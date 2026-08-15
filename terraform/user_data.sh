#!/bin/bash
# Runs once on first boot. Installs Docker and writes the runtime .env by
# reading AWS Secrets Manager with the instance's IAM role - no secret is ever
# passed through Terraform state into the instance as plaintext user data.
exec > /var/log/user-data.log 2>&1
set -x

apt-get update -y
apt-get install -y ca-certificates curl gnupg jq unzip

# Docker Engine + the Compose plugin
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu

# AWS CLI, used below to read the secret
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp && /tmp/aws/install

# Application directory the deploy workflow copies files into
mkdir -p /home/ubuntu/app
chown -R ubuntu:ubuntu /home/ubuntu/app

# Pull the secrets and render the .env the compose file reads
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "${secret_name}" \
  --region "${aws_region}" \
  --query SecretString --output text)

cat > /home/ubuntu/app/.env <<ENVFILE
POSTGRES_USER=raguser
POSTGRES_DB=ragdb
POSTGRES_PASSWORD=$(echo "$SECRET" | jq -r .POSTGRES_PASSWORD)
MEM0_API_KEY=$(echo "$SECRET" | jq -r .MEM0_API_KEY)
AWS_REGION=${aws_region}
CHAT_MODEL_ID=us.amazon.nova-lite-v1:0
EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
LOG_LEVEL=INFO
ENVFILE

chown ubuntu:ubuntu /home/ubuntu/app/.env
chmod 600 /home/ubuntu/app/.env

echo "bootstrap complete" > /home/ubuntu/app/.bootstrap-done
