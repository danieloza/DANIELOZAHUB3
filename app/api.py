import hmac
from datetime import date, datetime, time, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .csv_export import export_visits_csv
from .db import get_db
from .enterprise import (
    anonymize_client_data,
    build_background_job_alerts,
    cancel_queued_background_job,
    cleanup_background_jobs,
    dispatch_alerts_to_routes,
    enqueue_background_job,
    enqueue_calendar_sync_event,
    evaluate_slos,
    get_background_jobs_health,
    get_or_create_retention_policy,
    get_tenant_policy,
    ingest_calendar_webhook,
    list_alert_routes,
    list_audit_logs,
    list_background_jobs,
    list_calendar_connections,
    list_calendar_sync_events,
    list_slo_definitions,
    list_tenant_user_roles,
    preview_retention_cleanup,
    replay_calendar_sync_event,
    require_actor,
    retry_dead_letter_job,
    run_retention_cleanup,
    upsert_alert_route,
    upsert_calendar_connection,
    upsert_retention_policy,
    upsert_slo_definition,
    upsert_tenant_policy,
    upsert_tenant_user_role,
    write_audit_log,
)
from .models import Tenant, Visit, EmployeePortfolioImage, Employee
from .observability import get_ops_alerts, get_ops_metrics_snapshot
from .pdf_export import build_month_report_pdf
from .platform import (
    create_payment_intent,
    enqueue_outbox_event,
    get_or_create_no_show_policy,
    get_outbox_health,
    is_feature_enabled,
)
from .schemas import (
    AlertDispatchOut,
    AlertRouteOut,
    AlertRouteSet,
    AuditLogOut,
    BackgroundJobCleanupOut,
    BackgroundJobCreate,
    BackgroundJobOut,
    BackgroundJobsHealthOut,
    BufferOut,
    BufferSet,
    CalendarConnectionOut,
    CalendarConnectionSet,
    CalendarSyncEventOut,
    ClientDetailOut,
    ClientNoteCreate,
    ClientNoteOut,
    ClientSearchOut,
    ClientVisitHistoryOut,
    ConversionIntegrityReportOut,
    DataRetentionCleanupOut,
    DataRetentionCleanupPreviewOut,
    DataRetentionPolicyOut,
    DataRetentionPolicySet,
    DayPulseOut,
    DaySummary,
    EmployeeAvailabilityOut,
    EmployeeAvailabilitySet,
    EmployeeBlockCreate,
    EmployeeBlockOut,
    EmployeeWeeklyScheduleDayOut,
    EmployeeWeeklyScheduleSet,
    MonthReport,
    OpsAlertOut,
    OpsMetricsOut,
    OpsStatusOut,
    PortfolioImageCreate,
    PortfolioImageOut,
    PublicReservationCreate,
    PublicReservationOut,
    ReservationAssistantActionOut,
    ReservationConvertCreate,
    ReservationMetricsOut,
    ReservationStatusEventOut,
    ReservationStatusUpdate,
    SloDefinitionOut,
    SloDefinitionSet,
    SloEvaluationOut,
    SlotRecommendationOut,
    TeamEmployeeCreate,
    TeamEmployeeOut,
    TeamEmployeeUpdate,
    TenantPolicyOut,
    TenantPolicySet,
    TenantUserRoleOut,
    TenantUserRoleSet,
    VisitCreate,
    VisitOut,
    VisitStatusEventOut,
    VisitStatusUpdate,
    VisitUpdate,
)
from .services import (
    add_client_note,
    apply_employee_weekly_schedule_to_range,
    archive_team_employee,
    convert_reservation_to_visit,
    create_employee_block,
    create_employee_leave_request,
    create_public_reservation,
    create_shift_swap_request,
    create_team_employee,
    create_time_clock_entry,
    create_visit,
    day_summary,
    decide_employee_leave_request,
    decide_shift_swap_request,
    delete_visit,
    enforce_public_reservation_rate_limit,
    get_client_detail,
    get_conversion_integrity_report,
    get_day_pulse,
    get_employee_buffer,
    get_employee_by_id,
    get_or_create_tenant,
    get_reservation_assistant_actions,
    get_reservation_by_id,
    get_reservation_metrics,
    get_service_buffer,
    list_employee_availability,
    list_employee_blocks,
    list_employee_leave_requests,
    list_employee_service_capabilities,
    list_employee_weekly_schedule,
    list_public_reservations,
    list_reservation_status_events,
    list_schedule_audit_events,
    list_schedule_notifications,
    list_shift_swap_requests,
    list_team_employees,
    list_time_clock_day_report,
    list_visit_status_events,
    month_report,
    reassign_visit_employee,
    recommend_slots,
    search_clients,
    set_employee_weekly_schedule,
    set_schedule_notification_status,
    update_reservation_status,
    update_team_employee,
    update_visit,
    update_visit_status,
    upsert_employee_availability_day,
    upsert_employee_buffer,
    upsert_employee_service_capability,
    upsert_service_buffer,
)
from .team_schemas import (
    ScheduleAuditOut,
    ScheduleNotificationOut,
    ScheduleNotificationSetStatus,
    TeamEmployeeCapabilityOut,
    TeamEmployeeCapabilitySet,
    TeamLeaveCreate,
    TeamLeaveDecision,
    TeamLeaveOut,
    TeamSwapCreate,
    TeamSwapDecision,
    TeamSwapOut,
    TeamTimeClockDayRowOut,
    TeamTimeClockIn,
    TeamTimeClockOut,
    TeamVisitReassignIn,
    TeamWeeklyApplyRangeIn,
)

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/public")


def _to_visit_out(v: Visit) -> VisitOut:
    client_name = v.client.name
    employee_name = v.employee.name
    service_name = v.service.name
    return VisitOut(
        id=v.id,
        dt=v.dt,
        client=client_name,
        employee=employee_name,
        service=service_name,
        price=float(v.price),
        source_reservation_id=v.source_reservation_id,
        client_name=client_name,
        employee_name=employee_name,
        service_name=service_name,
        duration_min=int(v.duration_min or 30),
        status=(v.status or "planned"),
        client_phone=v.client.phone,
    )


def _to_reservation_out(tenant_slug: str, reservation) -> PublicReservationOut:
    return PublicReservationOut(
        id=reservation.id,
        tenant_slug=tenant_slug,
        status=reservation.status,
        requested_dt=reservation.requested_dt,
        client_name=reservation.client_name,
        service_name=reservation.service_name,
        phone=reservation.phone,
        note=reservation.note,
        created_at=reservation.created_at,
        converted_visit_id=reservation.converted_visit_id,
        converted_at=reservation.converted_at,
    )


def _to_team_employee_out(row) -> TeamEmployeeOut:
    return TeamEmployeeOut(
        id=row.id,
        name=row.name,
        commission_pct=float(row.commission_pct or 0),
        is_active=bool(row.is_active),
        is_portfolio_public=bool(row.is_portfolio_public),
        portfolio=[
            PortfolioImageOut(
                id=img.id,
                image_url=img.image_url,
                description=img.description,
                order_weight=img.order_weight,
                created_at=img.created_at
            ) for img in sorted(row.portfolio, key=lambda x: x.order_weight)
        ] if hasattr(row, "portfolio") and row.portfolio else []
    )


def _to_team_capability_out(row, employee_name: str) -> TeamEmployeeCapabilityOut:
    return TeamEmployeeCapabilityOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=employee_name,
        service_name=row.service_name,
        duration_min=(int(row.duration_min) if row.duration_min is not None else None),
        price_override=(
            float(row.price_override) if row.price_override is not None else None
        ),
        is_active=bool(row.is_active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_team_leave_out(row, employee_name: str) -> TeamLeaveOut:
    return TeamLeaveOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=employee_name,
        start_day=row.start_day,
        end_day=row.end_day,
        status=row.status,
        reason=row.reason,
        requested_by=row.requested_by,
        decided_by=row.decided_by,
        decision_note=row.decision_note,
        decided_at=row.decided_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_team_swap_out(
    row, from_employee_name: str, to_employee_name: str
) -> TeamSwapOut:
    return TeamSwapOut(
        id=row.id,
        shift_day=row.shift_day,
        from_employee_id=row.from_employee_id,
        from_employee_name=from_employee_name,
        to_employee_id=row.to_employee_id,
        to_employee_name=to_employee_name,
        from_start_hour=int(row.from_start_hour),
        from_end_hour=int(row.from_end_hour),
        to_start_hour=int(row.to_start_hour),
        to_end_hour=int(row.to_end_hour),
        status=row.status,
        reason=row.reason,
        requested_by=row.requested_by,
        decided_by=row.decided_by,
        decision_note=row.decision_note,
        decided_at=row.decided_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _employee_name(db: Session, tenant_id: int, employee_id: int) -> str:
    row = get_employee_by_id(db, tenant_id, employee_id)
    if row is None:
        return f"employee:{employee_id}"
    return row.name


def _resolve_tenant_or_default(db: Session, tenant_slug: str | None) -> Tenant:
    slug = (tenant_slug or settings.DEFAULT_TENANT_SLUG).strip().lower()
    tenant_name = (
        settings.DEFAULT_TENANT_NAME if slug == settings.DEFAULT_TENANT_SLUG else slug
    )
    return get_or_create_tenant(db, slug=slug, name=tenant_name)


def get_current_tenant(
    db: Session = Depends(get_db),
    x_tenant_slug: str | None = Header(default=None),
) -> Tenant:
    return _resolve_tenant_or_default(db, x_tenant_slug)


def require_admin_api_key(x_admin_api_key: str | None = Header(default=None)) -> None:
    expected = (settings.ADMIN_API_KEY or "").strip()
    if not expected:
        return
    incoming = (x_admin_api_key or "").strip()
    if not hmac.compare_digest(expected, incoming):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin API key"
        )


def _mask_secret(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def _client_ip_from_request(request: Request | None) -> str:
    if request is None:
        return "unknown"
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return "unknown"


def _require_actor_for_roles(
    db: Session,
    tenant: Tenant,
    actor_email: str | None,
    actor_role: str | None,
    allowed_roles: set[str],
) -> tuple[str, str]:
    try:
        return require_actor(
            db=db,
            tenant_id=tenant.id,
            actor_email=actor_email,
            actor_role_hint=actor_role,
            allowed_roles=allowed_roles,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _audit_critical_action(
    db: Session,
    tenant_id: int,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    request: Request = None,
    payload: dict | None = None,
) -> None:
    write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_email=actor_email,
        actor_role=actor_role,
        request_id=(request.headers.get("x-request-id") if request else None),
        payload=payload or {},
    )


@router.post("/visits", response_model=VisitOut)
def add_visit(
    payload: VisitCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        v = create_visit(
            db=db,
            tenant_id=tenant.id,
            dt=payload.dt,
            client_name=payload.client_name,
            client_phone=payload.client_phone,
            employee_name=payload.employee_name,
            service_name=payload.service_name,
            price=payload.price,
            duration_min=payload.duration_min,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if x_actor_email:
        _audit_critical_action(
            db=db,
            tenant_id=tenant.id,
            action="visit.create",
            resource_type="visit",
            resource_id=v.id,
            actor_email=x_actor_email,
            actor_role=x_actor_role,
            request=request,
            payload={
                "dt": payload.dt.isoformat(),
                "employee_name": payload.employee_name,
                "service_name": payload.service_name,
            },
        )
    for conn in list_calendar_connections(db=db, tenant_id=tenant.id):
        if not conn.enabled:
            continue
        enqueue_calendar_sync_event(
            db=db,
            tenant_id=tenant.id,
            provider=conn.provider,
            action="visit_created",
            visit_id=v.id,
            payload={
                "visit_id": v.id,
                "dt": v.dt.isoformat(),
                "employee_name": v.employee.name,
                "service_name": v.service.name,
                "client_name": v.client.name,
            },
        )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="visit.created",
        key=f"visit:{v.id}",
        payload={
            "visit_id": v.id,
            "tenant_slug": tenant.slug,
            "status": v.status,
            "dt": v.dt.isoformat(),
            "employee_name": v.employee.name,
        },
    )
    return _to_visit_out(v)


@router.get("/visits", response_model=list[VisitOut])
def list_visits(
    day: date = Query(...),
    employee_name: str | None = Query(None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)

    q = db.query(Visit).filter(
        Visit.tenant_id == tenant.id, Visit.dt >= start, Visit.dt < end
    )
    if employee_name:
        q = q.join(Visit.employee).filter_by(name=employee_name, tenant_id=tenant.id)

    visits = q.order_by(Visit.dt.asc()).all()
    return [_to_visit_out(v) for v in visits]


@router.patch("/visits/{visit_id}", response_model=VisitOut)
def patch_visit(
    visit_id: int,
    payload: VisitUpdate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    if payload.dt is None and payload.duration_min is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
        )
    try:
        visit = update_visit(
            db=db,
            tenant_id=tenant.id,
            visit_id=visit_id,
            dt=payload.dt,
            duration_min=payload.duration_min,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found"
        )
    if x_actor_email:
        _audit_critical_action(
            db=db,
            tenant_id=tenant.id,
            action="visit.update",
            resource_type="visit",
            resource_id=visit.id,
            actor_email=x_actor_email,
            actor_role=x_actor_role,
            request=request,
            payload={
                "dt": visit.dt.isoformat(),
                "duration_min": int(visit.duration_min or 30),
            },
        )
    for conn in list_calendar_connections(db=db, tenant_id=tenant.id):
        if not conn.enabled:
            continue
        enqueue_calendar_sync_event(
            db=db,
            tenant_id=tenant.id,
            provider=conn.provider,
            action="visit_updated",
            visit_id=visit.id,
            payload={
                "visit_id": visit.id,
                "dt": visit.dt.isoformat(),
                "duration_min": int(visit.duration_min or 30),
            },
        )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="visit.updated",
        key=f"visit:{visit.id}",
        payload={
            "visit_id": visit.id,
            "tenant_slug": tenant.slug,
            "status": visit.status,
            "dt": visit.dt.isoformat(),
            "duration_min": int(visit.duration_min or 30),
        },
    )
    return _to_visit_out(visit)


@router.delete("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_visit(
    visit_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    removed_visit = db.execute(
        select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant.id)
    ).scalar_one_or_none()
    ok = delete_visit(db, tenant.id, visit_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found"
        )
    if x_actor_email:
        _audit_critical_action(
            db=db,
            tenant_id=tenant.id,
            action="visit.delete",
            resource_type="visit",
            resource_id=visit_id,
            actor_email=x_actor_email,
            actor_role=x_actor_role,
            request=request,
            payload={},
        )
    if removed_visit:
        for conn in list_calendar_connections(db=db, tenant_id=tenant.id):
            if not conn.enabled:
                continue
            enqueue_calendar_sync_event(
                db=db,
                tenant_id=tenant.id,
                provider=conn.provider,
                action="visit_deleted",
                visit_id=visit_id,
                payload={"visit_id": visit_id, "dt": removed_visit.dt.isoformat()},
            )
        enqueue_outbox_event(
            db=db,
            tenant_id=tenant.id,
            topic="visit.deleted",
            key=f"visit:{visit_id}",
            payload={
                "visit_id": visit_id,
                "tenant_slug": tenant.slug,
                "dt": removed_visit.dt.isoformat(),
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/visits/{visit_id}/status", response_model=VisitOut)
def patch_visit_status(
    visit_id: int,
    payload: VisitStatusUpdate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    try:
        visit = update_visit_status(
            db=db,
            tenant_id=tenant.id,
            visit_id=visit_id,
            new_status=payload.status,
            actor=actor_email,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="visit.status_update",
        resource_type="visit",
        resource_id=visit.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"status": payload.status, "note": payload.note},
    )
    for conn in list_calendar_connections(db=db, tenant_id=tenant.id):
        if not conn.enabled:
            continue
        enqueue_calendar_sync_event(
            db=db,
            tenant_id=tenant.id,
            provider=conn.provider,
            action="visit_status_updated",
            visit_id=visit.id,
            payload={
                "visit_id": visit.id,
                "status": visit.status,
                "note": payload.note,
            },
        )
    if (visit.status or "").strip().lower() == "no_show":
        policy = get_or_create_no_show_policy(db=db, tenant_id=tenant.id)
        if bool(policy.enabled) and float(policy.fee_amount or 0) > 0:
            create_payment_intent(
                db=db,
                tenant_id=tenant.id,
                amount=float(policy.fee_amount),
                reason="no_show_fee",
                visit_id=visit.id,
                client_id=visit.client_id,
                metadata={"policy_grace_minutes": int(policy.grace_minutes or 0)},
            )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="visit.status_changed",
        key=f"visit:{visit.id}",
        payload={
            "visit_id": visit.id,
            "tenant_slug": tenant.slug,
            "status": visit.status,
            "actor_email": actor_email,
        },
    )
    return _to_visit_out(visit)


@router.get("/visits/{visit_id}/history", response_model=list[VisitStatusEventOut])
def visit_status_history(
    visit_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    visit = db.execute(
        select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant.id)
    ).scalar_one_or_none()
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found"
        )
    rows = list_visit_status_events(db, tenant.id, visit_id)
    return [
        VisitStatusEventOut(
            id=row.id,
            visit_id=row.visit_id,
            from_status=row.from_status,
            to_status=row.to_status,
            actor=row.actor,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/reservations", response_model=list[PublicReservationOut])
def list_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = list_public_reservations(
        db=db,
        tenant_id=tenant.id,
        status_filter=status_filter,
        limit=limit,
    )
    return [_to_reservation_out(tenant.slug, r) for r in rows]


@router.patch(
    "/reservations/{reservation_id}/status", response_model=PublicReservationOut
)
def patch_reservation_status(
    reservation_id: int,
    payload: ReservationStatusUpdate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    try:
        reservation = update_reservation_status(
            db=db,
            tenant_id=tenant.id,
            reservation_id=reservation_id,
            new_status=payload.status,
            actor=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="reservation.status_update",
        resource_type="reservation",
        resource_id=reservation.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"status": payload.status},
    )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="reservation.status_changed",
        key=f"reservation:{reservation.id}",
        payload={
            "reservation_id": reservation.id,
            "tenant_slug": tenant.slug,
            "status": reservation.status,
            "actor_email": actor_email,
        },
    )
    return _to_reservation_out(tenant.slug, reservation)


@router.post("/reservations/{reservation_id}/convert", response_model=VisitOut)
def convert_reservation(
    reservation_id: int,
    payload: ReservationConvertCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    try:
        reservation, visit = convert_reservation_to_visit(
            db=db,
            tenant_id=tenant.id,
            reservation_id=reservation_id,
            employee_name=payload.employee_name,
            price=payload.price,
            dt=payload.dt,
            client_name=payload.client_name,
            service_name=payload.service_name,
            actor=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not reservation or not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="reservation.convert_to_visit",
        resource_type="reservation",
        resource_id=reservation.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "visit_id": visit.id,
            "employee_name": payload.employee_name,
            "price": payload.price,
        },
    )
    for conn in list_calendar_connections(db=db, tenant_id=tenant.id):
        if not conn.enabled:
            continue
        enqueue_calendar_sync_event(
            db=db,
            tenant_id=tenant.id,
            provider=conn.provider,
            action="visit_created_from_reservation",
            visit_id=visit.id,
            payload={
                "visit_id": visit.id,
                "reservation_id": reservation.id,
                "dt": visit.dt.isoformat(),
                "employee_name": visit.employee.name,
            },
        )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="reservation.converted",
        key=f"reservation:{reservation.id}",
        payload={
            "reservation_id": reservation.id,
            "visit_id": visit.id,
            "tenant_slug": tenant.slug,
            "actor_email": actor_email,
        },
    )
    return _to_visit_out(visit)


@router.get(
    "/reservations/{reservation_id}/history",
    response_model=list[ReservationStatusEventOut],
)
def reservation_status_history(
    reservation_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    reservation = get_reservation_by_id(db, tenant.id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )

    rows = list_reservation_status_events(db, tenant.id, reservation_id)
    return [
        ReservationStatusEventOut(
            id=row.id,
            reservation_id=row.reservation_id,
            from_status=row.from_status,
            to_status=row.to_status,
            action=row.action,
            actor=row.actor,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/reservations/metrics", response_model=ReservationMetricsOut)
def reservations_metrics(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    return ReservationMetricsOut(**get_reservation_metrics(db, tenant.id))


@router.get("/team/workstations")
def list_workstations_endpoint(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from .models import Workstation
    return db.query(Workstation).filter(Workstation.tenant_id == tenant.id).all()

@router.post("/team/workstations")
def create_workstation(
    name: str,
    type: str = "chair",
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from .models import Workstation
    obj = Workstation(tenant_id=tenant.id, name=name, type=type, pos_x=10, pos_y=10)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@router.patch("/team/workstations/{ws_id}")
def update_workstation_pos(
    ws_id: int,
    pos_x: int,
    pos_y: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from .models import Workstation
    row = db.query(Workstation).filter(Workstation.id == ws_id, Workstation.tenant_id == tenant.id).first()
    if not row: raise HTTPException(status_code=404)
    row.pos_x = pos_x
    row.pos_y = pos_y
    db.commit()
    return {"status": "success"}

@router.get("/summary/smart")
def get_smart_summary(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
):
    """
    Senior IT: Returns personalized financial stats based on user role.
    """
    today = date.today()
    total, count, by_emp = month_report(db, tenant.id, today.year, today.month)
    
    # 1. Admin/Owner view
    if x_actor_role in {"owner", "manager"}:
        return {
            "role": "admin",
            "total_revenue": total,
            "visits_count": count,
            "breakdown": [
                {"name": n, "revenue": r, "commission": c} for (n, p, r, c) in by_emp
            ]
        }
    
    # 2. Employee view (Filter by email/name)
    # Note: Logic to match actor_email to employee name goes here
    my_data = next((item for item in by_emp if item[0].lower() in (x_actor_email or "").lower()), None)
    
    if my_data:
        return {
            "role": "employee",
            "my_revenue": my_data[2],
            "my_commission": my_data[3],
            "visits_count": "hidden"
        }
        
    return {"role": "guest", "msg": "No personal data found."}


@router.get("/report/month", response_model=MonthReport)
def get_month_report(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    total, count, by_emp = month_report(db, tenant.id, year, month)
    month_label = f"{year:04d}-{month:02d}"
    return MonthReport(
        month=month_label,
        total_revenue=total,
        visits_count=count,
        by_employee=[
            {
                "employee": n,
                "commission_pct": p,
                "revenue": r,
                "commission_amount": c,
            }
            for (n, p, r, c) in by_emp
        ],
    )


@router.get("/export/visits.csv")
def get_visits_csv(
    start: datetime,
    end: datetime,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    csv_text = export_visits_csv(db, tenant.id, start, end)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=visits.csv"},
    )


@router.get("/export/report.pdf")
def get_report_pdf(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    total, count, by_emp = month_report(db, tenant.id, year, month)
    month_label = f"{year:04d}-{month:02d}"
    pdf_bytes = build_month_report_pdf(month_label, total, count, by_emp)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report_{month_label}.pdf"
        },
    )


@router.post("/team/employees", response_model=TeamEmployeeOut)
def create_team_employee_endpoint(
    payload: TeamEmployeeCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = create_team_employee(
            db=db,
            tenant_id=tenant.id,
            name=payload.name,
            commission_pct=payload.commission_pct,
        )
        
        # Senior IT: Auto-initialize standard schedule
        from .services import set_employee_weekly_schedule
        standard_days = []
        for i in range(5): # Mon-Fri
            standard_days.append({"weekday": i, "is_day_off": False, "start_hour": 9, "end_hour": 19})
        standard_days.append({"weekday": 5, "is_day_off": False, "start_hour": 9, "end_hour": 15}) # Sat
        standard_days.append({"weekday": 6, "is_day_off": True, "start_hour": None, "end_hour": None}) # Sun
        
        set_employee_weekly_schedule(db, tenant.id, row.id, standard_days)
        
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_409_CONFLICT
            if "exists" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail)

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.employee_create",
        resource_type="employee",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "employee_name": row.name,
            "commission_pct": float(row.commission_pct or 0),
        },
    )
    return _to_team_employee_out(row)


@router.get("/team/employees", response_model=list[TeamEmployeeOut])
def list_team_employees_endpoint(
    q: str | None = Query(default=None, description="Search by name"),
    include_inactive: bool = Query(default=False),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_team_employees(
        db=db, tenant_id=tenant.id, include_inactive=include_inactive, q=q
    )
    return [_to_team_employee_out(row) for row in rows]


@router.patch("/team/employees/{employee_id}", response_model=TeamEmployeeOut)
def patch_team_employee_endpoint(
    employee_id: int,
    payload: TeamEmployeeUpdate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = update_team_employee(
            db=db,
            tenant_id=tenant.id,
            employee_id=employee_id,
            name=payload.name,
            commission_pct=payload.commission_pct,
            is_active=payload.is_active,
            is_portfolio_public=payload.is_portfolio_public,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_409_CONFLICT
            if "exists" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.employee_update",
        resource_type="employee",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "employee_name": row.name,
            "commission_pct": float(row.commission_pct or 0),
            "is_active": bool(row.is_active),
        },
    )
    return _to_team_employee_out(row)


@router.delete("/team/employees/{employee_id}", response_model=TeamEmployeeOut)
def archive_team_employee_endpoint(
    employee_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    row = archive_team_employee(db=db, tenant_id=tenant.id, employee_id=employee_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.employee_archive",
        resource_type="employee",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"employee_name": row.name, "is_active": bool(row.is_active)},
    )
    return _to_team_employee_out(row)


@router.get("/team/employees/{employee_id}/portfolio", response_model=list[PortfolioImageOut])
def list_team_employee_portfolio_endpoint(
    employee_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    # Senior IT: Any authorized staff can see portfolio in admin panel
    row = db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant.id)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    
    return [
        PortfolioImageOut(
            id=img.id,
            image_url=img.image_url,
            description=img.description,
            order_weight=img.order_weight,
            created_at=img.created_at
        ) for img in row.portfolio
    ]


@router.post("/team/employees/{employee_id}/portfolio", response_model=PortfolioImageOut)
def add_team_employee_portfolio_image_endpoint(
    employee_id: int,
    payload: PortfolioImageCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    
    employee = db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant.id)
    ).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    new_img = EmployeePortfolioImage(
        tenant_id=tenant.id,
        employee_id=employee_id,
        image_url=payload.image_url,
        description=payload.description,
        order_weight=payload.order_weight
    )
    db.add(new_img)
    db.commit()
    db.refresh(new_img)

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.portfolio_add",
        resource_type="employee_portfolio_image",
        resource_id=new_img.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"employee_id": employee_id, "image_url": payload.image_url},
    )

    return PortfolioImageOut(
        id=new_img.id,
        image_url=new_img.image_url,
        description=new_img.description,
        order_weight=new_img.order_weight,
        created_at=new_img.created_at
    )


@router.delete("/team/employees/{employee_id}/portfolio/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team_employee_portfolio_image_endpoint(
    employee_id: int,
    image_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    
    img = db.execute(
        select(EmployeePortfolioImage).where(
            EmployeePortfolioImage.id == image_id,
            EmployeePortfolioImage.employee_id == employee_id,
            EmployeePortfolioImage.tenant_id == tenant.id
        )
    ).scalar_one_or_none()
    
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio image not found")

    db.delete(img)
    db.commit()

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.portfolio_delete",
        resource_type="employee_portfolio_image",
        resource_id=image_id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"employee_id": employee_id},
    )


@router.put(
    "/team/employees/{employee_id}/weekly-schedule",
    response_model=list[EmployeeWeeklyScheduleDayOut],
)
def set_employee_weekly_schedule_endpoint(
    employee_id: int,
    payload: EmployeeWeeklyScheduleSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    rows = set_employee_weekly_schedule(
        db=db,
        tenant_id=tenant.id,
        employee_id=employee_id,
        days=[row.dict() for row in payload.days],
    )
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )

    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="team.employee_weekly_schedule_upsert",
        resource_type="employee_weekly_schedule",
        resource_id=employee_id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"days": [row.dict() for row in payload.days]},
    )
    return [EmployeeWeeklyScheduleDayOut(**row) for row in rows]


@router.get(
    "/team/employees/{employee_id}/weekly-schedule",
    response_model=list[EmployeeWeeklyScheduleDayOut],
)
def get_employee_weekly_schedule_endpoint(
    employee_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_employee_weekly_schedule(
        db=db,
        tenant_id=tenant.id,
        employee_id=employee_id,
    )
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    return [EmployeeWeeklyScheduleDayOut(**row) for row in rows]


@router.post("/team/employees/{employee_id}/weekly-schedule/apply-range")
def apply_employee_weekly_schedule_to_range_endpoint(
    employee_id: int,
    payload: TeamWeeklyApplyRangeIn,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        written = apply_employee_weekly_schedule_to_range(
            db=db,
            tenant_id=tenant.id,
            employee_id=employee_id,
            start_day=payload.start_day,
            end_day=payload.end_day,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if written is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    return {"employee_id": employee_id, "days_written": int(written)}


@router.post(
    "/team/employees/{employee_id}/capabilities",
    response_model=TeamEmployeeCapabilityOut,
)
def upsert_employee_capability_endpoint(
    employee_id: int,
    payload: TeamEmployeeCapabilitySet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = upsert_employee_service_capability(
            db=db,
            tenant_id=tenant.id,
            employee_id=employee_id,
            service_name=payload.service_name,
            duration_min=payload.duration_min,
            price_override=payload.price_override,
            is_active=payload.is_active,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    employee_name = _employee_name(db, tenant.id, employee_id)
    return _to_team_capability_out(row, employee_name=employee_name)


@router.get(
    "/team/employees/{employee_id}/capabilities",
    response_model=list[TeamEmployeeCapabilityOut],
)
def list_employee_capabilities_endpoint(
    employee_id: int,
    active_only: bool = Query(default=False),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_employee_service_capabilities(
        db=db,
        tenant_id=tenant.id,
        employee_id=employee_id,
        active_only=active_only,
    )
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    employee_name = _employee_name(db, tenant.id, employee_id)
    return [_to_team_capability_out(row, employee_name=employee_name) for row in rows]


@router.post("/team/leaves", response_model=TeamLeaveOut)
def create_team_leave_endpoint(
    payload: TeamLeaveCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = create_employee_leave_request(
            db=db,
            tenant_id=tenant.id,
            employee_id=payload.employee_id,
            start_day=payload.start_day,
            end_day=payload.end_day,
            reason=payload.reason,
            requested_by=actor_email,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "overlapping" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    employee_name = _employee_name(db, tenant.id, row.employee_id)
    return _to_team_leave_out(row, employee_name=employee_name)


@router.get("/team/leaves", response_model=list[TeamLeaveOut])
def list_team_leaves_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    employee_id: int | None = Query(default=None),
    start_day: date | None = Query(default=None),
    end_day: date | None = Query(default=None),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_employee_leave_requests(
        db=db,
        tenant_id=tenant.id,
        status_filter=status_filter,
        employee_id=employee_id,
        start_day=start_day,
        end_day=end_day,
    )
    return [
        _to_team_leave_out(
            row, employee_name=_employee_name(db, tenant.id, row.employee_id)
        )
        for row in rows
    ]


@router.patch("/team/leaves/{leave_id}/decision", response_model=TeamLeaveOut)
def decide_team_leave_endpoint(
    leave_id: int,
    payload: TeamLeaveDecision,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = decide_employee_leave_request(
            db=db,
            tenant_id=tenant.id,
            leave_id=leave_id,
            decision=payload.decision,
            decision_note=payload.decision_note,
            decided_by=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leave not found"
        )
    return _to_team_leave_out(
        row, employee_name=_employee_name(db, tenant.id, row.employee_id)
    )


@router.post("/team/swaps", response_model=TeamSwapOut)
def create_team_swap_endpoint(
    payload: TeamSwapCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = create_shift_swap_request(
            db=db,
            tenant_id=tenant.id,
            shift_day=payload.shift_day,
            from_employee_id=payload.from_employee_id,
            to_employee_id=payload.to_employee_id,
            from_start_hour=payload.from_start_hour,
            from_end_hour=payload.from_end_hour,
            to_start_hour=payload.to_start_hour,
            to_end_hour=payload.to_end_hour,
            reason=payload.reason,
            requested_by=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    return _to_team_swap_out(
        row,
        from_employee_name=_employee_name(db, tenant.id, row.from_employee_id),
        to_employee_name=_employee_name(db, tenant.id, row.to_employee_id),
    )


@router.get("/team/swaps", response_model=list[TeamSwapOut])
def list_team_swaps_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    start_day: date | None = Query(default=None),
    end_day: date | None = Query(default=None),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_shift_swap_requests(
        db=db,
        tenant_id=tenant.id,
        status_filter=status_filter,
        start_day=start_day,
        end_day=end_day,
    )
    return [
        _to_team_swap_out(
            row,
            from_employee_name=_employee_name(db, tenant.id, row.from_employee_id),
            to_employee_name=_employee_name(db, tenant.id, row.to_employee_id),
        )
        for row in rows
    ]


@router.patch("/team/swaps/{swap_id}/decision", response_model=TeamSwapOut)
def decide_team_swap_endpoint(
    swap_id: int,
    payload: TeamSwapDecision,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = decide_shift_swap_request(
            db=db,
            tenant_id=tenant.id,
            swap_id=swap_id,
            decision=payload.decision,
            decision_note=payload.decision_note,
            decided_by=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Swap not found"
        )
    return _to_team_swap_out(
        row,
        from_employee_name=_employee_name(db, tenant.id, row.from_employee_id),
        to_employee_name=_employee_name(db, tenant.id, row.to_employee_id),
    )


@router.post("/team/visits/{visit_id}/reassign", response_model=VisitOut)
def reassign_visit_endpoint(
    visit_id: int,
    payload: TeamVisitReassignIn,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    try:
        row = reassign_visit_employee(
            db=db,
            tenant_id=tenant.id,
            visit_id=visit_id,
            to_employee_id=payload.to_employee_id,
            reason=payload.reason,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found"
        )
    return _to_visit_out(row)


@router.post("/team/time-clock/events", response_model=TeamTimeClockOut)
def create_time_clock_event_endpoint(
    payload: TeamTimeClockIn,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    try:
        row = create_time_clock_entry(
            db=db,
            tenant_id=tenant.id,
            employee_id=payload.employee_id,
            event_type=payload.event_type,
            event_dt=payload.event_dt,
            source=payload.source,
            note=payload.note,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    return TeamTimeClockOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=_employee_name(db, tenant.id, row.employee_id),
        event_type=row.event_type,
        event_dt=row.event_dt,
        source=row.source,
        note=row.note,
        created_at=row.created_at,
    )


@router.get("/team/time-clock/day-report", response_model=list[TeamTimeClockDayRowOut])
def list_team_time_clock_day_report_endpoint(
    day: date = Query(...),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_time_clock_day_report(db=db, tenant_id=tenant.id, day=day)
    return [TeamTimeClockDayRowOut(**row) for row in rows]


@router.get("/team/schedule-audit", response_model=list[ScheduleAuditOut])
def list_team_schedule_audit_endpoint(
    limit: int = Query(default=200, ge=1, le=1000),
    action: str | None = Query(default=None),
    employee_id: int | None = Query(default=None),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    rows = list_schedule_audit_events(
        db=db,
        tenant_id=tenant.id,
        limit=limit,
        action=action,
        employee_id=employee_id,
    )
    return [
        ScheduleAuditOut(
            id=row.id,
            action=row.action,
            actor_email=row.actor_email,
            employee_id=row.employee_id,
            related_id=row.related_id,
            payload_json=row.payload_json,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/team/notifications", response_model=list[ScheduleNotificationOut])
def list_team_notifications_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    rows = list_schedule_notifications(
        db=db,
        tenant_id=tenant.id,
        status_filter=status_filter,
        limit=limit,
    )
    return [
        ScheduleNotificationOut(
            id=row.id,
            employee_id=row.employee_id,
            employee_name=employee_name,
            event_type=row.event_type,
            message=row.message,
            channel=row.channel,
            status=row.status,
            last_error=row.last_error,
            sent_at=row.sent_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for (row, employee_name) in rows
    ]


@router.patch(
    "/team/notifications/{notification_id}/status",
    response_model=ScheduleNotificationOut,
)
def set_team_notification_status_endpoint(
    notification_id: int,
    payload: ScheduleNotificationSetStatus,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, _ = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = set_schedule_notification_status(
            db=db,
            tenant_id=tenant.id,
            notification_id=notification_id,
            status_value=payload.status,
            last_error=payload.last_error,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    return ScheduleNotificationOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=_employee_name(db, tenant.id, row.employee_id)
        if row.employee_id
        else None,
        event_type=row.event_type,
        message=row.message,
        channel=row.channel,
        status=row.status,
        last_error=row.last_error,
        sent_at=row.sent_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/availability/day", response_model=EmployeeAvailabilityOut)
def set_employee_day_availability(
    payload: EmployeeAvailabilitySet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    row = upsert_employee_availability_day(
        db=db,
        tenant_id=tenant.id,
        employee_name=payload.employee_name,
        day=payload.day,
        is_day_off=payload.is_day_off,
        start_hour=payload.start_hour,
        end_hour=payload.end_hour,
        note=payload.note,
    )
    out = EmployeeAvailabilityOut(
        day=row.day,
        employee_name=row.employee_name,
        is_day_off=bool(row.is_day_off),
        start_hour=row.start_hour,
        end_hour=row.end_hour,
        source="override",
        note=row.note,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="availability.day_upsert",
        resource_type="employee_availability_day",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "employee_name": payload.employee_name,
            "day": payload.day.isoformat(),
            "is_day_off": payload.is_day_off,
        },
    )
    return out


@router.get("/availability", response_model=list[EmployeeAvailabilityOut])
def get_employee_availability(
    employee_name: str = Query(...),
    start_day: date = Query(...),
    end_day: date = Query(...),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = list_employee_availability(
        db=db,
        tenant_id=tenant.id,
        employee_name=employee_name,
        start_day=start_day,
        end_day=end_day,
    )
    return [EmployeeAvailabilityOut(**r) for r in rows]


@router.post("/availability/blocks", response_model=EmployeeBlockOut)
def add_employee_block(
    payload: EmployeeBlockCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    try:
        row = create_employee_block(
            db=db,
            tenant_id=tenant.id,
            employee_name=payload.employee_name,
            start_dt=payload.start_dt,
            end_dt=payload.end_dt,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    out = EmployeeBlockOut(
        id=row.id,
        employee_name=row.employee_name,
        start_dt=row.start_dt,
        end_dt=row.end_dt,
        reason=row.reason,
        created_at=row.created_at,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="availability.block_create",
        resource_type="employee_block",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "employee_name": payload.employee_name,
            "start_dt": payload.start_dt.isoformat(),
            "end_dt": payload.end_dt.isoformat(),
        },
    )
    return out


@router.get("/availability/blocks", response_model=list[EmployeeBlockOut])
def get_employee_blocks(
    employee_name: str = Query(...),
    start_day: date = Query(...),
    end_day: date = Query(...),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = list_employee_blocks(
        db=db,
        tenant_id=tenant.id,
        employee_name=employee_name,
        start_day=start_day,
        end_day=end_day,
    )
    return [
        EmployeeBlockOut(
            id=row.id,
            employee_name=row.employee_name,
            start_dt=row.start_dt,
            end_dt=row.end_dt,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/buffers/service/{service_name}", response_model=BufferOut)
def set_service_buffer(
    service_name: str,
    payload: BufferSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    row = upsert_service_buffer(
        db=db,
        tenant_id=tenant.id,
        service_name=service_name,
        before_min=payload.before_min,
        after_min=payload.after_min,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="buffer.service_upsert",
        resource_type="service_buffer",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "service_name": row.service_name,
            "before_min": row.before_min,
            "after_min": row.after_min,
        },
    )
    return BufferOut(
        target=row.service_name, before_min=row.before_min, after_min=row.after_min
    )


@router.get("/buffers/service/{service_name}", response_model=BufferOut)
def read_service_buffer(
    service_name: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    row = get_service_buffer(db=db, tenant_id=tenant.id, service_name=service_name)
    if not row:
        return BufferOut(target=service_name, before_min=0, after_min=0)
    return BufferOut(
        target=row.service_name, before_min=row.before_min, after_min=row.after_min
    )


@router.post("/buffers/employee/{employee_name}", response_model=BufferOut)
def set_employee_buffer(
    employee_name: str,
    payload: BufferSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager"},
    )
    row = upsert_employee_buffer(
        db=db,
        tenant_id=tenant.id,
        employee_name=employee_name,
        before_min=payload.before_min,
        after_min=payload.after_min,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="buffer.employee_upsert",
        resource_type="employee_buffer",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "employee_name": row.employee_name,
            "before_min": row.before_min,
            "after_min": row.after_min,
        },
    )
    return BufferOut(
        target=row.employee_name, before_min=row.before_min, after_min=row.after_min
    )


@router.get("/buffers/employee/{employee_name}", response_model=BufferOut)
def read_employee_buffer(
    employee_name: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    row = get_employee_buffer(db=db, tenant_id=tenant.id, employee_name=employee_name)
    if not row:
        return BufferOut(target=employee_name, before_min=0, after_min=0)
    return BufferOut(
        target=row.employee_name, before_min=row.before_min, after_min=row.after_min
    )


@router.get("/slots/recommendations", response_model=list[SlotRecommendationOut])
def get_slot_recommendations(
    day: date = Query(...),
    employee_name: str = Query(...),
    service_name: str = Query(...),
    duration_min: int | None = Query(default=None, ge=5, le=480),
    step_min: int = Query(default=5, ge=5, le=60),
    limit: int = Query(default=8, ge=1, le=50),
    canary_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = recommend_slots(
        db=db,
        tenant_id=tenant.id,
        employee_name=employee_name,
        service_name=service_name,
        day=day,
        duration_min=duration_min,
        step_min=step_min,
        limit=limit,
    )
    if is_feature_enabled(
        db=db,
        tenant_id=tenant.id,
        flag_key="slots_v2_scoring",
        subject_key=canary_key or employee_name,
    ):
        for row in rows:
            base = float(row.get("score", 0.0))
            # v2 canary: slight uplift for earlier slots, stronger evening penalty.
            hour = int(row["start_dt"].hour)
            if hour <= 11:
                base += 5.0
            elif hour >= 17:
                base -= 7.0
            row["score"] = round(max(0.0, min(100.0, base)), 2)
    return [SlotRecommendationOut(**r) for r in rows]


@router.get("/clients/search", response_model=list[ClientSearchOut])
def search_clients_endpoint(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = search_clients(db=db, tenant_id=tenant.id, query=q, limit=limit)
    return [ClientSearchOut(**r) for r in rows]


@router.get("/clients/{client_id}", response_model=ClientDetailOut)
def get_client_detail_endpoint(
    client_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    detail = get_client_detail(db=db, tenant_id=tenant.id, client_id=client_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )
    return ClientDetailOut(
        id=detail["id"],
        name=detail["name"],
        phone=detail["phone"],
        visits_count=detail["visits_count"],
        last_visit_dt=detail["last_visit_dt"],
        notes=[
            ClientNoteOut(
                id=n.id,
                client_id=n.client_id,
                note=n.note,
                actor=n.actor,
                created_at=n.created_at,
            )
            for n in detail["notes"]
        ],
        visits=[
            ClientVisitHistoryOut(
                visit_id=v.id,
                dt=v.dt,
                service_name=v.service.name,
                employee_name=v.employee.name,
                price=float(v.price),
                status=v.status,
            )
            for v in detail["visits"]
        ],
    )


@router.post("/clients/{client_id}/notes", response_model=ClientNoteOut)
def add_client_note_endpoint(
    client_id: int,
    payload: ClientNoteCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db=db,
        tenant=tenant,
        actor_email=x_actor_email,
        actor_role=x_actor_role,
        allowed_roles={"owner", "manager", "reception"},
    )
    row = add_client_note(
        db=db,
        tenant_id=tenant.id,
        client_id=client_id,
        note=payload.note,
        actor=actor_email,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )
    out = ClientNoteOut(
        id=row.id,
        client_id=row.client_id,
        note=row.note,
        actor=row.actor,
        created_at=row.created_at,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="client.note_add",
        resource_type="client_note",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"client_id": client_id},
    )
    return out


@router.get("/pulse/day", response_model=DayPulseOut)
def get_pulse_day(
    day: date = Query(...),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    return DayPulseOut(**get_day_pulse(db=db, tenant_id=tenant.id, day=day))


@router.get("/integrity/conversions", response_model=ConversionIntegrityReportOut)
def get_integrity_conversions(
    limit: int = Query(default=100, ge=1, le=500),
    _admin: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    return ConversionIntegrityReportOut(
        **get_conversion_integrity_report(db=db, tenant_id=tenant.id, limit=limit)
    )


@router.get("/ops/metrics", response_model=OpsMetricsOut)
def get_ops_metrics(
    window_minutes: int = Query(
        default=settings.OPS_ALERTS_WINDOW_MINUTES, ge=1, le=1440
    ),
    _admin: None = Depends(require_admin_api_key),
):
    return OpsMetricsOut(**get_ops_metrics_snapshot(window_minutes=window_minutes))


@router.get("/ops/alerts", response_model=list[OpsAlertOut])
def get_ops_alerts_endpoint(
    window_minutes: int = Query(
        default=settings.OPS_ALERTS_WINDOW_MINUTES, ge=1, le=1440
    ),
    _admin: None = Depends(require_admin_api_key),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    integrity = get_conversion_integrity_report(db=db, tenant_id=tenant.id, limit=100)
    rows = get_ops_alerts(
        window_minutes=window_minutes,
        integrity_issues_count=int(integrity.get("issues_count", 0)),
    )
    jobs_health = get_background_jobs_health(
        db=db, tenant_id=tenant.id, stale_running_minutes=15
    )
    jobs_alerts = build_background_job_alerts(jobs_health)
    if jobs_alerts:
        rows = [row for row in rows if str(row.get("code")) != "ops_ok"]
        rows.extend(jobs_alerts)
    outbox_health = get_outbox_health(db=db, tenant_id=tenant.id)
    if int(outbox_health.get("dead_letter_count", 0)) > 0:
        rows = [row for row in rows if str(row.get("code")) != "ops_ok"]
        rows.append(
            {
                "code": "outbox_dead_letter_detected",
                "severity": "high",
                "message": f"Detected {int(outbox_health.get('dead_letter_count', 0))} outbox dead-letter events",
            }
        )
    return [OpsAlertOut(**row) for row in rows]


@router.get("/ops/jobs/health", response_model=BackgroundJobsHealthOut)
def get_jobs_health_endpoint(
    stale_running_minutes: int = Query(default=15, ge=1, le=1440),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    return BackgroundJobsHealthOut(
        **get_background_jobs_health(
            db=db,
            tenant_id=tenant.id,
            stale_running_minutes=stale_running_minutes,
        )
    )


@router.get("/ops/status", response_model=OpsStatusOut)
def get_ops_status_endpoint(
    window_minutes: int = Query(
        default=settings.OPS_ALERTS_WINDOW_MINUTES, ge=1, le=1440
    ),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    metrics = get_ops_metrics_snapshot(window_minutes=window_minutes)
    integrity = get_conversion_integrity_report(db=db, tenant_id=tenant.id, limit=100)
    alerts = get_ops_alerts(
        window_minutes=window_minutes,
        integrity_issues_count=int(integrity.get("issues_count", 0)),
    )
    jobs_health = get_background_jobs_health(
        db=db, tenant_id=tenant.id, stale_running_minutes=15
    )
    jobs_alerts = build_background_job_alerts(jobs_health)
    if jobs_alerts:
        alerts = [row for row in alerts if str(row.get("code")) != "ops_ok"]
        alerts.extend(jobs_alerts)
    outbox_health = get_outbox_health(db=db, tenant_id=tenant.id)
    if int(outbox_health.get("dead_letter_count", 0)) > 0:
        alerts = [row for row in alerts if str(row.get("code")) != "ops_ok"]
        alerts.append(
            {
                "code": "outbox_dead_letter_detected",
                "severity": "high",
                "message": f"Detected {int(outbox_health.get('dead_letter_count', 0))} outbox dead-letter events",
            }
        )
    slo_rows = evaluate_slos(db=db, tenant_id=tenant.id)
    slo_total = len(slo_rows)
    slo_ok = len([row for row in slo_rows if bool(row.get("ok"))])
    slo_failed = max(0, slo_total - slo_ok)
    active_alert_codes = [
        str(row.get("code")) for row in alerts if str(row.get("code")) != "ops_ok"
    ]
    return OpsStatusOut(
        checked_at=datetime.now(timezone.utc).replace(tzinfo=None),
        metrics_window_minutes=int(window_minutes),
        requests_total=int(metrics.get("requests_total", 0)),
        latency_ms_p95=float(metrics.get("latency_ms_p95", 0.0)),
        error_5xx_count=int(metrics.get("error_5xx_count", 0)),
        alerts_count=len(active_alert_codes),
        active_alert_codes=active_alert_codes,
        slo_total=int(slo_total),
        slo_ok=int(slo_ok),
        slo_failed=int(slo_failed),
        jobs_health=jobs_health,
        outbox_health=outbox_health,
    )


@router.get(
    "/reservations/assistant", response_model=list[ReservationAssistantActionOut]
)
def reservations_assistant(
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    rows = get_reservation_assistant_actions(db=db, tenant_id=tenant.id, limit=limit)
    return [ReservationAssistantActionOut(**r) for r in rows]


@router.post("/rbac/roles", response_model=TenantUserRoleOut)
def set_tenant_user_role_endpoint(
    payload: TenantUserRoleSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner"}
    )
    try:
        row = upsert_tenant_user_role(
            db=db, tenant_id=tenant.id, email=payload.email, role=payload.role
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="rbac.role_upsert",
        resource_type="tenant_user_role",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"email": row.email, "role": row.role},
    )
    return TenantUserRoleOut(
        email=row.email,
        role=row.role,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/rbac/roles", response_model=list[TenantUserRoleOut])
def list_tenant_user_roles_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_tenant_user_roles(db=db, tenant_id=tenant.id)
    return [
        TenantUserRoleOut(
            email=row.email,
            role=row.role,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/audit/logs", response_model=list[AuditLogOut])
def list_audit_logs_endpoint(
    limit: int = Query(default=100, ge=1, le=1000),
    action: str | None = Query(default=None),
    actor_email_filter: str | None = Query(default=None, alias="actor_email"),
    resource_type: str | None = Query(default=None),
    since_minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 365),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_audit_logs(
        db=db,
        tenant_id=tenant.id,
        limit=limit,
        action=action,
        actor_email=actor_email_filter,
        resource_type=resource_type,
        since_minutes=since_minutes,
    )
    return [
        AuditLogOut(
            id=row.id,
            actor_email=row.actor_email,
            actor_role=row.actor_role,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            request_id=row.request_id,
            payload_json=row.payload_json,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/policies/{policy_key}", response_model=TenantPolicyOut)
def get_policy_endpoint(
    policy_key: str,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    value = get_tenant_policy(db=db, tenant_id=tenant.id, policy_key=policy_key)
    return TenantPolicyOut(
        key=policy_key, value=value, updated_by=None, updated_at=datetime.utcnow()
    )


@router.put("/policies/{policy_key}", response_model=TenantPolicyOut)
def set_policy_endpoint(
    policy_key: str,
    payload: TenantPolicySet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    try:
        row = upsert_tenant_policy(
            db=db,
            tenant_id=tenant.id,
            policy_key=policy_key,
            value=payload.value,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="policy.upsert",
        resource_type="tenant_policy",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"key": policy_key},
    )
    return TenantPolicyOut(
        key=row.key,
        value=payload.value,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


@router.post("/jobs", response_model=BackgroundJobOut)
def create_background_job_endpoint(
    payload: BackgroundJobCreate,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = enqueue_background_job(
        db=db,
        tenant_id=tenant.id,
        queue=payload.queue,
        job_type=payload.job_type,
        payload=payload.payload,
        max_attempts=payload.max_attempts,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="job.enqueue",
        resource_type="background_job",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"job_type": row.job_type, "queue": row.queue},
    )
    return BackgroundJobOut(
        id=row.id,
        tenant_id=row.tenant_id,
        queue=row.queue,
        job_type=row.job_type,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        run_after=row.run_after,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/jobs", response_model=list[BackgroundJobOut])
def list_background_jobs_endpoint(
    queue: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_background_jobs(
        db=db,
        tenant_id=tenant.id,
        queue=queue,
        status=status_filter,
        limit=limit,
    )
    return [
        BackgroundJobOut(
            id=row.id,
            tenant_id=row.tenant_id,
            queue=row.queue,
            job_type=row.job_type,
            status=row.status,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            last_error=row.last_error,
            run_after=row.run_after,
            finished_at=row.finished_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/jobs/{job_id}/retry", response_model=BackgroundJobOut)
def retry_dead_letter_job_endpoint(
    job_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = retry_dead_letter_job(db=db, job_id=job_id)
    if not row or row.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="job.retry",
        resource_type="background_job",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={},
    )
    return BackgroundJobOut(
        id=row.id,
        tenant_id=row.tenant_id,
        queue=row.queue,
        job_type=row.job_type,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        run_after=row.run_after,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJobOut)
def cancel_queued_job_endpoint(
    job_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = cancel_queued_background_job(db=db, tenant_id=tenant.id, job_id=job_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="job.cancel",
        resource_type="background_job",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={},
    )
    return BackgroundJobOut(
        id=row.id,
        tenant_id=row.tenant_id,
        queue=row.queue,
        job_type=row.job_type,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        run_after=row.run_after,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/jobs/cleanup", response_model=BackgroundJobCleanupOut)
def cleanup_background_jobs_endpoint(
    older_than_hours: int = Query(default=24 * 7, ge=1, le=24 * 365),
    statuses_csv: str | None = Query(default=None, alias="statuses"),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    statuses = (
        [s.strip().lower() for s in (statuses_csv or "").split(",") if s.strip()]
        if statuses_csv
        else None
    )
    result = cleanup_background_jobs(
        db=db,
        tenant_id=tenant.id,
        statuses=statuses,
        older_than_hours=older_than_hours,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="job.cleanup",
        resource_type="background_job",
        resource_id=None,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "older_than_hours": older_than_hours,
            "statuses": result.get("statuses", []),
        },
    )
    return BackgroundJobCleanupOut(**result)


@router.post("/integrations/calendar/connections", response_model=CalendarConnectionOut)
def set_calendar_connection_endpoint(
    payload: CalendarConnectionSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    try:
        row = upsert_calendar_connection(
            db=db,
            tenant_id=tenant.id,
            provider=payload.provider,
            external_calendar_id=payload.external_calendar_id,
            sync_direction=payload.sync_direction,
            webhook_secret=payload.webhook_secret,
            outbound_webhook_url=payload.outbound_webhook_url,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="calendar.connection_upsert",
        resource_type="calendar_connection",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "provider": row.provider,
            "external_calendar_id": row.external_calendar_id,
        },
    )
    return CalendarConnectionOut(
        id=row.id,
        provider=row.provider,
        external_calendar_id=row.external_calendar_id,
        sync_direction=row.sync_direction,
        webhook_secret=_mask_secret(row.webhook_secret),
        outbound_webhook_url=row.outbound_webhook_url,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/integrations/calendar/connections", response_model=list[CalendarConnectionOut]
)
def list_calendar_connections_endpoint(
    provider: str | None = Query(default=None),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_calendar_connections(db=db, tenant_id=tenant.id, provider=provider)
    return [
        CalendarConnectionOut(
            id=row.id,
            provider=row.provider,
            external_calendar_id=row.external_calendar_id,
            sync_direction=row.sync_direction,
            webhook_secret=_mask_secret(row.webhook_secret),
            outbound_webhook_url=row.outbound_webhook_url,
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/integrations/calendar/events", response_model=list[CalendarSyncEventOut])
def list_calendar_sync_events_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_calendar_sync_events(
        db=db, tenant_id=tenant.id, status=status_filter, limit=limit
    )
    return [
        CalendarSyncEventOut(
            id=row.id,
            provider=row.provider,
            source=row.source,
            external_event_id=row.external_event_id,
            visit_id=row.visit_id,
            action=row.action,
            status=row.status,
            retries=row.retries,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post(
    "/integrations/calendar/events/{event_id}/replay",
    response_model=CalendarSyncEventOut,
)
def replay_calendar_sync_event_endpoint(
    event_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = replay_calendar_sync_event(db=db, tenant_id=tenant.id, event_id=event_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar sync event not found",
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="calendar.event_replay",
        resource_type="calendar_sync_event",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"source_event_id": event_id},
    )
    return CalendarSyncEventOut(
        id=row.id,
        provider=row.provider,
        source=row.source,
        external_event_id=row.external_event_id,
        visit_id=row.visit_id,
        action=row.action,
        status=row.status,
        retries=row.retries,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/integrations/calendar/webhooks/{provider}", response_model=CalendarSyncEventOut
)
def ingest_calendar_webhook_endpoint(
    provider: str,
    payload: dict,
    x_webhook_secret: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
    x_webhook_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    try:
        row = ingest_calendar_webhook(
            db=db,
            provider=provider,
            webhook_secret=x_webhook_secret,
            payload=payload,
            webhook_timestamp=x_webhook_timestamp,
            webhook_signature=x_webhook_signature,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return CalendarSyncEventOut(
        id=row.id,
        provider=row.provider,
        source=row.source,
        external_event_id=row.external_event_id,
        visit_id=row.visit_id,
        action=row.action,
        status=row.status,
        retries=row.retries,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/export/report.pdf/jobs", response_model=BackgroundJobOut)
def enqueue_month_report_pdf_job(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = enqueue_background_job(
        db=db,
        tenant_id=tenant.id,
        queue="exports",
        job_type="generate_pdf_report",
        payload={"year": year, "month": month},
        max_attempts=4,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="report.pdf_job_enqueue",
        resource_type="background_job",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"year": year, "month": month},
    )
    return BackgroundJobOut(
        id=row.id,
        tenant_id=row.tenant_id,
        queue=row.queue,
        job_type=row.job_type,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        run_after=row.run_after,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/ops/slo", response_model=SloDefinitionOut)
def set_slo_definition_endpoint(
    payload: SloDefinitionSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    try:
        row = upsert_slo_definition(
            db=db,
            tenant_id=tenant.id,
            name=payload.name,
            metric_type=payload.metric_type,
            target=payload.target,
            window_minutes=payload.window_minutes,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="slo.upsert",
        resource_type="slo_definition",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"name": row.name, "metric_type": row.metric_type},
    )
    return SloDefinitionOut(
        id=row.id,
        name=row.name,
        metric_type=row.metric_type,
        target=float(row.target),
        window_minutes=row.window_minutes,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/ops/slo", response_model=list[SloDefinitionOut])
def list_slo_definitions_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_slo_definitions(db=db, tenant_id=tenant.id)
    return [
        SloDefinitionOut(
            id=row.id,
            name=row.name,
            metric_type=row.metric_type,
            target=float(row.target),
            window_minutes=row.window_minutes,
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/ops/slo/evaluate", response_model=list[SloEvaluationOut])
def evaluate_slo_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = evaluate_slos(db=db, tenant_id=tenant.id)
    return [SloEvaluationOut(**row) for row in rows]


@router.post("/ops/alerts/routes", response_model=AlertRouteOut)
def set_alert_route_endpoint(
    payload: AlertRouteSet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    try:
        row = upsert_alert_route(
            db=db,
            tenant_id=tenant.id,
            channel=payload.channel,
            target=payload.target,
            min_severity=payload.min_severity,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="alert_route.upsert",
        resource_type="alert_route",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={"channel": row.channel, "target": row.target},
    )
    return AlertRouteOut(
        id=row.id,
        channel=row.channel,
        target=row.target,
        min_severity=row.min_severity,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/ops/alerts/routes", response_model=list[AlertRouteOut])
def list_alert_routes_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    rows = list_alert_routes(db=db, tenant_id=tenant.id)
    return [
        AlertRouteOut(
            id=row.id,
            channel=row.channel,
            target=row.target,
            min_severity=row.min_severity,
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/ops/alerts/dispatch", response_model=AlertDispatchOut)
def dispatch_alerts_endpoint(
    window_minutes: int = Query(
        default=settings.OPS_ALERTS_WINDOW_MINUTES, ge=1, le=1440
    ),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    result = dispatch_alerts_to_routes(
        db=db, tenant_id=tenant.id, window_minutes=window_minutes
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="alerts.dispatch",
        resource_type="ops_alerts",
        resource_id=None,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={
            "window_minutes": window_minutes,
            "dispatched_jobs": result["dispatched_jobs"],
        },
    )
    return AlertDispatchOut(**result)


@router.get("/gdpr/retention", response_model=DataRetentionPolicyOut)
def get_retention_policy_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = get_or_create_retention_policy(db=db, tenant_id=tenant.id)
    return DataRetentionPolicyOut(
        client_notes_days=row.client_notes_days,
        audit_logs_days=row.audit_logs_days,
        status_events_days=row.status_events_days,
        rate_limit_events_hours=row.rate_limit_events_hours,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


@router.put("/gdpr/retention", response_model=DataRetentionPolicyOut)
def set_retention_policy_endpoint(
    payload: DataRetentionPolicySet,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner"}
    )
    row = upsert_retention_policy(
        db=db,
        tenant_id=tenant.id,
        client_notes_days=payload.client_notes_days,
        audit_logs_days=payload.audit_logs_days,
        status_events_days=payload.status_events_days,
        rate_limit_events_hours=payload.rate_limit_events_hours,
        actor_email=actor_email,
    )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="gdpr.retention_upsert",
        resource_type="data_retention_policy",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload=payload.dict(),
    )
    return DataRetentionPolicyOut(
        client_notes_days=row.client_notes_days,
        audit_logs_days=row.audit_logs_days,
        status_events_days=row.status_events_days,
        rate_limit_events_hours=row.rate_limit_events_hours,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


@router.post("/gdpr/cleanup", response_model=DataRetentionCleanupOut)
def run_retention_cleanup_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    result = run_retention_cleanup(db=db, tenant_id=tenant.id)
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="gdpr.cleanup_run",
        resource_type="gdpr_cleanup",
        resource_id=None,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload=result,
    )
    return DataRetentionCleanupOut(**result)


@router.get("/gdpr/cleanup/preview", response_model=DataRetentionCleanupPreviewOut)
def preview_retention_cleanup_endpoint(
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    result = preview_retention_cleanup(db=db, tenant_id=tenant.id)
    return DataRetentionCleanupPreviewOut(**result)


@router.post("/gdpr/clients/{client_id}/anonymize")
def anonymize_client_endpoint(
    client_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner", "manager"}
    )
    row = anonymize_client_data(db=db, tenant_id=tenant.id, client_id=client_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="gdpr.client_anonymize",
        resource_type="client",
        resource_id=row.id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={},
    )
    return {"ok": True, "client_id": row.id, "client_name": row.name}


@router.delete("/gdpr/clients/{client_id}")
def delete_client_endpoint(
    client_id: int,
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from .enterprise import delete_client_if_possible

    actor_email, actor_role = _require_actor_for_roles(
        db, tenant, x_actor_email, x_actor_role, {"owner"}
    )
    ok, reason = delete_client_if_possible(
        db=db, tenant_id=tenant.id, client_id=client_id
    )
    if not ok:
        if reason == "Client not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=reason)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    _audit_critical_action(
        db=db,
        tenant_id=tenant.id,
        action="gdpr.client_delete",
        resource_type="client",
        resource_id=client_id,
        actor_email=actor_email,
        actor_role=actor_role,
        request=request,
        payload={},
    )
    return {"ok": True, "client_id": client_id}


@public_router.get("/{tenant_slug}/employees/{employee_id}/portfolio", response_model=list[PortfolioImageOut])
def get_public_employee_portfolio_endpoint(
    tenant_slug: str,
    employee_id: int,
    db: Session = Depends(get_db),
):
    tenant = db.execute(select(Tenant).where(Tenant.slug == tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
        
    employee = db.execute(
        select(Employee).where(
            Employee.id == employee_id, 
            Employee.tenant_id == tenant.id,
            Employee.is_active == True,
            Employee.is_portfolio_public == True
        )
    ).scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not available")
    
    return [
        PortfolioImageOut(
            id=img.id,
            image_url=img.image_url,
            description=img.description,
            order_weight=img.order_weight,
            created_at=img.created_at
        ) for img in sorted(employee.portfolio, key=lambda x: x.order_weight)
    ]


@public_router.post("/{tenant_slug}/reservations", response_model=PublicReservationOut)
@public_router.post("/reservations", response_model=PublicReservationOut)
def create_public_reservation_endpoint(
    tenant_slug: str,
    payload: PublicReservationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == tenant_slug.strip().lower())
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    try:
        enforce_public_reservation_rate_limit(
            db=db,
            tenant_id=tenant.id,
            client_ip=_client_ip_from_request(request),
            phone=payload.phone,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )

    reservation = create_public_reservation(
        db=db,
        tenant_id=tenant.id,
        requested_dt=payload.requested_dt,
        client_name=payload.client_name,
        service_name=payload.service_name,
        phone=payload.phone,
        note=payload.note,
        idempotency_key=idempotency_key,
    )
    enqueue_outbox_event(
        db=db,
        tenant_id=tenant.id,
        topic="reservation.created_public",
        key=f"reservation:{reservation.id}",
        payload={
            "reservation_id": reservation.id,
            "tenant_slug": tenant.slug,
            "status": reservation.status,
            "service_name": reservation.service_name,
        },
    )
    return _to_reservation_out(tenant.slug, reservation)
