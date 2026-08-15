#!/usr/bin/env bash
# Brings the whole stack up locally and loads the knowledge base.
# This is the fastest way to see the app working before touching AWS.
#
#   ./scripts/local-up.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo ">> No .env found - creating one from .env.example"
  cp .env.example .env
  echo "!! Edit .env and set POSTGRES_PASSWORD and your AWS credentials, then re-run."
  exit 1
fi

# Bedrock needs credentials. On EC2 the instance role supplies them, but locally
# they have to be passed into the container - pull them from the AWS CLI config
# so they never have to be pasted into .env by hand.
. ./.env
if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
  export AWS_ACCESS_KEY_ID="$(aws configure get aws_access_key_id)"
  export AWS_SECRET_ACCESS_KEY="$(aws configure get aws_secret_access_key)"
  export AWS_SESSION_TOKEN="$(aws configure get aws_session_token || true)"

  if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    echo "!! No AWS credentials found. Run 'aws configure' or set them in .env."
    exit 1
  fi
  echo ">> Using AWS credentials from the AWS CLI config"
fi

echo ">> Building and starting the three services"
docker compose up -d --build

echo ">> Waiting for the API to become healthy"
for i in $(seq 1 30); do
  if curl -fsS http://localhost/api/health 2>/dev/null | grep -q '"status": *"ok"'; then
    echo ">> API is healthy"
    break
  fi
  printf '.'
  sleep 5
  if [ "$i" = "30" ]; then
    echo
    echo "!! API never became healthy. Logs:"
    docker compose logs --tail 50 api
    exit 1
  fi
done

echo ">> Loading the corpus into pgvector (skips if already loaded)"
docker compose exec -T api python ingest.py

echo
echo ">> Ready. Open http://localhost"
echo ">> Try:  curl -X POST http://localhost/api/chat -H 'Content-Type: application/json' -d '{\"question\":\"How tall can a fence be?\"}'"
