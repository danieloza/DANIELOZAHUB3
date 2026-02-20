# SalonOS

[![CI](https://github.com/danieloza/DANIELOZAHUB3/actions/workflows/ci.yml/badge.svg)](https://github.com/danieloza/DANIELOZAHUB3/actions/workflows/ci.yml)

## Hiring Snapshot
- Built a multi-tenant booking API with status workflows and conversion from reservation to visit.
- Implemented export/report endpoints plus bot-assisted operations for day-to-day scheduling.
- Added automated tests to keep API behavior stable while iterating quickly.
## TL;DR (60s)
Uruchom API SalonOS:
```powershell
.\start_api.ps1
```

Uruchom quality gate:
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

Lokalny duet demo:
- SalonOS: `http://127.0.0.1:8000`
- Danex: `http://127.0.0.1:8001`

## What It Is
SalonOS to `core` system rezerwacji i wizyt (API + bot Telegram).

## Scope
- Wizyty: add/list/move/delete
- Public reservations: `POST /public/{tenant_slug}/reservations`
- Status flow rezerwacji + konwersja do wizyty
- Raporty dzienne/miesieczne
- Eksport CSV/PDF
- Multi-tenant przez `X-Tenant-Slug`

## Architecture Role
- SalonOS core API: `http://127.0.0.1:8000`
- Danex Business API dzia³a jako gateway/admin/public nad SalonOS

## Quick Start
```powershell
cd C:\Users\syfsy\projekty\salonos
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Uzupelnij `TELEGRAM_BOT_TOKEN` w `.env`.

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

## Demo Flow (No VPS)
Lokalny duet:
- SalonOS: `http://127.0.0.1:8000`
- Danex: `http://127.0.0.1:8001`

Wspolny start/stop jest obslugiwany z repo Danex przez:
- `scripts/start_demo_stack.ps1`
- `scripts/stop_demo_stack.ps1`

## API Surface
Wizyty:
- `POST /api/visits`
- `GET /api/visits?day=YYYY-MM-DD&employee_name=...`
- `PATCH /api/visits/{visit_id}`
- `DELETE /api/visits/{visit_id}`

Rezerwacje:
- `POST /public/{tenant_slug}/reservations`
- `GET /api/reservations`
- `PATCH /api/reservations/{reservation_id}/status`
- `POST /api/reservations/{reservation_id}/convert`
- `GET /api/reservations/{reservation_id}/history`

Raporty i eksport:
- `GET /api/summary/day?day=YYYY-MM-DD`
- `GET /api/report/month?year=2026&month=2`
- `GET /api/export/visits.csv?start=...&end=...`
- `GET /api/export/report.pdf?year=2026&month=2`

Swagger i health:
- `http://127.0.0.1:8000/docs`
- `GET http://127.0.0.1:8000/ping`

## Quality Gates
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

## Operations Scripts
- `start_api.ps1`
- `start_bot.ps1`
- `start_all.ps1`
- `start_salonos.bat`
- `start_danex_all.bat`

## Security and Ops Notes
- Tenant routing przez `X-Tenant-Slug` i `DEFAULT_TENANT_*`.
- Public reservation endpoint jest konsumowany przez Danex gateway.
- Warto regularnie robic backup `salonos.db` (wspierane przez skrypty Danex).

## Project Structure
- `app/main.py` - entrypoint FastAPI
- `app/api.py` - routing API/public
- `app/services.py` - logika biznesowa
- `app/models.py` - modele SQLAlchemy
- `bot/router_bot.py` - routing bota
- `bot/visit_wizard.py` - flow dodawania wizyt
- `bot/day_view.py` - widok dnia i akcje

## Documentation
- `README.md` (ten plik)
- `tests/` (przyklady integracyjne API)
- Portfolio one-pager (in Danex repo): `..\danex-business-api\PORTFOLIO.md`



