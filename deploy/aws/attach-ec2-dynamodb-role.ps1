param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceId,
    [string]$TableName = "lottery-checker-search-history",
    [string]$AwsRegion = "ap-northeast-1",
    [string]$RoleName = "lottery-checker-ec2-role",
    [string]$InstanceProfileName = "lottery-checker-ec2-profile",
    [string]$InlinePolicyName = "lottery-checker-dynamodb-access",
    [string]$CallerPolicyName = "lottery-checker-ec2-association-access",
    [switch]$SkipCallerPermissionGrant,
    [switch]$SkipMetadataOptions
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

function Invoke-AwsAllowError {
    param([scriptblock]$Command)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command 2>&1
        return @{
            ExitCode = $LASTEXITCODE
            Output = ($output | Out-String).Trim()
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-ErrMsg "AWS CLI is not installed."
    exit 1
}

$callerIdentityRaw = aws sts get-caller-identity --output json 2>$null
Assert-Success "AWS credentials are not configured for this machine."
$callerIdentity = $callerIdentityRaw | ConvertFrom-Json
$accountId = [string]$callerIdentity.Account
$callerArn = [string]$callerIdentity.Arn

if (-not $accountId) {
    Write-ErrMsg "Cannot resolve AWS account ID from sts get-caller-identity."
    exit 1
}

$tableArn = "arn:aws:dynamodb:${AwsRegion}:${accountId}:table/${TableName}"
$roleArn = "arn:aws:iam::${accountId}:role/${RoleName}"
$callerUserName = ""
if ($callerArn -match ":user/") {
    $callerUserPath = ($callerArn -split ":user/", 2)[1]
    if ($callerUserPath) {
        $callerUserName = ($callerUserPath -split "/")[-1]
    }
}

Write-Info "Attaching EC2 IAM role for DynamoDB access"
Write-Info "Account: $accountId"
Write-Info "Region: $AwsRegion"
Write-Info "Instance: $InstanceId"
Write-Info "Table: $TableName"
Write-Info "Role: $RoleName"
Write-Info "Instance profile: $InstanceProfileName"
Write-Info "Caller ARN: $callerArn"

$tempDir = Join-Path $env:TEMP ("lottery-checker-iam-" + [guid]::NewGuid().ToString("N"))
New-Item -Path $tempDir -ItemType Directory | Out-Null
$trustPolicyPath = Join-Path $tempDir "trust-policy.json"
$inlinePolicyPath = Join-Path $tempDir "dynamodb-policy.json"
$callerPolicyPath = Join-Path $tempDir "caller-ec2-policy.json"

$trustPolicyJson = @"
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
"@

$inlinePolicyJson = @"
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
      "Resource": "$tableArn"
    }
  ]
}
"@

$callerPolicyJson = @"
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
      "Resource": "$roleArn",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ec2.amazonaws.com"
        }
      }
    }
  ]
}
"@

$trustPolicyJson | Set-Content -Path $trustPolicyPath -Encoding ascii
$inlinePolicyJson | Set-Content -Path $inlinePolicyPath -Encoding ascii
$callerPolicyJson | Set-Content -Path $callerPolicyPath -Encoding ascii

$trustPolicyUri = "file://$($trustPolicyPath -replace '\\','/')"
$inlinePolicyUri = "file://$($inlinePolicyPath -replace '\\','/')"
$callerPolicyUri = "file://$($callerPolicyPath -replace '\\','/')"

try {
    Write-Info "Ensuring IAM role exists..."
    $getRole = Invoke-AwsAllowError { aws iam get-role --role-name $RoleName --output json }
    if ($getRole.ExitCode -eq 0) {
        Write-WarnMsg "Role already exists: $RoleName"
    }
    elseif ($getRole.Output -match "NoSuchEntity") {
        aws iam create-role `
            --role-name $RoleName `
            --assume-role-policy-document $trustPolicyUri `
            --description "LotteryChecker EC2 role for DynamoDB search history" | Out-Null
        Assert-Success "Failed to create role: $RoleName"
        Write-Info "Created role: $RoleName"
    }
    else {
        Write-ErrMsg "Cannot query IAM role."
        Write-ErrMsg "AWS message: $($getRole.Output)"
        exit 1
    }

    Write-Info "Applying inline policy to role..."
    aws iam put-role-policy `
        --role-name $RoleName `
        --policy-name $InlinePolicyName `
        --policy-document $inlinePolicyUri | Out-Null
    Assert-Success "Failed to put inline policy on role."
    Write-Info "Policy applied: $InlinePolicyName"

    if ($SkipCallerPermissionGrant) {
        Write-WarnMsg "Skipped caller permission grant."
    }
    elseif ([string]::IsNullOrWhiteSpace($callerUserName)) {
        Write-WarnMsg "Caller is not an IAM user ARN. Cannot auto-grant caller permissions."
    }
    else {
        Write-Info "Ensuring caller user has EC2 profile-association permissions..."
        $callerGrant = Invoke-AwsAllowError {
            aws iam put-user-policy `
                --user-name $callerUserName `
                --policy-name $CallerPolicyName `
                --policy-document $callerPolicyUri
        }
        if ($callerGrant.ExitCode -eq 0) {
            Write-Info "Caller inline policy applied: $CallerPolicyName (user: $callerUserName)"
            Start-Sleep -Seconds 5
        }
        else {
            Write-WarnMsg "Cannot auto-grant caller permissions. Continue with current permissions."
            Write-WarnMsg "AWS message: $($callerGrant.Output)"
        }
    }

    Write-Info "Ensuring instance profile exists..."
    $getProfile = Invoke-AwsAllowError { aws iam get-instance-profile --instance-profile-name $InstanceProfileName --output json }
    if ($getProfile.ExitCode -eq 0) {
        Write-WarnMsg "Instance profile already exists: $InstanceProfileName"
    }
    elseif ($getProfile.Output -match "NoSuchEntity") {
        aws iam create-instance-profile --instance-profile-name $InstanceProfileName | Out-Null
        Assert-Success "Failed to create instance profile: $InstanceProfileName"
        Write-Info "Created instance profile: $InstanceProfileName"
    }
    else {
        Write-ErrMsg "Cannot query instance profile."
        Write-ErrMsg "AWS message: $($getProfile.Output)"
        exit 1
    }

    $roleCountRaw = aws iam get-instance-profile `
        --instance-profile-name $InstanceProfileName `
        --query "length(InstanceProfile.Roles[?RoleName=='$RoleName'])" `
        --output text 2>$null
    Assert-Success "Failed to read instance profile role attachments."

    $totalRoleCountRaw = aws iam get-instance-profile `
        --instance-profile-name $InstanceProfileName `
        --query "length(InstanceProfile.Roles)" `
        --output text 2>$null
    Assert-Success "Failed to read instance profile role count."

    $roleAlreadyAttached = $false
    if ([int]$roleCountRaw -gt 0) {
        $roleAlreadyAttached = $true
    }

    if ($roleAlreadyAttached) {
        Write-WarnMsg "Role is already attached to instance profile."
    }
    elseif ([int]$totalRoleCountRaw -gt 0) {
        Write-ErrMsg "Instance profile $InstanceProfileName already contains another role. Use a different profile name."
        exit 1
    }
    else {
        Write-Info "Attaching role to instance profile..."
        aws iam add-role-to-instance-profile `
            --instance-profile-name $InstanceProfileName `
            --role-name $RoleName | Out-Null
        Assert-Success "Failed to add role to instance profile."
        Write-Info "Role attached to instance profile."
        Start-Sleep -Seconds 10
    }

    Write-Info "Validating EC2 instance..."
    $instanceLookup = Invoke-AwsAllowError {
        aws ec2 describe-instances `
            --region $AwsRegion `
            --instance-ids $InstanceId `
            --query "Reservations[0].Instances[0].InstanceId" `
            --output text
    }
    if ($instanceLookup.ExitCode -ne 0) {
        $instanceErr = ($instanceLookup.Output | Out-String).Trim()
        if ($instanceErr -match "UnauthorizedOperation" -or $instanceErr -match "ec2:DescribeInstances") {
            Write-WarnMsg "No permission for ec2:DescribeInstances. Continuing without instance pre-check."
        }
        else {
            Write-ErrMsg "Cannot query EC2 instance."
            Write-ErrMsg "AWS message: $instanceErr"
            exit 1
        }
    }
    else {
        $instanceLookupText = ($instanceLookup.Output | Out-String).Trim()
        if ($instanceLookupText -eq "None" -or [string]::IsNullOrWhiteSpace($instanceLookupText)) {
            Write-ErrMsg "Instance not found: $InstanceId in region $AwsRegion"
            exit 1
        }
    }

    Write-Info "Associating instance profile with EC2 instance..."
    $associationLookup = Invoke-AwsAllowError {
        aws ec2 describe-iam-instance-profile-associations `
            --region $AwsRegion `
            --filters "Name=instance-id,Values=$InstanceId" "Name=state,Values=associated" `
            --output json
    }
    if ($associationLookup.ExitCode -ne 0) {
        Write-ErrMsg "Cannot query IAM instance profile associations. Check IAM permissions for ec2:DescribeIamInstanceProfileAssociations."
        Write-ErrMsg "AWS message: $($associationLookup.Output)"
        exit 1
    }

    $associationJson = ($associationLookup.Output | Out-String).Trim()
    $associationId = "None"
    $currentProfileArn = "None"
    if (-not [string]::IsNullOrWhiteSpace($associationJson)) {
        try {
            $associationParsed = $associationJson | ConvertFrom-Json
            if ($associationParsed.IamInstanceProfileAssociations.Count -gt 0) {
                $assoc = $associationParsed.IamInstanceProfileAssociations[0]
                $associationId = [string]$assoc.AssociationId
                if ($assoc.IamInstanceProfile -and $assoc.IamInstanceProfile.Arn) {
                    $currentProfileArn = [string]$assoc.IamInstanceProfile.Arn
                }
            }
        }
        catch {
            Write-WarnMsg "Cannot parse EC2 association JSON response, continuing with fallback."
        }
    }

    if ($associationId -eq "None" -or [string]::IsNullOrWhiteSpace($associationId)) {
        $associateResult = Invoke-AwsAllowError {
            aws ec2 associate-iam-instance-profile `
                --region $AwsRegion `
                --instance-id $InstanceId `
                --iam-instance-profile "Name=$InstanceProfileName"
        }
        if ($associateResult.ExitCode -ne 0) {
            Write-ErrMsg "Failed to associate instance profile to EC2. Check permissions ec2:AssociateIamInstanceProfile and iam:PassRole."
            Write-ErrMsg "AWS message: $($associateResult.Output)"
            exit 1
        }
        Write-Info "Associated instance profile to EC2."
    }
    elseif ($currentProfileArn -like "*/$InstanceProfileName") {
        Write-WarnMsg "EC2 instance already uses instance profile: $InstanceProfileName"
    }
    else {
        $replaceResult = Invoke-AwsAllowError {
            aws ec2 replace-iam-instance-profile-association `
                --region $AwsRegion `
                --association-id $associationId `
                --iam-instance-profile "Name=$InstanceProfileName"
        }
        if ($replaceResult.ExitCode -ne 0) {
            Write-ErrMsg "Failed to replace instance profile association. Check permissions ec2:ReplaceIamInstanceProfileAssociation and iam:PassRole."
            Write-ErrMsg "AWS message: $($replaceResult.Output)"
            exit 1
        }
        Write-Info "Replaced old instance profile with: $InstanceProfileName"
    }

    if (-not $SkipMetadataOptions) {
        Write-Info "Setting IMDS options for container credential access (tokens required, hop limit 2)..."
        $metadataResult = Invoke-AwsAllowError {
            aws ec2 modify-instance-metadata-options `
                --region $AwsRegion `
                --instance-id $InstanceId `
                --http-endpoint enabled `
                --http-tokens required `
                --http-put-response-hop-limit 2
        }
        if ($metadataResult.ExitCode -ne 0) {
            Write-ErrMsg "Failed to update instance metadata options. Check permission ec2:ModifyInstanceMetadataOptions."
            Write-ErrMsg "AWS message: $($metadataResult.Output)"
            exit 1
        }
    }
    else {
        Write-WarnMsg "Skipped metadata options update."
    }
}
finally {
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
}

Write-Info "Done."
Write-Info "Next step: restart app container on EC2 so app re-initializes DynamoDB store."
Write-Host "cd ~/lottery-checker && bash deploy/ec2/update.sh"
