param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [Parameter(Mandatory = $true)]
    [string]$KeyFile,
    [string]$RemoteUser = "ec2-user",
    [string]$RemoteDir = "~/lottery-checker",
    [string]$LocalEnvFile = "",
    [int]$Port = 22
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
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

if (-not (Get-Command scp -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "scp is not installed."
    exit 1
}

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "ssh is not installed."
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

if ([string]::IsNullOrWhiteSpace($LocalEnvFile)) {
    $LocalEnvFile = Join-Path $ProjectRoot ".env"
}

if (-not (Test-Path $LocalEnvFile)) {
    Write-ErrMsg ".env file not found: $LocalEnvFile"
    exit 1
}

if (-not (Test-Path $KeyFile)) {
    Write-ErrMsg "SSH key file not found: $KeyFile"
    exit 1
}

$LocalEnvFile = (Resolve-Path $LocalEnvFile).Path
$KeyPath = (Resolve-Path $KeyFile).Path
$RemoteEnvPath = "$RemoteDir/.env"

Write-Info "Ensuring remote directory exists: $RemoteDir"
ssh -i $KeyPath -p $Port -o StrictHostKeyChecking=accept-new "$RemoteUser@$HostName" "mkdir -p $RemoteDir"
Assert-Success "Failed to create remote directory: $RemoteDir"

Write-Info "Copying .env to ${RemoteUser}@${HostName}:${RemoteDir}/.env"
scp -i $KeyPath -P $Port -o StrictHostKeyChecking=accept-new $LocalEnvFile "$RemoteUser@$HostName`:$RemoteEnvPath"
Assert-Success "Failed to copy .env via scp."

Write-Info "Setting secure permission on remote .env"
ssh -i $KeyPath -p $Port -o StrictHostKeyChecking=accept-new "$RemoteUser@$HostName" "chmod 600 $RemoteEnvPath && ls -l $RemoteEnvPath"
Assert-Success "Failed to set permission on remote .env."

Write-Info "Done."
