param(
    [ValidateSet("quick", "full")]
    [string]$Mode = "quick"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "[Phase 1A] Raster audit mode: $Mode"
Write-Host "[Phase 1A] Source raster directory is mounted read-only as /data/source."

$backendId = docker compose ps -q backend
if (-not $backendId) {
    throw "backend 容器未运行。请先执行 docker compose up -d。"
}

# -T avoids allocating an interactive TTY and makes this script CI/log friendly.
docker compose exec -T backend python -m app.gis.audit_cli `
    --raster-dir /data/source `
    --output-dir /workspace/docs/data `
    --mode $Mode

if ($LASTEXITCODE -ne 0) {
    throw "栅格审计失败，exit code: $LASTEXITCODE"
}

Write-Host ""
Write-Host "审计完成："
Write-Host "  docs/data/raster-manifest.json"
Write-Host "  docs/data/raster-audit.md"
Write-Host ""
Write-Host "先阅读 raster-audit.md 的『为什么会得到这些结论』，再决定是否运行 full 模式。"
