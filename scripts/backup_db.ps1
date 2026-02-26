# Senior IT Database Backup Script
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DB_PATH = Join-Path $ProjectRoot "salonos.db"
$BACKUP_DIR = Join-Path $ProjectRoot "backups"
$STAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_FILE = Join-Path $BACKUP_DIR "salonos_db_$STAMP.bak"

Write-Host "--- Starting Automated Backup ---" -ForegroundColor Cyan

if (-not (Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null
}

if (Test-Path $DB_PATH) {
    Copy-Item -Path $DB_PATH -Destination $BACKUP_FILE
    Write-Host "Backup saved to: $BACKUP_FILE" -ForegroundColor Green

    # Cleanup: Keep only last 7 days
    Get-ChildItem -Path $BACKUP_DIR -Filter "*.bak" |
        Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-7) } |
        Remove-Item
    Write-Host "Old backups cleaned up." -ForegroundColor Gray
} else {
    Write-Host "ERROR: Database file not found at $DB_PATH" -ForegroundColor Red
}
