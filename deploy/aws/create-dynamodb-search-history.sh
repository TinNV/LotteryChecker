#!/usr/bin/env bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

TABLE_NAME="${TABLE_NAME:-lottery-checker-search-history}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
TTL_ATTRIBUTE="${TTL_ATTRIBUTE:-ttl_epoch}"

print_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

print_info "Creating/validating DynamoDB search history resources"
print_info "Table: ${TABLE_NAME}"
print_info "Region: ${AWS_REGION}"
print_info "TTL attribute: ${TTL_ATTRIBUTE}"

if ! command -v aws >/dev/null 2>&1; then
  print_error "AWS CLI is not installed."
  exit 1
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  print_error "AWS credentials are not configured."
  exit 1
fi

print_info "Ensuring DynamoDB table exists..."
if aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" >/dev/null 2>&1; then
  print_warn "Table ${TABLE_NAME} already exists."
else
  aws dynamodb create-table \
    --table-name "${TABLE_NAME}" \
    --attribute-definitions \
      AttributeName=pk,AttributeType=S \
      AttributeName=sk,AttributeType=S \
    --key-schema \
      AttributeName=pk,KeyType=HASH \
      AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "${AWS_REGION}" >/dev/null
  print_info "Created table ${TABLE_NAME}"
fi

print_info "Waiting until table exists..."
aws dynamodb wait table-exists \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}"

TTL_STATUS="$(
  aws dynamodb describe-time-to-live \
    --table-name "${TABLE_NAME}" \
    --region "${AWS_REGION}" \
    --query 'TimeToLiveDescription.TimeToLiveStatus' \
    --output text 2>/dev/null || echo "DISABLED"
)"

TTL_ATTRIBUTE_CURRENT="$(
  aws dynamodb describe-time-to-live \
    --table-name "${TABLE_NAME}" \
    --region "${AWS_REGION}" \
    --query 'TimeToLiveDescription.AttributeName' \
    --output text 2>/dev/null || echo ""
)"

if [[ "${TTL_STATUS}" == "ENABLED" || "${TTL_STATUS}" == "ENABLING" ]] && [[ "${TTL_ATTRIBUTE_CURRENT}" == "${TTL_ATTRIBUTE}" ]]; then
  print_warn "TTL is already ${TTL_STATUS} on attribute ${TTL_ATTRIBUTE}."
else
  print_info "Enabling TTL..."
  aws dynamodb update-time-to-live \
    --table-name "${TABLE_NAME}" \
    --time-to-live-specification "Enabled=true,AttributeName=${TTL_ATTRIBUTE}" \
    --region "${AWS_REGION}" >/dev/null
  print_info "TTL update requested for attribute ${TTL_ATTRIBUTE}."
fi

print_info "Done."
print_info "Set these env vars on EC2 before deploy:"
echo "export AWS_REGION=${AWS_REGION}"
echo "export DYNAMODB_SEARCH_TABLE=${TABLE_NAME}"
echo "export SEARCH_HISTORY_TTL_DAYS=30"
