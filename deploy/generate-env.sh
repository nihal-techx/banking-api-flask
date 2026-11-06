#!/usr/bin/env bash
# Creates .env.prod with fresh random secrets. Refuses to overwrite an existing file.
# Usage: bash deploy/generate-env.sh <site-address> [output-file]
set -euo pipefail

SITE="${1:?usage: bash deploy/generate-env.sh <site-address> [output-file]}"
OUT="${2:-.env.prod}"

if [ -e "$OUT" ]; then
  echo "$OUT already exists, refusing to overwrite it" >&2
  exit 1
fi

rand() { openssl rand -hex 24; }  # hex: no characters that need escaping in URLs

umask 077
cat > "$OUT" << EOF
SITE_ADDRESS=$SITE
IMAGE_TAG=latest
POSTGRES_PASSWORD=$(rand)
APP_DB_PASSWORD=$(rand)
REDIS_PASSWORD=$(rand)
RABBITMQ_PASSWORD=$(rand)
SECRET_KEY=$(rand)
JWT_SECRET_KEY=$(rand)
EOF
echo "wrote $OUT"