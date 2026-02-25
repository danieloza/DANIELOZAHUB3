param(
  [Parameter(Mandatory = $true)][string]$BackupFile,
  [string]$TargetDbPath = "",
  [switch]$CreatePreRestoreSnapshot
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $TargetDbPath) { $TargetDbPath = Join-Path $root "salonos.db" }

if (-not (Test-Path $BackupFile)) {
  throw "Backup file not found: $BackupFile"
}

if ($CreatePreRestoreSnapshot -and (Test-Path $TargetDbPath)) {
  $snapshotDir = Join-Path $root "backups\pre_restore"
  New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  Copy-Item $TargetDbPath (Join-Path $snapshotDir ("salonos_before_restore_" + $stamp + ".db")) -Force
}

Copy-Item $BackupFile $TargetDbPath -Force
Write-Host "Restore completed: $BackupFile -> $TargetDbPath"
