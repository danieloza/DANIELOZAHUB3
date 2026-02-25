# Performance Targets

## Scope
- Public reservations: `POST /public/{tenant}/reservations`
- Convert flow: `POST /api/reservations/{id}/convert`

## SLO-aligned targets
- p95 latency public reservations: <= 800 ms
- p95 latency convert flow: <= 1200 ms
- error rate 5xx: < 1%
- reservation integrity mismatches: 0

## Load scenarios
- `perf/k6_public_reservations.js`
- `perf/k6_convert_flow.js`

## Suggested command
```powershell
k6 run .\perf\k6_public_reservations.js
k6 run .\perf\k6_convert_flow.js
```

## DB tuning checklist
- Ensure indexes exist for:
  - `visits(tenant_id, dt, employee_id)`
  - `reservation_requests(tenant_id, status, requested_dt)`
  - `background_jobs(queue, status, run_after)`
  - `calendar_sync_events(tenant_id, status, created_at)`
- Verify query plans for availability + convert paths after each schema change.
- Re-run load profiles after index or policy changes.
