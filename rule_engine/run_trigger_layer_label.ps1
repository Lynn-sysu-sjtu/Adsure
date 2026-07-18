param(
    [switch]$DryRun,
    [switch]$Overwrite,
    [switch]$UseDeepSeek,
    [int]$LimitRules = 0,
    [int]$LimitFiles = 0
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ProjectRoot "src\batch_label_trigger_layer.py"

$argsList = @($ScriptPath)
if ($DryRun) { $argsList += "--dry-run" }
if ($Overwrite) { $argsList += "--overwrite" }
if ($UseDeepSeek) { $argsList += "--use-deepseek" }
if ($LimitRules -gt 0) {
    $argsList += "--limit-rules"
    $argsList += [string]$LimitRules
}
if ($LimitFiles -gt 0) {
    $argsList += "--limit-files"
    $argsList += [string]$LimitFiles
}

Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Command: py -3 $($argsList -join ' ')"
py -3 @argsList
