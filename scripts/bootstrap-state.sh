#!/usr/bin/env bash
# Creates the S3 bucket and DynamoDB table that hold Terraform's remote state.
#
# Run this ONCE, before the first `terraform init`. It cannot live in the
# Terraform configuration itself, because the backend has to exist before
# Terraform can store state in it.

set -euo pipefail

BUCKET="${TF_STATE_BUCKET:-assessment-iii-tfstate-gsharp23}"
TABLE="${TF_LOCK_TABLE:-assessment-iii-tf-locks}"
REGION="${AWS_REGION:-us-east-1}"

echo ">> Account: $(aws sts get-caller-identity --query Account --output text)"
echo ">> Bucket:  $BUCKET"
echo ">> Table:   $TABLE"

# --- State bucket ---
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo ">> Bucket already exists, skipping"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"

  # Versioning lets you recover a state file you damaged.
  aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled

  # State contains resource details - encrypt it at rest and keep it private.
  aws s3api put-bucket-encryption --bucket "$BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

  echo ">> Bucket created"
fi

# --- Lock table ---
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo ">> Lock table already exists, skipping"
else
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null
  echo ">> Lock table created"
fi

echo
echo ">> Backend is ready. Next:  terraform -chdir=terraform init"
