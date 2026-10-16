#requires -Version 5.1
<#
.SYNOPSIS
    Reset the four mahalo-mock-* DynamoDB tables so they re-seed on next call.

.DESCRIPTION
    Operator maintenance script (NOT reachable by the agent). For each of the four
    exactly-named tables it deletes every item -- the collection records AND the
    `_meta` / `seeded` sentinel -- so that the next Lambda invocation lazily
    re-seeds the table from its verbatim seed_data.

    HIGH BLAST RADIUS. This script deletes DATA (items) from live tables. To keep
    the blast radius contained it:
      * targets ONLY the four hard-coded table names below -- no wildcard scans,
        no name discovery, no ListTables;
      * never calls DeleteTable / drops a table (the CDK stack owns table
        lifecycle; this only clears rows);
      * requires an explicit -Confirm:$false or an interactive confirmation.

.PARAMETER Profile
    AWS CLI/SDK named profile to use. Defaults to 'lava'.

.PARAMETER Region
    AWS region. Defaults to 'us-east-1'.

.EXAMPLE
    ./scripts/reset-mock-tables.ps1
    ./scripts/reset-mock-tables.ps1 -Profile lava -Region us-east-1
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$Profile = 'lava',
    [string]$Region = 'us-east-1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Exact, hard-coded table names. Do NOT replace with a wildcard or discovery.
$TableNames = @(
    'mahalo-mock-jira',
    'mahalo-mock-confluence',
    'mahalo-mock-github',
    'mahalo-mock-servicenow'
)

function Invoke-Aws {
    param([string[]]$AwsArgs)
    $output = & aws @AwsArgs --profile $Profile --region $Region --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "aws $($AwsArgs -join ' ') failed: $output"
    }
    return $output
}

function Clear-MockTable {
    param([Parameter(Mandatory = $true)][string]$TableName)

    Write-Host "Scanning $TableName for items to delete..."

    $scanRaw = Invoke-Aws @(
        'dynamodb', 'scan',
        '--table-name', $TableName,
        '--projection-expression', 'pk,sk'
    )
    $scan = $scanRaw | ConvertFrom-Json
    $items = @($scan.Items)

    if ($items.Count -eq 0) {
        Write-Host "  $TableName already empty; nothing to delete."
        return
    }

    Write-Host "  Deleting $($items.Count) item(s) from $TableName..."
    foreach ($item in $items) {
        $key = @{
            pk = @{ S = $item.pk.S }
            sk = @{ S = $item.sk.S }
        } | ConvertTo-Json -Compress -Depth 5

        Invoke-Aws @(
            'dynamodb', 'delete-item',
            '--table-name', $TableName,
            '--key', $key
        ) | Out-Null
    }
    Write-Host "  $TableName cleared; next call will re-seed."
}

$target = $TableNames -join ', '
if ($PSCmdlet.ShouldProcess($target, 'Delete all items (clear + force re-seed)')) {
    foreach ($name in $TableNames) {
        # Defense in depth: never act on a name outside the hard-coded allow-list.
        if ($TableNames -notcontains $name) {
            throw "Refusing to touch non-allow-listed table: $name"
        }
        Clear-MockTable -TableName $name
    }
    Write-Host 'Done. All four mahalo-mock-* tables reset.'
}
