#!/usr/bin/env bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/cloudformation-simple.yaml"

PROJECT_NAME="${PROJECT_NAME:-lottery-checker}"
STACK_NAME="${STACK_NAME:-${PROJECT_NAME}-app}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
ECR_REPOSITORY="${ECR_REPOSITORY:-${PROJECT_NAME}}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
INSTANCE_CPU="${INSTANCE_CPU:-1 vCPU}"
INSTANCE_MEMORY="${INSTANCE_MEMORY:-2 GB}"

print_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

print_info "Deploying LotteryChecker to AWS (simple mode)"
print_info "Project: ${PROJECT_NAME}"
print_info "Stack: ${STACK_NAME}"
print_info "Region: ${AWS_REGION}"

if ! command -v aws >/dev/null 2>&1; then
  print_error "AWS CLI is not installed."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  print_error "Docker is not installed."
  exit 1
fi

if [ ! -f "${TEMPLATE_FILE}" ]; then
  print_error "Template file not found: ${TEMPLATE_FILE}"
  exit 1
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  print_error "AWS credentials are not configured."
  exit 1
fi

print_info "Validating CloudFormation template..."
aws cloudformation validate-template \
  --template-body "file://${TEMPLATE_FILE}" \
  --region "${AWS_REGION}" >/dev/null

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

print_info "Ensuring ECR repository exists: ${ECR_REPOSITORY}"
if ! aws ecr describe-repositories \
  --repository-names "${ECR_REPOSITORY}" \
  --region "${AWS_REGION}" >/dev/null 2>&1; then
  aws ecr create-repository \
    --repository-name "${ECR_REPOSITORY}" \
    --image-scanning-configuration scanOnPush=true \
    --region "${AWS_REGION}" >/dev/null
  print_info "Created ECR repository ${ECR_REPOSITORY}"
else
  print_warn "ECR repository ${ECR_REPOSITORY} already exists."
fi

print_info "Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

print_info "Building Docker image..."
docker build -t "${ECR_REPOSITORY}:${IMAGE_TAG}" "${PROJECT_ROOT}"

print_info "Tagging and pushing image to ECR..."
docker tag "${ECR_REPOSITORY}:${IMAGE_TAG}" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

print_info "Deploying CloudFormation stack..."
aws cloudformation deploy \
  --stack-name "${STACK_NAME}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameter-overrides \
    "ProjectName=${PROJECT_NAME}" \
    "ImageUri=${IMAGE_URI}" \
    "InstanceCpu=${INSTANCE_CPU}" \
    "InstanceMemory=${INSTANCE_MEMORY}" \
  --capabilities CAPABILITY_IAM \
  --region "${AWS_REGION}" \
  --no-fail-on-empty-changeset

print_info "Retrieving stack outputs..."
aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Stacks[0].Outputs' \
  --output table

SERVICE_URL="$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='ServiceUrl'].OutputValue" \
  --output text)"

SERVICE_ARN="$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='ServiceArn'].OutputValue" \
  --output text)"

CONFIG_FILE="${SCRIPT_DIR}/deployment-config.json"
cat > "${CONFIG_FILE}" <<EOF
{
  "project_name": "${PROJECT_NAME}",
  "stack_name": "${STACK_NAME}",
  "region": "${AWS_REGION}",
  "ecr_repository": "${ECR_REPOSITORY}",
  "image_uri": "${IMAGE_URI}",
  "service_url": "${SERVICE_URL}",
  "service_arn": "${SERVICE_ARN}",
  "deployed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

print_info "Deployment config saved: ${CONFIG_FILE}"
print_info "Deployment complete."
print_info "Service URL: ${SERVICE_URL}"
