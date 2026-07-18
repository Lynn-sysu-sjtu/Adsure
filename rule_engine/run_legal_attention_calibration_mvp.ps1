param(
    [string]$BaselineReport = "",
    [switch]$LatestBaseline,
    [switch]$IncludeLowPriority
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcDir = Join-Path $ProjectRoot "src"

chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$argsList = @(
    (Join-Path $SrcDir "legal_attention_calibration.py"),
    "--base-dir", $ProjectRoot
)

if ($BaselineReport) {
    $argsList += @("--baseline-report", $BaselineReport)
} elseif ($LatestBaseline) {
    $argsList += "--latest-baseline"
}

if ($IncludeLowPriority) {
    $argsList += "--include-low-priority"
}

Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Command: py -3 $($argsList -join ' ')"
py -3 @argsList
if ($LASTEXITCODE -ne 0) { throw "legal_attention_calibration.py failed with exit code $LASTEXITCODE" }