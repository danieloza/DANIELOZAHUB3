# Alembic

This repository keeps runtime-compatible schema bootstrapping in `app/db.py` and
versioned migrations in Alembic for controlled future changes.

Initial setup on an existing database:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\alembic_stamp_baseline.ps1
```

Upgrade to latest revision:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\alembic_upgrade.ps1 -Revision head
```
