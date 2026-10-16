<#
.SYNOPSIS
    Live end-to-end verification for Task 2 (HITL write tools) of mahalo-agentcore.

.DESCRIPTION
    Brings up the SSH tunnel to the EC2 mocks (if it isn't already), verifies the
    AWS `lava` SSO session and Bedrock reachability, then runs the live
    verification steps described in docs/.agents/tasks/task2-verification.md:

      1. Full pytest suite with the live integration test ACTUALLY running
         (list my repositories -> payment-service; show my stories -> PAY-).
      2. Live HITL create-story (interactive approve/reject prompt).
      3. Live GitHub check-in chain (branch -> commit -> PR) REPL, approving each
         step to confirm the [SYSTEM] breadcrumbs stop re-proposing done steps.

    Steps 2 and 3 are INTERACTIVE by design: the agent pauses on each write and
    reads a [y/N] answer from the keyboard, so this script hands control to you
    for those — it never auto-answers (nothing is fabricated).

.PARAMETER SkipTunnel
    Don't try to open the SSH tunnel; assume it's already forwarding 5001-5004.

.PARAMETER PytestOnly
    Run only step 1 (the live pytest suite) and exit; skip the interactive writes.

.EXAMPLE
    pwsh ./scripts/verify-task2-live.ps1

.EXAMPLE
    pwsh ./scripts/verify-task2-live.ps1 -PytestOnly
#>
[CmdletBinding()]
param(
    [switch]$SkipTunnel,
    [switch]$PytestOnly
)

$ErrorActionPreference = 'Stop'

# --- Paths & constants ------------------------------------------------------
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot 'agent\.venv\Scripts\python.exe'
$SshKey     = Join-Path $env:USERPROFILE '.ssh\mahalo-dock-key.pem'
$Profile    = 'lava'
$Region     = 'us-east-1'
$JiraProbe  = 'http://localhost:5001/projects'
$JiraToken  = 'mock-jira-token-12345'
$MockPorts  = 5001, 5002, 5003, 5004

function Write-Step  ($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok    ($m) { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Warn2 ($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Fail        ($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; exit 1 }

# --- 0. Preconditions -------------------------------------------------------
Write-Step 'Preconditions'
if (-not (Test-Path $VenvPython)) { Fail "venv python not found at $VenvPython (run Task 1 setup first)" }
Write-Ok "venv python: $VenvPython"

# --- 1. AWS SSO session -----------------------------------------------------
Write-Step "AWS SSO session (profile '$Profile')"
$caller = aws sts get-caller-identity --profile $Profile --region $Region --output json 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "SSO session invalid or expired. Run:  aws sso login --profile $Profile"
    Fail 'AWS session not valid — cannot exercise the live Bedrock path.'
}
$acct = ($caller | ConvertFrom-Json).Account
Write-Ok "authenticated (account $acct)"

# --- 2. Mock tunnel (ports 5001-5004) ---------------------------------------
function Test-MocksReachable {
    try {
        $r = Invoke-WebRequest -Uri $JiraProbe -Headers @{ 'X-API-Token' = $JiraToken } `
             -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

Write-Step 'Mock tunnel (ports 5001-5004)'
$tunnelProc = $null
if (Test-MocksReachable) {
    Write-Ok 'mocks already reachable on localhost:5001-5004'
}
elseif ($SkipTunnel) {
    Fail 'mocks unreachable and -SkipTunnel was set — open the tunnel first.'
}
else {
    if (-not (Test-Path $SshKey)) { Fail "SSH key not found at $SshKey" }

    Write-Host '  mocks down — resolving EC2 public IP via AWS...' -ForegroundColor DarkGray
    $ip = aws ec2 describe-instances `
            --filters 'Name=tag:project,Values=mahalo-dock' 'Name=instance-state-name,Values=running' `
            --query 'Reservations[0].Instances[0].PublicIpAddress' `
            --output text --profile $Profile --region $Region 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ip) -or $ip -eq 'None') {
        Fail 'could not resolve a running mahalo-dock EC2 instance IP.'
    }
    Write-Ok "EC2 public IP: $ip"

    $fwd = $MockPorts | ForEach-Object { "-L ${_}:localhost:${_}" }
    $sshArgs = @('-i', $SshKey, '-N', '-o', 'StrictHostKeyChecking=accept-new',
                 '-o', 'ExitOnForwardFailure=yes') + ($fwd -split ' ') + "ubuntu@$ip"
    Write-Host "  opening SSH tunnel: ssh $($sshArgs -join ' ')" -ForegroundColor DarkGray
    $tunnelProc = Start-Process -FilePath 'ssh' -ArgumentList $sshArgs -PassThru -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-MocksReachable) { break }
    }
    if (-not (Test-MocksReachable)) {
        if ($tunnelProc -and -not $tunnelProc.HasExited) { Stop-Process -Id $tunnelProc.Id -Force }
        Fail 'tunnel opened but mocks still unreachable after 30s.'
    }
    Write-Ok "tunnel up (pid $($tunnelProc.Id)), mocks reachable"
}

try {
    # --- 3. Live pytest suite -----------------------------------------------
    Write-Step 'Step 1/3 — live pytest suite (integration test should RUN, not skip)'
    Push-Location $RepoRoot
    try {
        & $VenvPython -m pytest agent -q
        if ($LASTEXITCODE -ne 0) { Fail "pytest returned exit code $LASTEXITCODE" }
    } finally { Pop-Location }
    Write-Ok 'suite green (if the live test skipped, the tunnel/creds were not live)'

    if ($PytestOnly) {
        Write-Step 'Done (-PytestOnly)'
        return
    }

    # --- 4. Interactive HITL create-story -----------------------------------
    Write-Step 'Step 2/3 — live HITL create-story (INTERACTIVE)'
    Write-Host @'
  The agent will PROPOSE a write and pause with:  Approve this write? [y/N]
    - answer  y  -> the POST runs, expect: Story created successfully
    - answer  n  -> nothing is written (reject path)
  Run it once per path if you want to confirm both.
'@ -ForegroundColor Gray
    Push-Location $RepoRoot
    try {
        & $VenvPython -m agent.chat "create a story in PAY titled 'Add retry to payment webhook'"
    } finally { Pop-Location }

    # --- 5. Interactive GitHub chain REPL -----------------------------------
    Write-Step 'Step 3/3 — live GitHub check-in chain (INTERACTIVE REPL)'
    Write-Host @'
  A REPL opens. Drive the chain, approving (y) each step:
    1) create a feature branch in payment-service for PAY-109
    2) commit the code to that branch
    3) open a pull request from that branch into main
  Each approved step should NOT be re-proposed ([SYSTEM] breadcrumbs).
  Type 'exit' to leave the REPL.
'@ -ForegroundColor Gray
    Push-Location $RepoRoot
    try {
        & $VenvPython -m agent.chat
    } finally { Pop-Location }

    Write-Step 'Live verification finished'
    Write-Ok 'Record the outcomes in docs/.agents/tasks/task2-verification.md'
}
finally {
    if ($tunnelProc -and -not $tunnelProc.HasExited) {
        Write-Host "`nClosing SSH tunnel (pid $($tunnelProc.Id))..." -ForegroundColor DarkGray
        Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue
    }
}
