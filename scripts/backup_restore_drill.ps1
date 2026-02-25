param(
  [string]$DbPath = "",
  [string]$BackupDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $DbPath) { $DbPath = Join-Path $root "salonos.db" }
if (-not $BackupDir) { $BackupDir = Join-Path $root "backups" }

$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$reportPath = Join-Path $logsDir "backup_restore_drill_last.json"

$report = [ordered]@{
  started_at = (Get-Date).ToString("o")
  status = "running"
  db_path = $DbPath
}

try {
  & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup_db.ps1") -DbPath $DbPath -BackupDir $BackupDir | Out-Null

  $latest = Get-ChildItem $BackupDir -Filter "salonos_*.db" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No backup file found after backup step" }

  $drillDir = Join-Path $BackupDir "drill"
  New-Item -ItemType Directory -Force -Path $drillDir | Out-Null
  $drillDb = Join-Path $drillDir ("salonos_restore_drill_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".db")
  Copy-Item $latest.FullName $drillDb -Force

  $python = Join-Path $root ".venv\Scripts\python.exe"
  if (-not (Test-Path $python)) { throw "Missing Python env: $python" }

  $probeFile = Join-Path $drillDir "probe_restore_drill.py"
  $probeCode = @'
import sqlite3
import sys

db = sys.argv[1]
conn = sqlite3.connect(db)
cur = conn.cursor()
required = ["tenants", "visits", "reservation_requests", "reservation_status_events", "visit_status_events"]
missing = []
for name in required:
    row = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    if not row:
        missing.append(name)
if missing:
    print("missing_tables=" + ",".join(missing))
    sys.exit(2)
visits = cur.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
reservations = cur.execute("SELECT COUNT(*) FROM reservation_requests").fetchone()[0]
print(f"visits={visits};reservations={reservations}")
conn.close()
'@
  Set-Content -Path $probeFile -Value $probeCode -Encoding UTF8

  $probeOut = & $python $probeFile $drillDb
  if ($LASTEXITCODE -ne 0) {
    throw "Restore drill probe failed with exit code $LASTEXITCODE"
  }
  $report.status = "ok"
  $report.finished_at = (Get-Date).ToString("o")
  $report.latest_backup_file = $latest.FullName
  $report.drill_db = $drillDb
  $report.probe = $probeOut
}
catch {
  $report.status = "failed"
  $report.finished_at = (Get-Date).ToString("o")
  $report.error = $_.Exception.Message
  throw
}
finally {
  $report | ConvertTo-Json -Depth 8 | Set-Content $reportPath
  Write-Host "Backup restore drill report: $reportPath"
}
