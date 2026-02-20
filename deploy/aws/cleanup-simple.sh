#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-lottery-checker}"
STACK_NAME="${STACK_NAME:-${PROJECT_NAME}-app}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
ECR_REPOSITORY="${ECR_REPOSITORY:-${PROJECT_NAME}}"
DELETE_ECR="${DELETE_ECR:-false}"

echo "[INFO] Cleaning up AWS resources for ${PROJECT_NAME}"
echo "[INFO] Stack: ${STACK_NAME}"
echo "[INFO] Region: ${AWS_REGION}"

if ! command -v aws >/dev/null 2>&1; then
  echo "[ERROR] AWS CLI is not installed."
  exit 1
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "[ERROR] AWS credentials are not configured."
  exit 1
fi

if aws cloudformation describe-stacks --stack-name "${STACK_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  echo "[INFO] Deleting CloudFormation stack..."
  aws cloudformation delete-stack --stack-name "${STACK_NAME}" --region "${AWS_REGION}"
  aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" --region "${AWS_REGION}"
  echo "[INFO] Stack deleted."
else
  echo "[WARN] Stack ${STACK_NAME} does not exist."
fi

if [ "${DELETE_ECR}" = "true" ]; then
  if aws ecr describe-repositories --repository-names "${ECR_REPOSITORY}" --region "${AWS_REGION}" >/dev/null 2>&1; then
    echo "[INFO] Deleting ECR repository ${ECR_REPOSITORY}..."
    aws ecr delete-repository \
      --repository-name "${ECR_REPOSITORY}" \
      --force \
      --region "${AWS_REGION}" >/dev/null
    echo "[INFO] ECR repository deleted."
  else
    echo "[WARN] ECR repository ${ECR_REPOSITORY} does not exist."
  fi
else
  echo "[INFO] ECR repository kept. Set DELETE_ECR=true to remove it."
fi
