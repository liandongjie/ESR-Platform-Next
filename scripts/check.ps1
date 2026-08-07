$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

& "backend/.venv/Scripts/python.exe" -m ruff check backend
& "backend/.venv/Scripts/python.exe" -m pytest backend/tests

Push-Location frontend
npm run type-check
npm run lint
npm run test:run
npm run build
Pop-Location
