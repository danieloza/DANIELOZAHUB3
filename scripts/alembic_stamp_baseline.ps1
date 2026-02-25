$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing Python env: $python"
}

& $python -m alembic stamp 20260222_000001
Write-Host "Alembic baseline stamped: 20260222_000001"
