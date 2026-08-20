param(
    [string]$OutputDir = "/workspace/docs/performance",
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$SubjectBaselineSha = "5810240e14d1d5a86562d73d6b85f2cdd2083cc4",
    [switch]$VerifySourceTreeOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$AllowedBenchmarkPaths = @(
    "backend/app/gis/risk_benchmark.py",
    "backend/tests/test_risk_benchmark.py",
    "scripts/benchmark-risk-analysis.ps1",
    "docs/performance/"
)

$SubjectBaselineSha = $SubjectBaselineSha.ToLowerInvariant()
git cat-file -e "$SubjectBaselineSha`^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Subject production baseline commit 不存在：$SubjectBaselineSha。benchmark 未运行。"
}

$RepositoryHeadSha = git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or -not $RepositoryHeadSha) {
    throw "无法读取仓库 Git HEAD，benchmark 未运行。"
}
$RepositoryHeadSha = $RepositoryHeadSha.Trim().ToLowerInvariant()

git merge-base --is-ancestor $SubjectBaselineSha $RepositoryHeadSha
if ($LASTEXITCODE -ne 0) {
    throw "Subject production baseline 不是 repository HEAD 的 ancestor：subject=$SubjectBaselineSha, head=$RepositoryHeadSha。benchmark 未运行。"
}

function Test-BenchmarkPathAllowed([string]$Path) {
    $Normalized = $Path.Replace("\", "/")
    return (
        $Normalized -eq "backend/app/gis/risk_benchmark.py" -or
        $Normalized -eq "backend/tests/test_risk_benchmark.py" -or
        $Normalized -eq "scripts/benchmark-risk-analysis.ps1" -or
        $Normalized.StartsWith("docs/performance/", [System.StringComparison]::Ordinal)
    )
}

$TrackedDifferences = @()
$ForbiddenDifferences = @()
$TrackedLines = @(git -c core.quotepath=false diff --name-status --no-renames $SubjectBaselineSha --)
if ($LASTEXITCODE -ne 0) {
    throw "无法比较 subject baseline 与当前 working tree。benchmark 未运行。"
}
foreach ($Line in $TrackedLines) {
    $Parts = $Line -split "`t", 2
    if ($Parts.Count -ne 2) {
        throw "无法解析 tracked difference：$Line。benchmark 未运行。"
    }
    $Status = $Parts[0]
    $Path = $Parts[1].Replace("\", "/")
    if (Test-BenchmarkPathAllowed $Path) {
        $TrackedDifferences += "${Status}:$Path"
    } else {
        $ForbiddenDifferences += "${Status}:$Path"
    }
}

$UntrackedPaths = @(git -c core.quotepath=false ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) {
    throw "无法读取 non-ignored untracked files。benchmark 未运行。"
}
$AllowedUntrackedPaths = @()
foreach ($PathValue in $UntrackedPaths) {
    $Path = $PathValue.Replace("\", "/")
    if (Test-BenchmarkPathAllowed $Path) {
        $AllowedUntrackedPaths += $Path
    } else {
        $ForbiddenDifferences += "?:$Path"
    }
}

if ($ForbiddenDifferences.Count -gt 0) {
    $Details = $ForbiddenDifferences -join ", "
    throw "Source tree verification 失败；非 benchmark-only 差异：$Details。benchmark 未运行。"
}

Write-Output "[OK] subject production baseline: $SubjectBaselineSha"
Write-Output "[OK] repository HEAD: $RepositoryHeadSha"
Write-Output "[OK] source tree verified; only benchmark-only paths differ from baseline."
if ($VerifySourceTreeOnly) {
    return
}

$BackendId = docker compose ps -q backend
if (-not $BackendId) {
    throw "backend 容器未运行。请先执行 docker compose up -d。"
}

$BenchmarkArguments = @(
    "compose", "exec", "-T", "backend", "python", "-m", "app.gis.risk_benchmark",
    "--raster-dir", "/data/source",
    "--output-dir", $OutputDir,
    "--subject-baseline-sha", $SubjectBaselineSha,
    "--repository-head-sha", $RepositoryHeadSha,
    "--source-tree-verification-method", "host_git_diff_and_untracked_allowlist_v1",
    "--source-tree-verified",
    "--baseline-is-ancestor"
)
foreach ($Path in $AllowedBenchmarkPaths) {
    $BenchmarkArguments += @("--allowed-benchmark-path", $Path)
}
foreach ($Difference in $TrackedDifferences) {
    $BenchmarkArguments += @("--tracked-difference", $Difference)
}
foreach ($Path in $AllowedUntrackedPaths) {
    $BenchmarkArguments += @("--untracked-path", $Path)
}

docker @BenchmarkArguments

if ($LASTEXITCODE -ne 0) {
    throw "Risk benchmark 失败，exit code: $LASTEXITCODE"
}
