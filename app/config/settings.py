"""Configuração do processo (variáveis de ambiente / plexo-backend/.env).

Tudo que é segredo é SecretStr: repr, logs e model_dump() mostram '**********'.
O que é REGRA DE NEGÓCIO não mora aqui — mora em engine.policy_versions (PolicyStore).
"""
from __future__ import annotations

import re
import urllib.parse
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent  # plexo-backend/

_PAPEL_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- banco -------------------------------------------------------------
    database_url: SecretStr = Field(description="login administrador (migrações, dev)")
    database_url_app: SecretStr | None = Field(default=None, description="login da API (membro de plexo_app)")
    database_url_service: SecretStr | None = Field(default=None, description="login dos jobs (membro de plexo_service)")
    db_set_role: bool = Field(default=True, description="emitir SET LOCAL ROLE dentro de cada transação "
                              "(necessário quando o login é administrador, como em dev)")
    db_role_app: str = "plexo_app"
    db_role_service: str = "plexo_service"
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_pool_max_idle_s: float = Field(default=240.0, description="F9: recicla conexão ociosa antes de o Aiven fechá-la (sintoma: 'server closed the connection unexpectedly')")

    # --- LLM ----------------------------------------------------------------
    llm_provider: str = "deepseek"
    llm_model: str = Field(default="deepseek-v4-pro", description="id exato faturável (decisão 2026-08-23: DeepSeek V4 Pro); NUNCA usado em regra de domínio")
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"))
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_stream: bool = Field(default=True, description="F9: síntese em stream (delta token a token no SSE); False = por frase, como antes")
    require_approved_prompts: bool = True

    # --- infra --------------------------------------------------------------
    redis_url: SecretStr | None = None
    env: str = "dev"

    # --- auth (F7) — sessão opaca em identity.sessions + cookie httpOnly ------
    auth_headers_dev: bool = Field(default=False, description="aceitar X-Plexo-User-Id/Scope-Id sem sessão "
                                   "(só dev e testes; NUNCA em produção)")
    sessao_ttl_h: int = Field(default=24 * 14, description="validade da sessão; deslizante a cada uso")
    sessao_renovar_apos_min: int = Field(default=15, description="só renova last_seen/expires se passou disto")
    cookie_nome: str = "plx_sessao"
    cookie_secure: bool = Field(default=True, description="false só em dev http")
    cookie_domain: str | None = Field(default=None, description="ex.: .plexo.com.br quando app e API são hosts distintos")
    cookie_samesite: str = Field(default="lax", description="lax em dev (mesmo site); none quando o frontend está em outra origem (exige COOKIE_SECURE=true)")
    cors_origins: list[str] = Field(default=["http://localhost:3000"], description="origens do frontend (credenciais)")
    login_max_falhas_email: int = 10
    login_max_falhas_ip: int = 50
    login_janela_min: int = 15
    cadastro_aberto: bool = True
    termos_versao: str = "termos-v1"
    privacidade_versao: str = "privacidade-v1"

    # ------------------------------------------------------------------ util
    @staticmethod
    def _normalizar_pg(url: str) -> str:
        """Aceita postgresql+psycopg:// (SQLAlchemy) e força sslmode=require (Aiven)."""
        url = re.sub(r"^postgres(ql)?(\+[a-z0-9]+)?://", "postgresql://", url)
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        q.setdefault("sslmode", "require")
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))

    def pg_conninfo(self, papel: str) -> str:
        """papel ∈ {'admin','app','service'}. Sem login próprio, cai no administrador + SET ROLE."""
        escolhido = {
            "admin": self.database_url,
            "app": self.database_url_app or self.database_url,
            "service": self.database_url_service or self.database_url,
        }[papel]
        return self._normalizar_pg(escolhido.get_secret_value())

    def papel_sql(self, qual: str) -> str:
        nome = {"app": self.db_role_app, "service": self.db_role_service}[qual]
        if not _PAPEL_RE.match(nome):
            raise ValueError("nome de papel inválido")
        return nome


@lru_cache
def get_settings() -> Settings:
    return Settings()
