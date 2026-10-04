# Backend de agentes da Plexo — API (uvicorn) e worker (arq) na mesma imagem; o comando muda no compose.
# Só o que a aplicação precisa em runtime: app/, prompts/, seeds/, sql/, alembic/ (migrations por CLI), tools/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/plexo

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY prompts ./prompts
COPY seeds ./seeds
COPY sql ./sql
COPY alembic ./alembic
COPY tools ./tools

# usuário sem privilégio
RUN useradd --create-home --uid 10001 plexo && chown -R plexo:plexo /srv/plexo
USER plexo

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# --proxy-headers: atrás do Caddy o esquema/host reais vêm dos cabeçalhos X-Forwarded-*.
#
# --forwarded-allow-ips: as REDES PRIVADAS, nunca `*`. A diferença não é de estilo — é o
# algoritmo que o uvicorn usa para escolher o IP (`_TrustedHosts.get_trusted_client_address`):
#
#   com "*"  (always_trust)  →  devolve x_forwarded_for[0]        ← a ponta ESQUERDA
#   com CIDR                 →  percorre em ordem REVERSA e devolve o primeiro não-confiável
#
# O Caddy ANEXA o peer real ao fim do cabeçalho. Com `*`, portanto, o uvicorn lia justamente a
# entrada que o cliente escreveu e ignorava a verdadeira. O efeito: `request.client.host` virava
# valor do atacante, e é ele que alimenta `login_max_falhas_ip` (força bruta sem teto, girando o
# header) e o `ip_address` de `identity.sessions`, `login_attempts` e `audit.activity_log` — o
# registro forense de um incidente, escrito por quem o causou.
#
# As redes privadas bastam porque `api` usa `expose:` e não `ports:` no compose: só um contêiner
# da própria rede alcança a 8000, e ele está sempre num desses intervalos. O peer externo real
# nunca está, então é ele que o laço reverso devolve. `uvicorn>=0.30` aceita CIDR (confirmado em
# 0.52.4: `_TrustedHosts` monta `trusted_networks` com `ipaddress.ip_network`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers",      "--forwarded-allow-ips", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
