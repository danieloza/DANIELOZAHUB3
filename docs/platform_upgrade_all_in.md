# Platform Upgrade: All-In

## 1) PostgreSQL + Redis
- Local infra: `docker-compose.infra.yml`
- Postgres on `localhost:5432`, Redis on `localhost:6379`
- Suggested `.env`:
  - `DATABASE_URL=postgresql://salonos:salonos@127.0.0.1:5432/salonos`
  - `REDIS_URL=redis://127.0.0.1:6379/0`

## 2) AuthN/AuthZ (JWT + MFA)
- New auth endpoints under `/auth/*`
- Register/login/refresh + TOTP setup/verify
- Bearer token carries tenant/email/role claims
- Optional enforcement switch: `AUTH_REQUIRED=1`

## 3) Outbox + Event Bus
- Outbox table: `outbox_events`
- Dispatcher script: `scripts/outbox_dispatcher.py`
- Redis stream topic from `EVENT_BUS_STREAM`

## 4) Global Idempotency for mutations
- Middleware handles `POST/PUT/PATCH/DELETE`
- Uses `Idempotency-Key` header
- Stores/replays exact response payload by `(tenant, method, path, key)`

## 5) Payment + No-show Policy
- Policy endpoints under `/api/platform/no-show-policy`
- Payment intents under `/api/platform/payments/intents`
- Automatic no-show fee intent on status `no_show` when policy enabled

## 6) PITR + Encrypted Offsite Backup
- Backup script: `scripts/pitr_backup.py`
- Restore script: `scripts/pitr_restore.py`
- Encryption required via `BACKUP_ENCRYPTION_KEY`
- Optional S3 upload via `OFFSITE_S3_*`

## 7) Synthetic Monitoring
- Script: `scripts/synthetic_monitor.py`
- Workflow: `.github/workflows/synthetic-monitor.yml`
- Flow: create reservation -> status update -> convert -> integrity check

## 8) Feature Flags + Canary
- Endpoints under `/api/platform/flags`
- Percentage rollout + allowlist
- Canary applied to slot scoring with flag `slots_v2_scoring`
