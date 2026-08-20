param(
    [string]$BackendImage = "esr-platform-backend:release-gate",
    [ValidateRange(1024, 65535)]
    [int]$HttpPort = 15080
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "compose.release-gate.yml"
$ProjectName = "esr-release-gate-$PID"
$env:ESR_RELEASE_GATE_BACKEND_IMAGE = $BackendImage
$env:ESR_RELEASE_GATE_HTTP_PORT = $HttpPort
$ComposeArgs = @("compose", "--project-name", $ProjectName, "-f", $ComposeFile)

function Assert-LastExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action 失败，exit code: $LASTEXITCODE"
    }
}

function Get-DatabaseRevision {
    $revision = docker @ComposeArgs exec -T db `
        psql -U esr -d esr_release_gate -tAc `
        "SELECT version_num FROM alembic_version;"
    Assert-LastExitCode "读取 Alembic revision"
    return ($revision | Out-String).Trim()
}

try {
    docker @ComposeArgs config --quiet
    Assert-LastExitCode "校验 release gate Compose"

    docker @ComposeArgs up -d --wait db redis
    Assert-LastExitCode "启动隔离 PostgreSQL/Redis"

    docker @ComposeArgs run --rm --no-deps source-init
    Assert-LastExitCode "准备只读 smoke 栅格目录"

    docker @ComposeArgs run --rm --no-deps backend `
        flask --app wsgi:app db upgrade
    Assert-LastExitCode "Alembic upgrade"
    $HeadBefore = Get-DatabaseRevision
    if (-not $HeadBefore) {
        throw "Alembic upgrade 后未记录 revision"
    }

    $PostgisVersion = docker @ComposeArgs exec -T db `
        psql -U esr -d esr_release_gate -tAc `
        "SELECT extversion FROM pg_extension WHERE extname = 'postgis';"
    Assert-LastExitCode "校验 PostGIS extension"
    if (-not ($PostgisVersion | Out-String).Trim()) {
        throw "PostGIS extension 未安装"
    }

    docker @ComposeArgs run --rm --no-deps backend `
        flask --app wsgi:app db downgrade -- -1
    Assert-LastExitCode "Alembic downgrade -1"
    $DowngradedRevision = Get-DatabaseRevision
    if (-not $DowngradedRevision -or $DowngradedRevision -eq $HeadBefore) {
        throw "Alembic downgrade 未移动 revision"
    }

    docker @ComposeArgs run --rm --no-deps backend `
        flask --app wsgi:app db upgrade
    Assert-LastExitCode "Alembic re-upgrade"
    $HeadAfter = Get-DatabaseRevision
    if ($HeadAfter -ne $HeadBefore) {
        throw "Alembic re-upgrade 未恢复 head：before=$HeadBefore after=$HeadAfter"
    }

    docker @ComposeArgs up -d --wait backend
    Assert-LastExitCode "启动 production backend smoke"
    $Ready = Invoke-RestMethod "http://127.0.0.1:$HttpPort/api/v1/health/ready"
    if ($Ready.status -ne "ready" -or $Ready.checks.database.status -ne "ok") {
        throw "Production readiness smoke 未通过"
    }

    Write-Output "[OK] isolated project: $ProjectName"
    Write-Output "[OK] PostGIS: $(($PostgisVersion | Out-String).Trim())"
    Write-Output "[OK] Alembic upgrade -> downgrade -> upgrade: $HeadBefore"
    Write-Output "[OK] production readiness smoke"
}
finally {
    docker @ComposeArgs down --volumes --remove-orphans
}
