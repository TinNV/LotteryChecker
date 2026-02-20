# AWS Deploy (Simple)

This setup deploys `LotteryChecker` to AWS using:
- Docker image in Amazon ECR
- AWS App Runner service created by CloudFormation

It is designed to be a low-ops deployment with one public HTTPS endpoint.

If your current priority is minimum cost and simplest setup, use:
- `deploy/ec2/README.md` (single VM with Docker Compose, no ECR/App Runner)

## Prerequisites

- AWS CLI configured (`aws sts get-caller-identity` must work)
- Docker installed and running
- Permission to use:
  - CloudFormation (create/update/describe stacks)
  - IAM (create role for App Runner image pull)
  - ECR (describe/create repo, login, push image)
  - App Runner (create/update/describe service)

### Minimum IAM actions (summary)

- `ecr:DescribeRepositories`
- `ecr:CreateRepository`
- `ecr:GetAuthorizationToken`
- `ecr:BatchCheckLayerAvailability`
- `ecr:InitiateLayerUpload`
- `ecr:UploadLayerPart`
- `ecr:CompleteLayerUpload`
- `ecr:PutImage`
- `apprunner:CreateService`
- `apprunner:UpdateService`
- `apprunner:DescribeService`
- `cloudformation:ValidateTemplate`
- `cloudformation:CreateStack`
- `cloudformation:UpdateStack`
- `cloudformation:DescribeStacks`
- `iam:CreateRole`
- `iam:AttachRolePolicy`
- `iam:PassRole`

## Deploy

### Linux / macOS (Bash)

```bash
cd deploy/aws
chmod +x deploy-simple.sh
./deploy-simple.sh
```

### Windows (PowerShell)

```powershell
cd deploy\aws
.\deploy-simple.ps1
```

## Optional Parameters

Both scripts support:
- `ProjectName` / `PROJECT_NAME` (default: `lottery-checker`)
- `StackName` / `STACK_NAME` (default: `<project>-app`)
- `AwsRegion` / `AWS_REGION` (default: `ap-northeast-1`)
- `EcrRepository` / `ECR_REPOSITORY` (default: `<project>`)
- `ImageTag` / `IMAGE_TAG` (default: UTC timestamp)
- `InstanceCpu` / `INSTANCE_CPU` (default: `1 vCPU`)
- `InstanceMemory` / `INSTANCE_MEMORY` (default: `2 GB`)

Examples:

```bash
PROJECT_NAME=lottery-checker AWS_REGION=ap-northeast-1 ./deploy-simple.sh
```

```powershell
.\deploy-simple.ps1 -ProjectName lottery-checker -AwsRegion ap-northeast-1
```

## Utility Script: Create DynamoDB Search Table

For the EC2 admin dashboard search history feature, you can auto-create DynamoDB table + TTL:

### Linux / macOS

```bash
cd deploy/aws
chmod +x create-dynamodb-search-history.sh
./create-dynamodb-search-history.sh
```

### Windows (PowerShell)

```powershell
cd deploy\aws
.\create-dynamodb-search-history.ps1
```

## Utility Script: Attach EC2 Role for DynamoDB

If admin page shows `NoCredentialsError: Unable to locate credentials`, attach an IAM role to EC2:
- grants DynamoDB access to the app table
- creates/uses instance profile
- associates profile to target EC2
- auto-grants missing EC2 association permissions to current IAM user (if possible)
- sets IMDS options (`http-tokens required`, `hop-limit 2`) for Dockerized app credential access

Find target instance ID:

```bash
aws ec2 describe-instances --region ap-northeast-1 --query "Reservations[].Instances[].[InstanceId,PublicIpAddress,State.Name,Tags]" --output table
```

### Linux / macOS

```bash
cd deploy/aws
chmod +x attach-ec2-dynamodb-role.sh
./attach-ec2-dynamodb-role.sh --instance-id i-xxxxxxxxxxxxxxxxx --region ap-northeast-1 --table-name lottery-checker-search-history
```

### Windows (PowerShell)

```powershell
cd deploy\aws
.\attach-ec2-dynamodb-role.ps1 -InstanceId i-xxxxxxxxxxxxxxxxx -AwsRegion ap-northeast-1 -TableName lottery-checker-search-history
```

Optional:
- PowerShell: `-CallerPolicyName`, `-SkipCallerPermissionGrant`, `-SkipMetadataOptions`
- Bash: `--caller-policy-name`, `--skip-caller-permission-grant`, `--skip-metadata-options`

After script finishes, restart app on EC2:

```bash
cd ~/lottery-checker
bash deploy/ec2/update.sh
```

Minimum IAM actions required by this utility:
- `iam:GetRole`
- `iam:CreateRole`
- `iam:PutRolePolicy`
- `iam:GetInstanceProfile`
- `iam:CreateInstanceProfile`
- `iam:AddRoleToInstanceProfile`
- `iam:PutUserPolicy` (only if using auto-grant for current caller)
- `ec2:DescribeIamInstanceProfileAssociations`
- `ec2:AssociateIamInstanceProfile`
- `ec2:ReplaceIamInstanceProfileAssociation`
- `ec2:ModifyInstanceMetadataOptions`
- `sts:GetCallerIdentity`

## Deployment Output

After deploy, scripts create:
- `deploy/aws/deployment-config.json`

This file includes:
- deployed image URI
- App Runner service URL
- stack and region info

## Update Deployment

Run deploy script again. It builds a new image tag, pushes it, and updates the stack.

## Cleanup

### Linux / macOS

```bash
cd deploy/aws
chmod +x cleanup-simple.sh
./cleanup-simple.sh
```

Delete ECR repository too:

```bash
DELETE_ECR=true ./cleanup-simple.sh
```

### Windows

```powershell
cd deploy\aws
.\cleanup-simple.ps1
```

Delete ECR repository too:

```powershell
.\cleanup-simple.ps1 -DeleteEcr
```
