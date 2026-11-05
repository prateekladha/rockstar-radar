#!/bin/sh
# App container entrypoint. If secrets-init populated the tmpfs (/secrets/app.env), load those
# RAM-only secrets into the environment before launching. Then build DATABASE_URL from the
# Vault-provided Postgres password. Local dev has no /secrets and just runs the app (env / .env).
set -e

if [ -f /secrets/app.env ]; then
  . /secrets/app.env
fi

# Build DATABASE_URL from the Vault password when not explicitly provided (prod path).
if [ -z "$DATABASE_URL" ] && [ -n "$POSTGRES_PASSWORD" ]; then
  export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER:-radar}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-postgres}:5432/${POSTGRES_DB:-radar}"
fi

exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips '*'
