#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only AgentCore capability check for mahalo-agentcore.
.DESCRIPTION
    Verifies AWS session, AgentCore control-plane APIs, the Bedrock inference profile
    status, and the presence of required CLIs on PATH. Creates NO AWS resources.
    Every check is tolerant: on failure it prints [FAIL] with the message and continues.
.PARAMETER Profile
    AWS profile to use. Default: lava
.PARAMETER Region
    AWS region to use. Default: us-east-1
#>
param(
    [string]$Profile = "lava",
    [string]$Region  = "us-east-1"
)

$ErrorActionPreference = "Continue"

$ModelId = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
$Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail
    )
    $Results.Add([pscustomobject]@{
        Check  = $Name
        Status = $(if ($Ok) { "PASS" } else { "FAIL" })
        Ok     = $Ok
        Detail = $Detail
    })
}

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    try {
        $detail = & $Action
        Add-Result -Name $Name -Ok $true -Detail ([string]$detail)
    }
    catch {
        Add-Result -Name $Name -Ok $false -Detail $_.Exception.Message
    }
}

function Invoke-Aws {
    param([string[]]$CliArgs)
    $output = & aws @CliArgs --profile $Profile --region $Region --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ([string]::Join(" ", $output))
    }
    return $output
}

Write-Host ""
Write-Host "AgentCore capability check (read-only)"
Write-Host ("Profile: {0}   Region: {1}" -f $Profile, $Region)
Write-Host ""

# --- PATH tooling checks ---
foreach ($tool in @("aws", "python", "node", "cdk")) {
    Invoke-Check -Name ("PATH: {0}" -f $tool) -Action {
        $cmd = Get-Command $tool -ErrorAction Stop
        return $cmd.Source
    }
}

# --- AWS session ---
Invoke-Check -Name "AWS session (sts get-caller-identity)" -Action {
    $json = Invoke-Aws -CliArgs @("sts", "get-caller-identity")
    $id = $json | ConvertFrom-Json
    return ("account {0}" -f $id.Account)
}

# --- AgentCore control-plane APIs ---
$agentCoreOps = @(
    "list-agent-runtimes",
    "list-gateways",
    "list-memories",
    "list-workload-identities",
    "list-api-key-credential-providers"
)
foreach ($op in $agentCoreOps) {
    Invoke-Check -Name ("AgentCore control-plane: {0}" -f $op) -Action {
        $null = Invoke-Aws -CliArgs @("bedrock-agentcore-control", $op)
        return "ok"
    }
}

# --- Bedrock inference profile status ---
Invoke-Check -Name ("Bedrock inference profile: {0}" -f $ModelId) -Action {
    $json = Invoke-Aws -CliArgs @("bedrock", "get-inference-profile", "--inference-profile-identifier", $ModelId)
    $profileInfo = $json | ConvertFrom-Json
    $status = $profileInfo.status
    if ([string]::IsNullOrEmpty($status)) { $status = "UNKNOWN" }
    if ($status -ne "ACTIVE") {
        throw ("status is {0}" -f $status)
    }
    return ("status {0}" -f $status)
}

# --- Print table ---
Write-Host ""
foreach ($r in $Results) {
    if ($r.Ok) {
        Write-Host ("[PASS] " + $r.Check) -ForegroundColor Green
    }
    else {
        Write-Host ("[FAIL] " + $r.Check + " -> " + $r.Detail) -ForegroundColor Red
    }
}

$failCount = ($Results | Where-Object { -not $_.Ok }).Count
$total     = $Results.Count

Write-Host ""
if ($failCount -eq 0) {
    Write-Host ("GO: all {0} checks passed." -f $total) -ForegroundColor Green
    exit 0
}
else {
    Write-Host ("NO-GO: {0} of {1} checks failed." -f $failCount, $total) -ForegroundColor Red
    Write-Host "If AWS checks failed due to an expired session, run: aws sso login --profile $Profile" -ForegroundColor Yellow
    exit 1
}
