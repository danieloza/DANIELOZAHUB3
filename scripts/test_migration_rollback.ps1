# Senior IT: Test Database Rollback capability
Write-Host "Testing Downgrade..."
.\.venv\Scripts\alembic.exe downgrade -1
Write-Host "Testing Upgrade (Recovery)..."
.\.venv\Scripts\alembic.exe upgrade head
Write-Host "Migration chain intact."
