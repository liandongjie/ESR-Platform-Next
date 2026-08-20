param(
    [ValidateRange(5, 1000)]
    [int]$Iterations = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Benchmark = Join-Path $Root "backend\app\gis\risk_preview_benchmark.py"
Push-Location $Root
try {
    python $Benchmark `
        --baseline "docs\performance\risk-analysis-baseline.json" `
        --output-dir "docs\performance\risk-preview" `
        --iterations $Iterations
    if ($LASTEXITCODE -ne 0) {
        throw "Risk preview benchmark 失败，exit code: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
