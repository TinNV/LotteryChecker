param(
    [string]$ProjectName = "lottery-checker",
    [string]$StackName = "",
    [string]$AwsRegion = "ap-northeast-1",
    [string]$EcrRepository = "",
    [switch]$DeleteEcr
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($StackName)) {
    $StackName = "$ProjectName-app"
}

if ([string]::IsNullOrWhiteSpace($EcrRepository)) {
    $EcrRepository = $ProjectName
}

Write-Host "[INFO] Cleaning up AWS resources for $ProjectName" -ForegroundColor Green
Write-Host "[INFO] Stack: $StackName" -ForegroundColor Green
Write-Host "[INFO] Region: $AwsRegion" -ForegroundColor Green

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] AWS CLI is not installed." -ForegroundColor Red
    exit 1
}

aws sts get-caller-identity 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] AWS credentials are not configured." -ForegroundColor Red
    exit 1
}

$null = aws cloudformation describe-stacks --stack-name $StackName --region $AwsRegion 2>$null
$StackExists = ($LASTEXITCODE -eq 0)

if ($StackExists) {
    Write-Host "[INFO] Deleting CloudFormation stack..." -ForegroundColor Yellow
    aws cloudformation delete-stack --stack-name $StackName --region $AwsRegion
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to start stack deletion." -ForegroundColor Red
        exit 1
    }
    aws cloudformation wait stack-delete-complete --stack-name $StackName --region $AwsRegion
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Stack deletion did not complete successfully." -ForegroundColor Red
        exit 1
    }
    Write-Host "[INFO] Stack deleted." -ForegroundColor Green
}
else {
    Write-Host "[WARN] Stack $StackName does not exist." -ForegroundColor Yellow
}

if ($DeleteEcr) {
    $null = aws ecr describe-repositories --repository-names $EcrRepository --region $AwsRegion 2>$null
    $EcrExists = ($LASTEXITCODE -eq 0)

    if ($EcrExists) {
        Write-Host "[INFO] Deleting ECR repository $EcrRepository..." -ForegroundColor Yellow
        aws ecr delete-repository --repository-name $EcrRepository --force --region $AwsRegion | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to delete ECR repository." -ForegroundColor Red
            exit 1
        }
        Write-Host "[INFO] ECR repository deleted." -ForegroundColor Green
    }
    else {
        Write-Host "[WARN] ECR repository $EcrRepository does not exist." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[INFO] ECR repository kept. Use -DeleteEcr to remove it." -ForegroundColor Green
}
