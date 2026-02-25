param(
  [string]$Revision = "head"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing Python env: $python"
}

& $python -m alembic upgrade $Revision
Write-Host "Alembic upgrade completed to revision: $Revision"
