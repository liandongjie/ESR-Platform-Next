$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill in secrets and AMap credentials before deployment."
}

if (-not (Test-Path "backend/.venv")) {
    python -m venv backend/.venv
}

& "backend/.venv/Scripts/python.exe" -m pip install --upgrade pip
& "backend/.venv/Scripts/python.exe" -m pip install -e "backend[dev]"

Push-Location frontend
npm install
Pop-Location

Write-Host "Bootstrap complete."
