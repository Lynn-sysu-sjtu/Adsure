param(
    [int]$LimitRules = 0,
    [int]$LimitFiles = 0,
    [switch]$DryRun,
    [switch]$Overwrite,
    [switch]$ApplySemanticRecommendations,
    [switch]$SkipRewrite,
    [switch]$SkipVectorIndex,
    [switch]$SkipBaseline,
    [string]$BaselineName = "baseline_hyde_vector_text_zhipu_dualrisk",
    [string]$SemanticBackend = "zhipu",
    [string]$LlmBackend = "deepseek",
    [string]$LlmMode = "strict"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcDir = Join-Path $ProjectRoot "src"
$JsonbaseDir = Join-Path $ProjectRoot "jsonbase"
$VectorIndex = Join-Path $ProjectRoot "vectorbase\rule_vector_index.json"
$ReportsDir = Join-Path $ProjectRoot "test_reports"

chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "JsonbaseDir: $JsonbaseDir"

if (-not $SkipRewrite) {
    if (-not $DryRun -and -not $env:DEEPSEEK_API_KEY) {
        throw "Missing DEEPSEEK_API_KEY. Set it before running, for example: `$env:DEEPSEEK_API_KEY='sk-...'"
    }

    $rewriteArgs = @(
        (Join-Path $SrcDir "batch_rewrite_vector_text_hyde.py"),
        "--jsonbase-dir", $JsonbaseDir
    )
    if ($LimitRules -gt 0) {
        $rewriteArgs += @("--limit-rules", "$LimitRules")
    }
    if ($LimitFiles -gt 0) {
        $rewriteArgs += @("--limit-files", "$LimitFiles")
    }
    if ($DryRun) {
        $rewriteArgs += "--dry-run"
    }
    if ($Overwrite) {
        $rewriteArgs += "--overwrite"
    }
    if ($ApplySemanticRecommendations) {
        $rewriteArgs += "--apply-semantic-recommendations"
    }

    Write-Host "Step 1/3: rewrite recall.vector_text with HyDE prompt"
    py -3 @rewriteArgs
    if ($LASTEXITCODE -ne 0) { throw "Step 1 failed with exit code $LASTEXITCODE" }
}

if (-not $SkipVectorIndex) {
    if (-not $env:ZHIPUAI_API_KEY -and -not $env:ZHIPU_API_KEY) {
        throw "Missing ZHIPUAI_API_KEY or ZHIPU_API_KEY. Vector index rebuild requires Zhipu embedding API."
    }

    Write-Host "Step 2/3: rebuild vectorbase/rule_vector_index.json"
    py -3 (Join-Path $SrcDir "build_rule_vector_index.py") --base-dir $ProjectRoot --output $VectorIndex
    if ($LASTEXITCODE -ne 0) { throw "Step 2 failed with exit code $LASTEXITCODE" }
}

if (-not $SkipBaseline) {
    Write-Host "Step 3/3: run baseline"
    $env:ADSURE_SEMANTIC_BACKEND = $SemanticBackend
    $env:ADSURE_LLM_BACKEND = $LlmBackend
    $env:ADSURE_LLM_MODE = $LlmMode
    py -3 (Join-Path $SrcDir "run_engine_baseline_eval.py") --baseline-name $BaselineName --output-dir $ReportsDir
    if ($LASTEXITCODE -ne 0) { throw "Step 3 failed with exit code $LASTEXITCODE" }
}

Write-Host "Pipeline finished."

