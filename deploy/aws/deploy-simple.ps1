param(
    [string]$ProjectName = "lottery-checker",
    [string]$StackName = "",
    [string]$AwsRegion = "ap-northeast-1",
    [string]$EcrRepository = "",
    [string]$ImageTag = "",
    [string]$InstanceCpu = "1 vCPU",
    [string]$InstanceMemory = "2 GB"
)

$ErrorActionPreference = "Stop"

# PowerShell 7 may turn non-zero native exit codes into terminating errors.
# Disable that behavior so existence checks can branch on $LASTEXITCODE.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ([string]::IsNullOrWhiteSpace($StackName)) {
    $StackName = "$ProjectName-app"
}

if ([string]::IsNullOrWhiteSpace($EcrRepository)) {
    $EcrRepository = $ProjectName
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$TemplateFile = Join-Path $ScriptDir "cloudformation-simple.yaml"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrMsg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Assert-Success {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Write-Info "Deploying LotteryChecker to AWS (simple mode)"
Write-Info "Project: $ProjectName"
Write-Info "Stack: $StackName"
Write-Info "Region: $AwsRegion"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "AWS CLI is not installed."
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "Docker is not installed."
    exit 1
}

if (-not (Test-Path $TemplateFile)) {
    Write-ErrMsg "Template file not found: $TemplateFile"
    exit 1
}

aws sts get-caller-identity 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-ErrMsg "AWS credentials are not configured."
    exit 1
}

Write-Info "Validating CloudFormation template..."
aws cloudformation validate-template `
    --template-body "file://$TemplateFile" `
    --region $AwsRegion | Out-Null
Assert-Success "CloudFormation template validation failed."

$AccountId = aws sts get-caller-identity --query Account --output text
Assert-Success "Failed to read AWS account id."
$EcrRegistry = "$AccountId.dkr.ecr.$AwsRegion.amazonaws.com"
$ImageUri = "$EcrRegistry/$EcrRepository`:$ImageTag"

Write-Info "Ensuring ECR repository exists: $EcrRepository"
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    # PowerShell 5 treats native stderr as ErrorRecord when ErrorActionPreference=Stop.
    # Keep this check non-terminating so we can branch on the AWS CLI exit code.
    $DescribeOutput = aws ecr describe-repositories `
        --repository-names $EcrRepository `
        --region $AwsRegion 2>&1
    $DescribeExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($DescribeExitCode -eq 0) {
    Write-WarnMsg "ECR repository $EcrRepository already exists."
}
else {
    $DescribeText = ($DescribeOutput | Out-String).Trim()
    if ($DescribeText -and ($DescribeText -notmatch "RepositoryNotFoundException")) {
        Write-ErrMsg "Cannot query ECR repository. Check IAM permissions for ecr:DescribeRepositories."
        Write-ErrMsg "AWS message: $DescribeText"
        exit 1
    }

    aws ecr create-repository `
        --repository-name $EcrRepository `
        --image-scanning-configuration scanOnPush=true `
        --region $AwsRegion | Out-Null
    Assert-Success "Failed to create ECR repository."
    Write-Info "Created ECR repository $EcrRepository"
}

Write-Info "Logging in to ECR..."
$EcrPassword = aws ecr get-login-password --region $AwsRegion
Assert-Success "Failed to get ECR login password."
$EcrPassword | docker login --username AWS --password-stdin $EcrRegistry | Out-Null
Assert-Success "Docker login to ECR failed."

Write-Info "Building Docker image..."
docker build -t "$EcrRepository`:$ImageTag" $ProjectRoot
Assert-Success "Docker build failed."

Write-Info "Tagging and pushing image to ECR..."
docker tag "$EcrRepository`:$ImageTag" $ImageUri
Assert-Success "Docker tag failed."
docker push $ImageUri
Assert-Success "Docker push failed."

Write-Info "Deploying CloudFormation stack..."
aws cloudformation deploy `
    --stack-name $StackName `
    --template-file $TemplateFile `
    --parameter-overrides `
        "ProjectName=$ProjectName" `
        "ImageUri=$ImageUri" `
        "InstanceCpu=$InstanceCpu" `
        "InstanceMemory=$InstanceMemory" `
    --capabilities CAPABILITY_IAM `
    --region $AwsRegion `
    --no-fail-on-empty-changeset
Assert-Success "CloudFormation deploy failed."

Write-Info "Retrieving stack outputs..."
aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $AwsRegion `
    --query "Stacks[0].Outputs" `
    --output table
Assert-Success "Failed to retrieve stack outputs."

$ServiceUrl = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $AwsRegion `
    --query "Stacks[0].Outputs[?OutputKey=='ServiceUrl'].OutputValue" `
    --output text
Assert-Success "Failed to read ServiceUrl output."

$ServiceArn = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $AwsRegion `
    --query "Stacks[0].Outputs[?OutputKey=='ServiceArn'].OutputValue" `
    --output text
Assert-Success "Failed to read ServiceArn output."

$ConfigFile = Join-Path $ScriptDir "deployment-config.json"
$Config = [ordered]@{
    project_name = $ProjectName
    stack_name = $StackName
    region = $AwsRegion
    ecr_repository = $EcrRepository
    image_uri = $ImageUri
    service_url = $ServiceUrl
    service_arn = $ServiceArn
    deployed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

$Config | ConvertTo-Json | Set-Content -Path $ConfigFile -Encoding UTF8

Write-Info "Deployment config saved: $ConfigFile"
Write-Info "Deployment complete."
Write-Info "Service URL: $ServiceUrl"
