#!/usr/bin/env bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

INSTANCE_ID="${INSTANCE_ID:-}"
TABLE_NAME="${TABLE_NAME:-lottery-checker-search-history}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
ROLE_NAME="${ROLE_NAME:-lottery-checker-ec2-role}"
INSTANCE_PROFILE_NAME="${INSTANCE_PROFILE_NAME:-lottery-checker-ec2-profile}"
INLINE_POLICY_NAME="${INLINE_POLICY_NAME:-lottery-checker-dynamodb-access}"
CALLER_POLICY_NAME="${CALLER_POLICY_NAME:-lottery-checker-ec2-association-access}"
SKIP_CALLER_PERMISSION_GRANT="${SKIP_CALLER_PERMISSION_GRANT:-false}"
SKIP_METADATA_OPTIONS="${SKIP_METADATA_OPTIONS:-false}"

usage() {
  cat <<'EOF'
Usage:
  ./attach-ec2-dynamodb-role.sh --instance-id <i-xxxxxxxxxxxxxxxxx> [options]

Options:
  --table-name <name>              Default: lottery-checker-search-history
  --region <region>                Default: ap-northeast-1
  --role-name <name>               Default: lottery-checker-ec2-role
  --instance-profile-name <name>   Default: lottery-checker-ec2-profile
  --inline-policy-name <name>      Default: lottery-checker-dynamodb-access
  --caller-policy-name <name>      Default: lottery-checker-ec2-association-access
  --skip-caller-permission-grant   Do not auto-grant EC2 association permissions to current IAM user
  --skip-metadata-options          Do not change IMDS settings
  -h, --help                       Show help
EOF
}

require_arg_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "[ERROR] Missing value for ${flag}"
    usage
    exit 1
  fi
}

print_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --instance-id)
      require_arg_value "$1" "${2:-}"
      INSTANCE_ID="$2"
      shift 2
      ;;
    --table-name)
      require_arg_value "$1" "${2:-}"
      TABLE_NAME="$2"
      shift 2
      ;;
    --region)
      require_arg_value "$1" "${2:-}"
      AWS_REGION="$2"
      shift 2
      ;;
    --role-name)
      require_arg_value "$1" "${2:-}"
      ROLE_NAME="$2"
      shift 2
      ;;
    --instance-profile-name)
      require_arg_value "$1" "${2:-}"
      INSTANCE_PROFILE_NAME="$2"
      shift 2
      ;;
    --inline-policy-name)
      require_arg_value "$1" "${2:-}"
      INLINE_POLICY_NAME="$2"
      shift 2
      ;;
    --caller-policy-name)
      require_arg_value "$1" "${2:-}"
      CALLER_POLICY_NAME="$2"
      shift 2
      ;;
    --skip-caller-permission-grant)
      SKIP_CALLER_PERMISSION_GRANT="true"
      shift 1
      ;;
    --skip-metadata-options)
      SKIP_METADATA_OPTIONS="true"
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print_error "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${INSTANCE_ID}" ]]; then
  print_error "--instance-id is required."
  usage
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  print_error "AWS CLI is not installed."
  exit 1
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  print_error "AWS credentials are not configured."
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
TABLE_ARN="arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
CALLER_USER_NAME=""
if [[ "${CALLER_ARN}" == *":user/"* ]]; then
  CALLER_USER_PATH="${CALLER_ARN##*:user/}"
  CALLER_USER_NAME="${CALLER_USER_PATH##*/}"
fi

print_info "Attaching EC2 IAM role for DynamoDB access"
print_info "Account: ${ACCOUNT_ID}"
print_info "Region: ${AWS_REGION}"
print_info "Instance: ${INSTANCE_ID}"
print_info "Table: ${TABLE_NAME}"
print_info "Role: ${ROLE_NAME}"
print_info "Instance profile: ${INSTANCE_PROFILE_NAME}"
print_info "Caller ARN: ${CALLER_ARN}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

TRUST_POLICY_PATH="${TMP_DIR}/trust-policy.json"
INLINE_POLICY_PATH="${TMP_DIR}/dynamodb-policy.json"
CALLER_POLICY_PATH="${TMP_DIR}/caller-ec2-policy.json"

cat >"${TRUST_POLICY_PATH}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

cat >"${INLINE_POLICY_PATH}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LotteryCheckerDynamoAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:DescribeTable"
      ],
      "Resource": "${TABLE_ARN}"
    }
  ]
}
EOF

cat >"${CALLER_POLICY_PATH}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Ec2InstanceProfileAssociationOps",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeIamInstanceProfileAssociations",
        "ec2:AssociateIamInstanceProfile",
        "ec2:ReplaceIamInstanceProfileAssociation",
        "ec2:ModifyInstanceMetadataOptions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassLotteryCheckerRoleToEc2",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "${ROLE_ARN}",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ec2.amazonaws.com"
        }
      }
    }
  ]
}
EOF

print_info "Ensuring IAM role exists..."
if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  print_warn "Role already exists: ${ROLE_NAME}"
else
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${TRUST_POLICY_PATH}" \
    --description "LotteryChecker EC2 role for DynamoDB search history" >/dev/null
  print_info "Created role: ${ROLE_NAME}"
fi

print_info "Applying inline policy to role..."
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${INLINE_POLICY_NAME}" \
  --policy-document "file://${INLINE_POLICY_PATH}" >/dev/null
print_info "Policy applied: ${INLINE_POLICY_NAME}"

if [[ "${SKIP_CALLER_PERMISSION_GRANT}" == "true" ]]; then
  print_warn "Skipped caller permission grant."
elif [[ -z "${CALLER_USER_NAME}" ]]; then
  print_warn "Caller is not an IAM user ARN. Cannot auto-grant caller permissions."
else
  print_info "Ensuring caller user has EC2 profile-association permissions..."
  if CALLER_GRANT_OUTPUT="$(aws iam put-user-policy \
    --user-name "${CALLER_USER_NAME}" \
    --policy-name "${CALLER_POLICY_NAME}" \
    --policy-document "file://${CALLER_POLICY_PATH}" 2>&1)"; then
    print_info "Caller inline policy applied: ${CALLER_POLICY_NAME} (user: ${CALLER_USER_NAME})"
    sleep 5
  else
    print_warn "Cannot auto-grant caller permissions. Continue with current permissions."
    print_warn "AWS message: ${CALLER_GRANT_OUTPUT}"
  fi
fi

print_info "Ensuring instance profile exists..."
if aws iam get-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" >/dev/null 2>&1; then
  print_warn "Instance profile already exists: ${INSTANCE_PROFILE_NAME}"
else
  aws iam create-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" >/dev/null
  print_info "Created instance profile: ${INSTANCE_PROFILE_NAME}"
fi

ROLE_COUNT="$(aws iam get-instance-profile \
  --instance-profile-name "${INSTANCE_PROFILE_NAME}" \
  --query "length(InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'])" \
  --output text)"

TOTAL_ROLE_COUNT="$(aws iam get-instance-profile \
  --instance-profile-name "${INSTANCE_PROFILE_NAME}" \
  --query "length(InstanceProfile.Roles)" \
  --output text)"

if [[ "${ROLE_COUNT}" != "0" ]]; then
  print_warn "Role is already attached to instance profile."
elif [[ "${TOTAL_ROLE_COUNT}" != "0" ]]; then
  print_error "Instance profile ${INSTANCE_PROFILE_NAME} already contains another role. Use a different profile name."
  exit 1
else
  print_info "Attaching role to instance profile..."
  aws iam add-role-to-instance-profile \
    --instance-profile-name "${INSTANCE_PROFILE_NAME}" \
    --role-name "${ROLE_NAME}" >/dev/null
  print_info "Role attached to instance profile."
  sleep 10
fi

print_info "Associating instance profile with EC2 instance..."
ASSOCIATION_ID="$(aws ec2 describe-iam-instance-profile-associations \
  --region "${AWS_REGION}" \
  --filters "Name=instance-id,Values=${INSTANCE_ID}" "Name=state,Values=associated" \
  --query "IamInstanceProfileAssociations[0].AssociationId" \
  --output text)"

CURRENT_PROFILE_ARN="$(aws ec2 describe-iam-instance-profile-associations \
  --region "${AWS_REGION}" \
  --filters "Name=instance-id,Values=${INSTANCE_ID}" "Name=state,Values=associated" \
  --query "IamInstanceProfileAssociations[0].IamInstanceProfile.Arn" \
  --output text)"

if [[ "${ASSOCIATION_ID}" == "None" || -z "${ASSOCIATION_ID}" ]]; then
  aws ec2 associate-iam-instance-profile \
    --region "${AWS_REGION}" \
    --instance-id "${INSTANCE_ID}" \
    --iam-instance-profile "Name=${INSTANCE_PROFILE_NAME}" >/dev/null
  print_info "Associated instance profile to EC2."
elif [[ "${CURRENT_PROFILE_ARN}" == *"/${INSTANCE_PROFILE_NAME}" ]]; then
  print_warn "EC2 instance already uses instance profile: ${INSTANCE_PROFILE_NAME}"
else
  aws ec2 replace-iam-instance-profile-association \
    --region "${AWS_REGION}" \
    --association-id "${ASSOCIATION_ID}" \
    --iam-instance-profile "Name=${INSTANCE_PROFILE_NAME}" >/dev/null
  print_info "Replaced old instance profile with: ${INSTANCE_PROFILE_NAME}"
fi

if [[ "${SKIP_METADATA_OPTIONS}" != "true" ]]; then
  print_info "Setting IMDS options for container credential access (tokens required, hop limit 2)..."
  aws ec2 modify-instance-metadata-options \
    --region "${AWS_REGION}" \
    --instance-id "${INSTANCE_ID}" \
    --http-endpoint enabled \
    --http-tokens required \
    --http-put-response-hop-limit 2 >/dev/null
else
  print_warn "Skipped metadata options update."
fi

print_info "Done."
print_info "Next step: restart app container on EC2 so app re-initializes DynamoDB store."
echo "cd ~/lottery-checker && bash deploy/ec2/update.sh"
