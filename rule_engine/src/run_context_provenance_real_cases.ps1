$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw "DEEPSEEK_API_KEY is not configured in this PowerShell session."
}
if (
    [string]::IsNullOrWhiteSpace($env:ZHIPU_API_KEY) -and
    [string]::IsNullOrWhiteSpace($env:ZHIPUAI_API_KEY)
) {
    throw "ZHIPU_API_KEY or ZHIPUAI_API_KEY is not configured in this PowerShell session."
}

$env:ADSURE_LLM_BACKEND = "deepseek"
$env:ADSURE_LLM_MODE = "strict"
$env:ADSURE_SEMANTIC_BACKEND = "zhipu"
$env:ADSURE_SEMANTIC_THRESHOLD = "0.50"
$env:ADSURE_FALLBACK_SEMANTIC_THRESHOLD = "0.55"
$env:ZHIPU_EMBEDDING_MODEL = "embedding-3"
$env:ADSURE_CATALOG_RECALL_ENABLED = "true"
$env:ADSURE_CATALOG_LLM_BACKEND = "deepseek"
$env:ADSURE_CATALOG_RECALL_LIMIT = "1"
$env:ADSURE_CATALOG_LLM_TIMEOUT = "4"

py -3 .\run_context_provenance_real_cases.py
if ($LASTEXITCODE -ne 0) {
    throw "Context provenance real-case verification failed with exit code $LASTEXITCODE."
}
