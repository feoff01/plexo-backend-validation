#!/usr/bin/env bash
# Deploy do backend na EC2 (Ubuntu + Docker), a partir do Git Bash no Windows — e também do
# GitHub Actions (.github/workflows/deploy.yml usa este mesmo script; fonte única de verdade).
# Uso: deploy/deploy.sh [-k caminho.pem] [-h ip] [--sem-env] [--sem-migrar]
#   1) empacota o repo (sem .venv/.git/tests) e envia por ssh;
#   2) envia o .env local + deploy/env.prod.overrides como .env do servidor (pule com --sem-env);
#   3) build da imagem;
#   4) `alembic upgrade head` num container efêmero (idempotente; pule com --sem-migrar);
#   5) `docker compose up -d` remoto e mostra /health.
set -euo pipefail
cd "$(dirname "$0")/.."

CHAVE="${PLEXO_SSH_KEY:-/c/Users/gabri/Downloads/projsoft26b.pem}"
HOST="${PLEXO_SSH_HOST:-3.236.177.183}"
USUARIO="${PLEXO_SSH_USER:-ubuntu}"
DESTINO="~/plexo/backend"
ENVIAR_ENV=1
MIGRAR=1
while [ $# -gt 0 ]; do
  case "$1" in
    -k) CHAVE="$2"; shift 2 ;;
    -h) HOST="$2"; shift 2 ;;
    --sem-env) ENVIAR_ENV=0; shift ;;
    --sem-migrar) MIGRAR=0; shift ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done
SSH=(ssh -o StrictHostKeyChecking=accept-new -i "$CHAVE" "$USUARIO@$HOST")

echo "== 1/5 enviando código para $USUARIO@$HOST:$DESTINO"
"${SSH[@]}" "mkdir -p $DESTINO"
tar --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache \
    --exclude=tests --exclude=diagrama --exclude='.env*' -czf - . | "${SSH[@]}" "tar -xzf - -C $DESTINO"

if [ "$ENVIAR_ENV" = 1 ]; then
  echo "== 2/5 enviando .env (dev) + sobrescritas de produção (o conteúdo nunca é impresso)"
  # `tr -d '\r'`: rodando do Git Bash, os arquivos da árvore podem estar em CRLF e o \r entraria no
  # VALOR de cada variável do .env remoto — CORS_ORIGINS é JSON e um \r ali derruba a API na subida.
  { cat .env; echo; echo "# --- sobrescritas de produção (deploy/env.prod.overrides) ---"; cat deploy/env.prod.overrides; } \
    | tr -d '\r' | "${SSH[@]}" "umask 077 && cat > $DESTINO/.env"
else
  echo "== 2/5 .env do servidor mantido"
fi

# Caddyfile ANTES do build: sintaxe inválida aqui não falha o deploy — ela põe o contêiner do
# Caddy em loop de restart, e o loop de restart É a indisponibilidade. `caddy validate` roda num
# contêiner descartável, sem tocar no que está no ar, e o `set -e` do script aborta antes de
# qualquer coisa subir.
echo "== 3/6 validando o Caddyfile"
"${SSH[@]}" "cd $DESTINO && docker run --rm -v \"\$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro\"   caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile"

echo "== 4/6 build da imagem"
# `set -o pipefail` NO LADO REMOTO: o pipefail daqui não alcança o shell do servidor e, sem ele,
# `docker compose build | tail` devolveria o código do `tail` (0) mesmo com o build quebrado.
"${SSH[@]}" "set -o pipefail; cd $DESTINO && docker compose build 2>&1 | tail -30"

# Migrations ANTES de subir o código novo (append-only ⇒ idempotente; se já estiver em head, não faz nada).
# O alembic/env.py lê DATABASE_URL do ARQUIVO .env, que não entra na imagem: montamos o do servidor.
# --user root porque o .env é 0600 do usuário do host e o container roda como `plexo` (uid 10001).
if [ "$MIGRAR" = 1 ]; then
  echo "== 5/6 alembic upgrade head"
  "${SSH[@]}" "cd $DESTINO && docker compose run --rm --no-deps --user root \
    -v \"\$PWD/.env:/srv/plexo/.env:ro\" api python -m alembic upgrade head"
else
  echo "== 5/6 migrations puladas (--sem-migrar)"
fi

echo "== 6/6 up"
"${SSH[@]}" "set -o pipefail; cd $DESTINO && docker compose up -d --remove-orphans 2>&1 | tail -8 && sleep 8 && docker compose ps && \
  echo '--- health (interno)' && (docker compose exec -T api curl -fsS http://127.0.0.1:8000/health || true)"
echo "== pronto: http://$HOST/health (HTTP) · https://3-236-177-183.sslip.io/health (quando a 443 abrir no Security Group — ver deploy/README-tls.md)"
