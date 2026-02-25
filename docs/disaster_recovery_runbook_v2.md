# Disaster Recovery Runbook v2

## Targets
- `RTO`: 60 minutes
- `RPO`: 15 minutes

## Preconditions
- Daily backup task active (`scripts/register_backup_task.ps1`)
- Verified restore script (`scripts/restore_db.ps1`)
- On-call routing active (Slack/Teams/email)

## Incident Mode Checklist
1. Declare incident and timestamp start.
2. Freeze deploys and schema changes.
3. Capture current API health (`/health`, `/ping`, `/api/ops/metrics`).
4. Identify blast radius (tenant scope, feature scope, data scope).
5. Decide failover/restore path based on RPO impact.

## Restore Drill Procedure
1. Create snapshot with `scripts/backup_db.ps1`.
2. Restore latest known-good backup into staging.
3. Run smoke:
   - `python scripts/smoke_after_deploy.py --base-url http://127.0.0.1:8000`
   - `pytest -q tests`
4. Validate integrity report:
   - `GET /api/integrity/conversions`
5. Promote restore target.

## Validation Gates
- API health endpoints return OK.
- Reservation->visit integrity issues count is 0.
- Background jobs queue does not have growing DLQ.
- Calendar sync events recover and continue.

## Communication
- T+0: incident declared
- T+15 min: impact update
- T+30 min: mitigation update
- T+60 min: recovery confirmation or revised ETA

## Recurrence
- Run full restore drill at least monthly.
- Record outcome and action items in postmortem.
