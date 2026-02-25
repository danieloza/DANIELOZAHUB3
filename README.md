# SalonOS

[![CI](https://github.com/danieloza/DANIELOZAHUB3/actions/workflows/ci.yml/badge.svg)](https://github.com/danieloza/DANIELOZAHUB3/actions/workflows/ci.yml)

## TL;DR (60s)
Start SalonOS API:
```powershell
.\start_api.ps1
```

Run quality gate:
```bash
python -m pytest -q tests
```

Local demo pair:
- SalonOS: `http://127.0.0.1:8000`
- Danex: `http://127.0.0.1:8001`

## What It Is
SalonOS is the core booking and visit management system (FastAPI + Telegram bot) with multi-tenant support.

## Scope
- visits: add/list/move/delete
- public reservations: `POST /public/{tenant_slug}/reservations`
- reservation status flow + reservation-to-visit conversion
- DB-level integrity: one reservation can create at most one visit
- daily/monthly reports
- CSV/PDF export
- multi-tenant routing via `X-Tenant-Slug`

## Architecture Role
- SalonOS core API: `http://127.0.0.1:8000`
- Danex Business API is the gateway/admin/public layer over SalonOS

## Run In 2 Minutes (API)
```bash
git clone https://github.com/danieloza/DANIELOZAHUB3.git
cd DANIELOZAHUB3
python -m pip install -r requirements.txt && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/health`

## Quick Start
```bash
git clone https://github.com/danieloza/DANIELOZAHUB3.git
cd DANIELOZAHUB3
python -m venv .venv
```

Activate virtual environment:
```bash
# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

Install dependencies and configure environment:
```bash
pip install -r requirements.txt
cp .env.example .env
```

Windows alternative for env file:
```powershell
Copy-Item .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env`.
Optional: set `ADMIN_API_KEY` to protect operational endpoints (`/api/ops/*`, `/api/integrity/*`).

## Run Modes
API:
```powershell
.\start_api.ps1
```

Bot:
```powershell
.\start_bot.ps1
```

API + Bot:
```powershell
.\start_all.ps1
```

## Local Demo Flow (No VPS)
Shared start/stop scripts for SalonOS + Danex are in Danex repo:
- `scripts/start_demo_stack.ps1`
- `scripts/stop_demo_stack.ps1`

Run automated local demo:
```powershell
.\demo_flow.ps1
```

Output report: `logs\demo_flow_last.json`

`demo_flow.ps1` validates end-to-end:
- availability (working day + employee block)
- buffers (service + employee)
- slot recommendations
- visit status transitions
- CRM endpoints (`clients/search`, `clients/{id}`, notes)
- reservations flow (create -> status -> convert)
- pulse + assistant endpoints
- conversion integrity checks

## API Surface
Visits:
- `POST /api/visits`
- `GET /api/visits?day=YYYY-MM-DD&employee_name=...`
- `PATCH /api/visits/{visit_id}`
- `DELETE /api/visits/{visit_id}`

Reservations:
- `POST /public/{tenant_slug}/reservations`
- `GET /api/reservations`
- `PATCH /api/reservations/{reservation_id}/status`
- `POST /api/reservations/{reservation_id}/convert`
- `GET /api/reservations/{reservation_id}/history`

Integrity:
- `GET /api/integrity/conversions?limit=100`

Ops (admin API key when configured):
- `GET /api/ops/metrics?window_minutes=15`
- `GET /api/ops/alerts?window_minutes=15`
- `GET /api/ops/jobs/health?stale_running_minutes=15`

Reports and export:
- `GET /api/summary/day?day=YYYY-MM-DD`
- `GET /api/report/month?year=2026&month=2`
- `GET /api/export/visits.csv?start=...&end=...`
- `GET /api/export/report.pdf?year=2026&month=2`

Swagger and health:
- `http://127.0.0.1:8000/docs`
- `GET /ping`
- `GET /health`
- `GET /health/ready`

## Quality Gates
```bash
python -m pytest -q tests
```

## Operations Scripts
- `start_api.ps1`
- `start_bot.ps1`
- `start_all.ps1`
- `demo_flow.ps1`
- `scripts/backup_db.ps1`
- `scripts/restore_db.ps1`
- `scripts/backup_restore_drill.ps1`
- `scripts/register_backup_task.ps1`
- `scripts/alembic_stamp_baseline.ps1`
- `scripts/alembic_upgrade.ps1`
- `start_salonos.bat`
- `start_danex_all.bat`

## Backups and Migrations
Backup:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup_db.ps1 -RetentionDays 14
```

Restore:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore_db.ps1 -BackupFile .\backups\salonos_YYYYMMDD_HHMMSS.db -CreatePreRestoreSnapshot
```

Restore drill:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup_restore_drill.ps1
```

Daily backup task registration:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_backup_task.ps1 -TaskName SalonOS-Backup-Daily -At 02:30
```

Alembic baseline + upgrade:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\alembic_stamp_baseline.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\alembic_upgrade.ps1 -Revision head
```

## Security and Ops Notes
- tenant routing via `X-Tenant-Slug` and `DEFAULT_TENANT_*`
- reservation conversion is protected against double execution (idempotency + unique constraint)
- public reservation anti-abuse rate limiting (IP + phone)
- auth anti-bruteforce limiter (tenant + email + IP)
- request correlation with `X-Request-ID` + JSON logs + ops metrics/alerts
- security headers enabled (`X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `Referrer-Policy`)
- optional calendar webhook HMAC validation

## Project Structure
- `app/main.py` - FastAPI entrypoint
- `app/api.py` - API/public routes
- `app/services.py` - business logic
- `app/models.py` - SQLAlchemy models
- `bot/router_bot.py` - Telegram bot routing
- `bot/visit_wizard.py` - guided visit flow
- `bot/day_view.py` - day summary view

## Enterprise Delivery Highlights
- calendar sync (Google/Outlook) + webhooks + outbox events
- background jobs with retries + dead-letter queue
- tenant policy engine (status transitions, slot buffer multiplier, SLA)
- RBAC (`owner/manager/reception`) + actor enforcement for critical ops
- full critical-action audit trail
- OpenAPI freeze + contract testing in CI
- SLO definitions + evaluation + alert routes
- GDPR operations: anonymization/delete + retention cleanup
- performance profiles (k6)
- DR runbook + release automation

## Documentation Note
Main documentation is in English for broader reach.
Operational scripts remain aligned with the local deployment workflow.

## Release and License
- Release: `v0.1.0`
- License: `MIT` (see `LICENSE`)
- Changelog: `CHANGELOG.md`
