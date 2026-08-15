#!/usr/bin/env bash
# Registers every GitHub secret and variable the workflows need, in one command.
#
#   ./scripts/set-secrets.sh
#
# Requires the GitHub CLI, authenticated:  gh auth login
# Values are read from your local .env and from ~/.aws/credentials, so nothing
# is typed on the command line where it would land in shell history.

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v gh >/dev/null; then
  echo "GitHub CLI not found. Install it: https://cli.github.com/"
  exit 1
fi

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill it in first."
  exit 1
fi

# Load .env without exporting it into anything else
set -a && . ./.env && set +a

echo ">> Repository: $(gh repo view --json nameWithOwner -q .nameWithOwner)"

# --- AWS credentials for the workflows ---
AWS_KEY_ID="${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id)}"
AWS_SECRET="${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key)}"

echo ">> Setting AWS credentials"
gh secret set AWS_ACCESS_KEY_ID     --body "$AWS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY --body "$AWS_SECRET"

# --- Application secrets ---
echo ">> Setting application secrets"
gh secret set POSTGRES_PASSWORD --body "$POSTGRES_PASSWORD"
gh secret set MEM0_API_KEY      --body "${MEM0_API_KEY:-}"

# --- SSH key the deploy job uses to reach EC2 ---
KEY_PATH="${EC2_SSH_KEY_PATH:-$HOME/aicloudops/aico-echo.pem}"
if [ -f "$KEY_PATH" ]; then
  echo ">> Setting EC2_SSH_KEY from $KEY_PATH"
  gh secret set EC2_SSH_KEY < "$KEY_PATH"
else
  echo "!! $KEY_PATH not found - set EC2_SSH_KEY manually or export EC2_SSH_KEY_PATH"
fi

# --- Non-secret variables ---
echo ">> Setting variables"
gh variable set EC2_KEY_NAME --body "${EC2_KEY_NAME:-aico-echo}"

echo
echo ">> Done. Current configuration:"
gh secret list
gh variable list
