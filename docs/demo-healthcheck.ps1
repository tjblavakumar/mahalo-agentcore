<#
.SYNOPSIS
  MAHALO demo pre-flight health check.

.DESCRIPTION
  Pings every service the live demo depends on (frontend routes, thin API,
  the multi-LLM /model-config endpoint, and real Gitea) and prints a clean
  PASS/FAIL table. Read-only: it makes GET requests only and never writes,
  deploys, or approves anything. No AWS credentials needed - everything is a
  public HTTPS endpoint.

.USAGE
  From the repo root (or anywhere):
    pwsh docs/demo-healthcheck.ps1
  or in Windows PowerShell:
    powershell -File docs/demo-healthcheck.ps1

  Optionally warm up the agent too (sends ONE harmless read-only chat prompt
  as the dev persona so the first real demo call isn't a cold start):
    pwsh docs/demo-healthcheck.ps1 -WarmUp

.NOTES
  If anything shows FAIL:
   - Frontend FAIL  -> CloudFront/S3 issue; re-check after a minute.
   - API FAIL       -> thin API Lambda; a cold call can be slow, retry once.
   - Gitea FAIL     -> the Gitea EC2 may be auto-stopped (weekends). Start it:
                       aws ec2 start-instances --instance-ids i-06d65fadd3fbd211b --profile lava --region us-east-1
                       wait ~20s, then re-run this script.
#>

[CmdletBinding()]
param(
    [switch]$WarmUp
)

$ErrorActionPreference = "Stop"

# --- Endpoints (public HTTPS; no secrets) ---------------------------------
$FrontendBase = "https://dw28e5je2s7b9.cloudfront.net"
$ApiBase      = "https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws"
$GiteaVersion = "https://d3ec76atxiij9a.cloudfront.net/api/v1/version"

$results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $results.Add([pscustomobject]@{
        Check  = $Name
        Status = if ($Ok) { "PASS" } else { "FAIL" }
        Detail = $Detail
    })
}

function Test-Url {
    param([string]$Name, [string]$Url, [hashtable]$Headers = @{}, [int]$TimeoutSec = 25)
    try {
        $r = Invoke-WebRequest -Uri $Url -Headers $Headers -TimeoutSec $TimeoutSec -UseBasicParsing
        $ok = ($r.StatusCode -eq 200)
        Add-Result $Name $ok ("HTTP {0}" -f $r.StatusCode)
        return $r
    }
    catch {
        Add-Result $Name $false $_.Exception.Message
        return $null
    }
}

Write-Host ""
Write-Host "MAHALO demo health check - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host ("-" * 60)

# --- Frontend routes (each must resolve on a cold/deep load) --------------
Test-Url "Frontend /"          "$FrontendBase/"          | Out-Null
Test-Url "Frontend /chat"      "$FrontendBase/chat"      | Out-Null
Test-Url "Frontend /dashboard" "$FrontendBase/dashboard" | Out-Null
Test-Url "Frontend /jira"      "$FrontendBase/jira"      | Out-Null
Test-Url "Frontend /settings"  "$FrontendBase/settings"  | Out-Null
Test-Url "Frontend /connections" "$FrontendBase/connections" | Out-Null

# --- Thin API: multi-LLM model config (the new slice) ---
$mc = Test-Url "API /model-config (dev)" "$ApiBase/model-config" @{ "X-Mahalo-Persona" = "dev" }
if ($mc) {
    try {
        $cfg = $mc.Content | ConvertFrom-Json
        $gen = $cfg.codeGeneration
        $rev = $cfg.codeReview
        $okModels = [bool]$gen -and [bool]$rev
        Add-Result "Model config values" $okModels ("codeGen=$gen; codeReview=$rev")
    }
    catch {
        Add-Result "Model config values" $false "could not parse JSON body"
    }
}

# --- Gitea (real git, the write path) ---
$g = Test-Url "Gitea API version" $GiteaVersion
if ($g) {
    Add-Result "Gitea reachable" $true $g.Content.Trim()
}

# --- Optional: warm up the agent (one read-only chat call) ---
if ($WarmUp) {
    Write-Host ""
    Write-Host "Warming up the agent - one read-only chat call as dev. First call can take 40-60s..." -ForegroundColor Yellow
    try {
        $body = @{ message = "What am I working on right now?"; session_id = "healthcheck-warmup-session-0001"; project_id = $null } | ConvertTo-Json
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $warmHeaders = @{ "X-Mahalo-Persona" = "dev" }
        $resp = Invoke-WebRequest -Uri "$ApiBase/chat" -Method Post -Body $body -ContentType "application/json" -Headers $warmHeaders -TimeoutSec 120 -UseBasicParsing
        $sw.Stop()
        $ok = ($resp.StatusCode -eq 200)
        Add-Result "Agent warm-up (/chat)" $ok ("HTTP {0} in {1:n1}s" -f $resp.StatusCode, $sw.Elapsed.TotalSeconds)
    }
    catch {
        Add-Result "Agent warm-up (/chat)" $false $_.Exception.Message
    }
}

# --- Report ---------------------------------------------------------------
Write-Host ""
$results | Format-Table -AutoSize | Out-String | Write-Host

$failCount = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
Write-Host ("-" * 60)
if ($failCount -eq 0) {
    Write-Host "ALL CHECKS PASSED - demo environment looks healthy." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "$failCount CHECK(S) FAILED - see the Detail column and the NOTES in this script header." -ForegroundColor Red
    exit 1
}
