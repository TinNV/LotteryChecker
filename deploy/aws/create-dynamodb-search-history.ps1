param(
    [string]$TableName = "lottery-checker-search-history",
    [string]$AwsRegion = "ap-northeast-1",
    [string]$TtlAttribute = "ttl_epoch"
)

$ErrorActionPreference = "Stop"

# PowerShell 7 may turn non-zero native exit codes into terminating errors.
# Disable that behavior so existence checks can branch on $LASTEXITCODE.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

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

Write-Info "Creating/validating DynamoDB search history resources"
Write-Info "Table: $TableName"
Write-Info "Region: $AwsRegion"
Write-Info "TTL attribute: $TtlAttribute"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "AWS CLI is not installed."
    exit 1
}

aws sts get-caller-identity 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-ErrMsg "AWS credentials are not configured."
    exit 1
}

Write-Info "Ensuring DynamoDB table exists..."
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $DescribeOutput = aws dynamodb describe-table `
        --table-name $TableName `
        --region $AwsRegion 2>&1
    $DescribeExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($DescribeExitCode -eq 0) {
    Write-WarnMsg "Table $TableName already exists."
}
else {
    $DescribeText = ($DescribeOutput | Out-String).Trim()
    if ($DescribeText -and ($DescribeText -notmatch "ResourceNotFoundException")) {
        Write-ErrMsg "Cannot query DynamoDB table."
        Write-ErrMsg "AWS message: $DescribeText"
        exit 1
    }

    aws dynamodb create-table `
        --table-name $TableName `
        --attribute-definitions `
            AttributeName=pk,AttributeType=S `
            AttributeName=sk,AttributeType=S `
        --key-schema `
            AttributeName=pk,KeyType=HASH `
            AttributeName=sk,KeyType=RANGE `
        --billing-mode PAY_PER_REQUEST `
        --region $AwsRegion | Out-Null
    Assert-Success "Failed to create DynamoDB table."
    Write-Info "Created table $TableName"
}

Write-Info "Waiting until table exists..."
aws dynamodb wait table-exists `
    --table-name $TableName `
    --region $AwsRegion
Assert-Success "Table is not ready."

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $TtlStatusOutput = aws dynamodb describe-time-to-live `
        --table-name $TableName `
        --region $AwsRegion `
        --query "TimeToLiveDescription.TimeToLiveStatus" `
        --output text 2>&1
    $TtlStatusExitCode = $LASTEXITCODE

    if ($TtlStatusExitCode -eq 0) {
        $TtlStatus = ($TtlStatusOutput | Out-String).Trim()
    }
    else {
        $TtlStatus = "DISABLED"
    }

    $TtlAttributeOutput = aws dynamodb describe-time-to-live `
        --table-name $TableName `
        --region $AwsRegion `
        --query "TimeToLiveDescription.AttributeName" `
        --output text 2>&1
    $TtlAttributeExitCode = $LASTEXITCODE
    if ($TtlAttributeExitCode -eq 0) {
        $TtlAttributeCurrent = ($TtlAttributeOutput | Out-String).Trim()
    }
    else {
        $TtlAttributeCurrent = ""
    }
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

$TtlAlreadyEnabled = (($TtlStatus -eq "ENABLED") -or ($TtlStatus -eq "ENABLING")) -and ($TtlAttributeCurrent -eq $TtlAttribute)
if ($TtlAlreadyEnabled) {
    Write-WarnMsg "TTL is already $TtlStatus on attribute $TtlAttribute."
}
else {
    Write-Info "Enabling TTL..."
    aws dynamodb update-time-to-live `
        --table-name $TableName `
        --time-to-live-specification "Enabled=true,AttributeName=$TtlAttribute" `
        --region $AwsRegion | Out-Null
    Assert-Success "Failed to enable TTL."
    Write-Info "TTL update requested for attribute $TtlAttribute"
}

Write-Info "Done."
Write-Info "Set these env vars on EC2 before deploy:"
Write-Host "`$env:AWS_REGION = '$AwsRegion'"
Write-Host "`$env:DYNAMODB_SEARCH_TABLE = '$TableName'"
Write-Host "`$env:SEARCH_HISTORY_TTL_DAYS = '30'"
