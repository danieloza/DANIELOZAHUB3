import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Client,
    ClientNote,
    Employee,
    EmployeeAvailabilityDay,
    EmployeeBlock,
    EmployeeBuffer,
    EmployeeLeaveRequest,
    EmployeeServiceCapability,
    EmployeeWeeklySchedule,
    ReservationRateLimitEvent,
    ReservationRequest,
    ReservationStatusEvent,
    ScheduleAuditEvent,
    ScheduleNotification,
    Service,
    ServiceBuffer,
    ShiftSwapRequest,
    Tenant,
    TimeClockEntry,
    Visit,
    VisitStatusEvent,
    OutboxEvent,
    VisitInvoice,
)

RESERVATION_STATUSES = {"new", "contacted", "confirmed", "rejected"}
ALLOWED_STATUS_TRANSITIONS = {
    "new": {"contacted"},
    "contacted": {"confirmed", "rejected"},
    "confirmed": set(),
    "rejected": set(),
}

VISIT_STATUSES = {
    "planned",
    "confirmed",
    "arrived",
    "in_service",
    "done",
    "no_show",
    "canceled",
}
ALLOWED_VISIT_STATUS_TRANSITIONS = {
    "planned": {"confirmed", "arrived", "canceled", "no_show"},
    "confirmed": {"arrived", "canceled", "no_show"},
    "arrived": {"in_service", "canceled"},
    "in_service": {"done", "canceled"},
    "done": set(),
    "no_show": {"confirmed", "canceled"},
    "canceled": {"planned", "confirmed"},
}

DEFAULT_EMPLOYEE_HOURS = {
    "Magda": (8, 18),
    "Kamila": (10, 19),
    "Taja": (8, 16),
}
DEFAULT_WEEKDAY_OVERRIDES = {
    "Magda": {5: (9, 14), 6: None},
    "Kamila": {5: (10, 15), 6: None},
    "Taja": {5: (8, 13), 6: None},
}
DEFAULT_SERVICE_DURATIONS = {
    "Strzyżenie": 30,
    "Koloryzacja": 120,
    "Tonowanie": 60,
    "Modelowanie": 45,
    "Inna": 30,
}


_REFERENCE_MONDAY = date(2026, 1, 5)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    return a_start < b_end and b_start < a_end


def _normalize_hours(start: int | None, end: int | None) -> tuple[int, int]:
    start_h = int(start or 9)
    end_h = int(end or 18)
    if end_h <= start_h:
        return 9, 18
    return start_h, end_h


def _default_employee_hours(employee_name: str, day: date) -> tuple[int, int] | None:
    base = DEFAULT_EMPLOYEE_HOURS.get(employee_name) or (9, 18)
    overrides = DEFAULT_WEEKDAY_OVERRIDES.get(employee_name) or {}
    if day.weekday() in overrides:
        rule = overrides[day.weekday()]
        if rule is None:
            return None
        return _normalize_hours(rule[0], rule[1])
    return _normalize_hours(base[0], base[1])


def _default_duration_for_service(service_name: str, fallback: int = 30) -> int:
    return int(DEFAULT_SERVICE_DURATIONS.get(service_name, fallback))


def get_or_create_tenant(db: Session, slug: str, name: str | None = None) -> Tenant:
    normalized_slug = slug.strip().lower()
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == normalized_slug)
    ).scalar_one_or_none()
    if tenant:
        return tenant

    tenant = Tenant(slug=normalized_slug, name=(name or normalized_slug).strip())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def get_or_create_client(
    db: Session, tenant_id: int, name: str, phone: str | None = None
) -> Client:
    normalized_name = name.strip()
    normalized_phone = (phone or "").strip() or None
    obj = db.execute(
        select(Client).where(
            Client.tenant_id == tenant_id, Client.name == normalized_name
        )
    ).scalar_one_or_none()
    if obj:
        if normalized_phone and obj.phone != normalized_phone:
            obj.phone = normalized_phone
            db.commit()
            db.refresh(obj)
        return obj
    obj = Client(tenant_id=tenant_id, name=normalized_name, phone=normalized_phone)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _normalize_employee_name(name: str) -> str:
    return (name or "").strip()


def _sample_day_for_weekday(weekday: int) -> date:
    return _REFERENCE_MONDAY + timedelta(days=int(weekday))


def get_employee_by_id(
    db: Session, tenant_id: int, employee_id: int
) -> Employee | None:
    return db.execute(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.id == employee_id,
        )
    ).scalar_one_or_none()


def get_employee_by_name(
    db: Session, tenant_id: int, employee_name: str
) -> Employee | None:
    normalized_name = _normalize_employee_name(employee_name)
    if not normalized_name:
        return None
    return db.execute(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.name == normalized_name,
        )
    ).scalar_one_or_none()


def _get_employee_capability(
    db: Session,
    tenant_id: int,
    employee_name: str,
    service_name: str,
) -> tuple[Employee | None, EmployeeServiceCapability | None]:
    employee = get_employee_by_name(db, tenant_id, employee_name)
    if employee is None:
        return None, None

    rows = (
        db.execute(
            select(EmployeeServiceCapability).where(
                EmployeeServiceCapability.tenant_id == tenant_id,
                EmployeeServiceCapability.employee_id == employee.id,
                EmployeeServiceCapability.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return employee, None

    target = (service_name or "").strip().lower()
    for row in rows:
        if str(row.service_name or "").strip().lower() == target:
            return employee, row
    return employee, None


def _employee_has_any_active_capability(
    db: Session, tenant_id: int, employee_id: int
) -> bool:
    count = db.execute(
        select(func.count(EmployeeServiceCapability.id)).where(
            EmployeeServiceCapability.tenant_id == tenant_id,
            EmployeeServiceCapability.employee_id == employee_id,
            EmployeeServiceCapability.is_active.is_(True),
        )
    ).scalar_one()
    return int(count or 0) > 0


def _is_employee_on_approved_leave(
    db: Session, tenant_id: int, employee_id: int, day: date
) -> bool:
    row = db.execute(
        select(EmployeeLeaveRequest.id).where(
            EmployeeLeaveRequest.tenant_id == tenant_id,
            EmployeeLeaveRequest.employee_id == employee_id,
            EmployeeLeaveRequest.status == "approved",
            EmployeeLeaveRequest.start_day <= day,
            EmployeeLeaveRequest.end_day >= day,
        )
    ).first()
    return row is not None


def list_team_employees(
    db: Session, tenant_id: int, include_inactive: bool = False, q: str | None = None
) -> list[Employee]:
    query = db.query(Employee).filter(Employee.tenant_id == tenant_id)
    if not include_inactive:
        query = query.filter(Employee.is_active.is_(True))
    if q:
        query = query.filter(Employee.name.ilike(f"%{q.strip()}%"))
    return query.order_by(Employee.name.asc(), Employee.id.asc()).all()


def create_team_employee(
    db: Session,
    tenant_id: int,
    name: str,
    commission_pct: float = 0.0,
) -> Employee:
    normalized_name = _normalize_employee_name(name)
    if not normalized_name:
        raise ValueError("Employee name is required")

    existing = get_employee_by_name(db, tenant_id, normalized_name)
    if existing:
        if existing.is_active:
            raise ValueError("Employee already exists")
        existing.is_active = True
        existing.commission_pct = max(0.0, float(commission_pct))
        db.commit()
        db.refresh(existing)
        return existing

    row = Employee(
        tenant_id=tenant_id,
        name=normalized_name,
        commission_pct=max(0.0, float(commission_pct)),
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_team_employee(
    db: Session,
    tenant_id: int,
    employee_id: int,
    *,
    name: str | None = None,
    commission_pct: float | None = None,
    is_active: bool | None = None,
    is_portfolio_public: bool | None = None,
) -> Employee | None:
    row = get_employee_by_id(db, tenant_id, employee_id)
    if row is None:
        return None

    if name is not None:
        normalized_name = _normalize_employee_name(name)
        if not normalized_name:
            raise ValueError("Employee name is required")
        if normalized_name != row.name:
            duplicate = get_employee_by_name(db, tenant_id, normalized_name)
            if duplicate and duplicate.id != row.id:
                raise ValueError("Employee name already exists")
            row.name = normalized_name

    if commission_pct is not None:
        row.commission_pct = max(0.0, float(commission_pct))
    if is_active is not None:
        row.is_active = bool(is_active)
    if is_portfolio_public is not None:
        row.is_portfolio_public = bool(is_portfolio_public)

    db.commit()
    db.refresh(row)
    return row


def archive_team_employee(
    db: Session, tenant_id: int, employee_id: int
) -> Employee | None:
    row = get_employee_by_id(db, tenant_id, employee_id)
    if row is None:
        return None
    if row.is_active:
        row.is_active = False
        db.commit()
        db.refresh(row)
    return row


def list_employee_weekly_schedule(
    db: Session,
    tenant_id: int,
    employee_id: int,
) -> list[dict] | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None

    rows = (
        db.execute(
            select(EmployeeWeeklySchedule).where(
                EmployeeWeeklySchedule.tenant_id == tenant_id,
                EmployeeWeeklySchedule.employee_id == employee_id,
            )
        )
        .scalars()
        .all()
    )
    by_weekday = {int(r.weekday): r for r in rows}

    out: list[dict] = []
    for weekday in range(7):
        rule = by_weekday.get(weekday)
        if rule:
            if rule.is_day_off:
                out.append(
                    {
                        "weekday": weekday,
                        "is_day_off": True,
                        "start_hour": None,
                        "end_hour": None,
                        "source": "weekly",
                    }
                )
                continue
            start_hour, end_hour = _normalize_hours(rule.start_hour, rule.end_hour)
            out.append(
                {
                    "weekday": weekday,
                    "is_day_off": False,
                    "start_hour": int(start_hour),
                    "end_hour": int(end_hour),
                    "source": "weekly",
                }
            )
            continue

        default_hours = _default_employee_hours(
            employee.name, _sample_day_for_weekday(weekday)
        )
        if default_hours is None:
            out.append(
                {
                    "weekday": weekday,
                    "is_day_off": True,
                    "start_hour": None,
                    "end_hour": None,
                    "source": "default",
                }
            )
        else:
            out.append(
                {
                    "weekday": weekday,
                    "is_day_off": False,
                    "start_hour": int(default_hours[0]),
                    "end_hour": int(default_hours[1]),
                    "source": "default",
                }
            )
    return out


def set_employee_weekly_schedule(
    db: Session,
    tenant_id: int,
    employee_id: int,
    days: list[dict],
) -> list[dict] | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None

    for item in days:
        weekday = int(item.get("weekday"))
        row = db.execute(
            select(EmployeeWeeklySchedule).where(
                EmployeeWeeklySchedule.tenant_id == tenant_id,
                EmployeeWeeklySchedule.employee_id == employee_id,
                EmployeeWeeklySchedule.weekday == weekday,
            )
        ).scalar_one_or_none()
        if row is None:
            row = EmployeeWeeklySchedule(
                tenant_id=tenant_id,
                employee_id=employee_id,
                weekday=weekday,
            )
            db.add(row)

        is_day_off = bool(item.get("is_day_off"))
        row.is_day_off = is_day_off
        if is_day_off:
            row.start_hour = None
            row.end_hour = None
        else:
            start_hour = item.get("start_hour")
            end_hour = item.get("end_hour")
            if start_hour is None or end_hour is None:
                start_hour, end_hour = 9, 18
            start_hour, end_hour = _normalize_hours(int(start_hour), int(end_hour))
            row.start_hour = int(start_hour)
            row.end_hour = int(end_hour)

    db.commit()
    return list_employee_weekly_schedule(db, tenant_id, employee_id)


def get_or_create_employee(db: Session, tenant_id: int, name: str) -> Employee:
    normalized_name = _normalize_employee_name(name)
    obj = db.execute(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.name == normalized_name,
        )
    ).scalar_one_or_none()
    if obj:
        if not bool(obj.is_active):
            raise ValueError("Employee is archived")
        return obj
    obj = Employee(
        tenant_id=tenant_id, name=normalized_name, commission_pct=0, is_active=True
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_or_create_service(
    db: Session, tenant_id: int, name: str, default_price: float = 0
) -> Service:
    obj = db.execute(
        select(Service).where(Service.tenant_id == tenant_id, Service.name == name)
    ).scalar_one_or_none()
    if obj:
        return obj
    obj = Service(tenant_id=tenant_id, name=name, default_price=default_price)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_effective_buffers(
    db: Session,
    tenant_id: int,
    employee_name: str,
    service_name: str,
) -> tuple[int, int]:
    from .enterprise import get_slot_buffer_multiplier

    service = db.execute(
        select(ServiceBuffer).where(
            ServiceBuffer.tenant_id == tenant_id,
            ServiceBuffer.service_name == service_name.strip(),
        )
    ).scalar_one_or_none()
    employee = db.execute(
        select(EmployeeBuffer).where(
            EmployeeBuffer.tenant_id == tenant_id,
            EmployeeBuffer.employee_name == employee_name.strip(),
        )
    ).scalar_one_or_none()
    multiplier = float(get_slot_buffer_multiplier(db, tenant_id))
    before = int(
        round(
            (
                (service.before_min if service else 0)
                + (employee.before_min if employee else 0)
            )
            * multiplier
        )
    )
    after = int(
        round(
            (
                (service.after_min if service else 0)
                + (employee.after_min if employee else 0)
            )
            * multiplier
        )
    )
    return max(before, 0), max(after, 0)


def get_employee_hours(
    db: Session, tenant_id: int, employee_name: str, day: date
) -> tuple[int, int] | None:
    normalized_name = employee_name.strip()
    employee = get_employee_by_name(db, tenant_id, normalized_name)
    if employee and not bool(employee.is_active):
        return None
    if employee and _is_employee_on_approved_leave(db, tenant_id, employee.id, day):
        return None

    row = db.execute(
        select(EmployeeAvailabilityDay).where(
            EmployeeAvailabilityDay.tenant_id == tenant_id,
            EmployeeAvailabilityDay.employee_name == normalized_name,
            EmployeeAvailabilityDay.day == day,
        )
    ).scalar_one_or_none()
    if row:
        if row.is_day_off:
            return None
        if row.start_hour is None or row.end_hour is None:
            weekly = db.execute(
                select(EmployeeWeeklySchedule)
                .join(Employee, Employee.id == EmployeeWeeklySchedule.employee_id)
                .where(
                    EmployeeWeeklySchedule.tenant_id == tenant_id,
                    Employee.name == normalized_name,
                    EmployeeWeeklySchedule.weekday == day.weekday(),
                )
            ).scalar_one_or_none()
            if weekly and weekly.is_day_off:
                return None
            if weekly and weekly.start_hour is not None and weekly.end_hour is not None:
                return _normalize_hours(weekly.start_hour, weekly.end_hour)
            return _default_employee_hours(normalized_name, day)
        return _normalize_hours(row.start_hour, row.end_hour)

    weekly = db.execute(
        select(EmployeeWeeklySchedule)
        .join(Employee, Employee.id == EmployeeWeeklySchedule.employee_id)
        .where(
            EmployeeWeeklySchedule.tenant_id == tenant_id,
            Employee.name == normalized_name,
            EmployeeWeeklySchedule.weekday == day.weekday(),
        )
    ).scalar_one_or_none()
    if weekly:
        if weekly.is_day_off:
            return None
        if weekly.start_hour is None or weekly.end_hour is None:
            return _default_employee_hours(normalized_name, day)
        return _normalize_hours(weekly.start_hour, weekly.end_hour)
    return _default_employee_hours(normalized_name, day)


def list_employee_blocks_in_range(
    db: Session,
    tenant_id: int,
    employee_name: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[EmployeeBlock]:
    stmt = (
        select(EmployeeBlock)
        .where(
            EmployeeBlock.tenant_id == tenant_id,
            EmployeeBlock.employee_name == employee_name.strip(),
            EmployeeBlock.start_dt < end_dt,
            EmployeeBlock.end_dt > start_dt,
        )
        .order_by(EmployeeBlock.start_dt.asc())
    )
    return db.execute(stmt).scalars().all()


def _candidate_window(
    dt: datetime,
    duration_min: int,
    before_min: int,
    after_min: int,
) -> tuple[datetime, datetime]:
    start = to_utc_naive(dt) - timedelta(minutes=before_min)
    end = to_utc_naive(dt) + timedelta(minutes=duration_min + after_min)
    return start, end


def _visit_busy_window(
    db: Session, tenant_id: int, visit: Visit
) -> tuple[datetime, datetime]:
    emp_name = visit.employee.name
    svc_name = visit.service.name
    before, after = get_effective_buffers(db, tenant_id, emp_name, svc_name)
    return _candidate_window(visit.dt, int(visit.duration_min or 30), before, after)


def check_visit_slot_available(
    db: Session,
    tenant_id: int,
    employee_name: str,
    service_name: str,
    dt: datetime,
    duration_min: int,
    skip_visit_id: int | None = None,
) -> tuple[bool, str | None]:
    candidate_dt = to_utc_naive(dt)
    day = candidate_dt.date()
    hours = get_employee_hours(db, tenant_id, employee_name, day)
    if not hours:
        return False, f"{employee_name} is unavailable on this day"

    before_min, after_min = get_effective_buffers(
        db, tenant_id, employee_name, service_name
    )
    candidate_start, candidate_end = _candidate_window(
        candidate_dt, duration_min, before_min, after_min
    )
    if candidate_start.date() != day or candidate_end.date() != day:
        return False, "Slot with buffers must fit within one day"

    work_start_h, work_end_h = hours
    work_start = work_start_h * 60
    work_end = work_end_h * 60
    slot_start = (candidate_start.hour * 60) + candidate_start.minute
    slot_end = (candidate_end.hour * 60) + candidate_end.minute
    if slot_start < work_start or slot_end > work_end:
        return False, "Slot exceeds employee working hours"

    blocks = list_employee_blocks_in_range(
        db, tenant_id, employee_name, candidate_start, candidate_end
    )
    if blocks:
        return False, "Slot overlaps employee block"

    window_start = datetime.combine(day, time.min) - timedelta(days=1)
    window_end = datetime.combine(day, time.max) + timedelta(days=1)
    visits = (
        db.query(Visit)
        .join(Visit.employee)
        .join(Visit.service)
        .filter(
            Visit.tenant_id == tenant_id,
            Employee.name == employee_name.strip(),
            Visit.dt >= window_start,
            Visit.dt <= window_end,
        )
        .all()
    )
    for existing in visits:
        if skip_visit_id and existing.id == skip_visit_id:
            continue
        existing_start, existing_end = _visit_busy_window(db, tenant_id, existing)
        if overlaps(candidate_start, candidate_end, existing_start, existing_end):
            return False, f"Slot overlaps existing visit #{existing.id}"
    return True, None


def add_visit_status_event(
    db: Session,
    tenant_id: int,
    visit_id: int,
    from_status: str | None,
    to_status: str,
    actor: str | None = None,
    note: str | None = None,
) -> VisitStatusEvent:
    event = VisitStatusEvent(
        tenant_id=tenant_id,
        visit_id=visit_id,
        from_status=from_status,
        to_status=to_status,
        actor=(actor or "").strip() or None,
        note=(note or "").strip() or None,
        created_at=utc_now_naive(),
    )
    db.add(event)
    db.flush()
    return event


def create_visit(
    db: Session,
    tenant_id: int,
    dt: datetime,
    client_name: str,
    employee_name: str,
    service_name: str,
    price: float,
    duration_min: int | None = None,
    status: str = "planned",
    client_phone: str | None = None,
    source_reservation_id: int | None = None,
) -> Visit:
    normalized_status = (status or "planned").strip().lower()
    if normalized_status not in VISIT_STATUSES:
        raise ValueError("Invalid visit status")

    normalized_employee = employee_name.strip()
    normalized_service = service_name.strip()
    employee_row, capability = _get_employee_capability(
        db=db,
        tenant_id=tenant_id,
        employee_name=normalized_employee,
        service_name=normalized_service,
    )
    if (
        employee_row
        and _employee_has_any_active_capability(db, tenant_id, employee_row.id)
        and capability is None
    ):
        raise ValueError("Employee is not assigned to this service")

    resolved_duration = int(
        duration_min
        or (
            int(capability.duration_min)
            if capability and capability.duration_min
            else _default_duration_for_service(normalized_service)
        )
    )
    if resolved_duration <= 0:
        raise ValueError("duration_min must be > 0")

    ok, reason = check_visit_slot_available(
        db=db,
        tenant_id=tenant_id,
        employee_name=normalized_employee,
        service_name=normalized_service,
        dt=dt,
        duration_min=resolved_duration,
    )
    if not ok:
        raise ValueError(reason or "Slot unavailable")

    client = get_or_create_client(
        db, tenant_id, client_name.strip(), phone=client_phone
    )
    employee = employee_row or get_or_create_employee(
        db, tenant_id, normalized_employee
    )
    service = get_or_create_service(db, tenant_id, normalized_service)
    resolved_price = (
        float(capability.price_override)
        if capability and capability.price_override is not None
        else float(price)
    )

    visit = Visit(
        tenant_id=tenant_id,
        dt=to_utc_naive(dt),
        client_id=client.id,
        employee_id=employee.id,
        service_id=service.id,
        source_reservation_id=source_reservation_id,
        price=resolved_price,
        duration_min=resolved_duration,
        status=normalized_status,
    )
    db.add(visit)
    db.flush()
    add_visit_status_event(
        db=db,
        tenant_id=tenant_id,
        visit_id=visit.id,
        from_status=None,
        to_status=normalized_status,
        note="created",
    )
    try:
        db.commit()
        db.refresh(visit)
        return visit
    except IntegrityError:
        db.rollback()
        if source_reservation_id is None:
            raise
        existing = db.execute(
            select(Visit).where(
                Visit.tenant_id == tenant_id,
                Visit.source_reservation_id == source_reservation_id,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        raise


def add_reservation_status_event(
    db: Session,
    tenant_id: int,
    reservation_id: int,
    from_status: str | None,
    to_status: str,
    action: str,
    actor: str | None = None,
    note: str | None = None,
) -> ReservationStatusEvent:
    event = ReservationStatusEvent(
        tenant_id=tenant_id,
        reservation_id=reservation_id,
        from_status=from_status,
        to_status=to_status,
        action=action,
        actor=(actor or "").strip() or None,
        note=(note or "").strip() or None,
        created_at=utc_now_naive(),
    )
    db.add(event)
    db.flush()
    return event


def _normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = "".join(ch for ch in str(phone).strip() if ch.isdigit() or ch == "+")
    return cleaned or None


def _cleanup_rate_limit_events(db: Session) -> None:
    retention_hours = max(1, int(settings.PUBLIC_RL_EVENT_RETENTION_HOURS))
    cutoff = utc_now_naive() - timedelta(hours=retention_hours)
    db.execute(
        delete(ReservationRateLimitEvent).where(
            ReservationRateLimitEvent.created_at < cutoff,
        )
    )
    db.commit()


def enforce_public_reservation_rate_limit(
    db: Session,
    tenant_id: int,
    client_ip: str | None,
    phone: str | None = None,
) -> None:
    ip = (client_ip or "").strip()[:64] or None
    normalized_phone = _normalize_phone(phone)

    _cleanup_rate_limit_events(db)

    now = utc_now_naive()
    minute_ago = now - timedelta(minutes=1)
    hour_ago = now - timedelta(hours=1)

    if ip:
        ip_min = db.execute(
            select(func.count(ReservationRateLimitEvent.id)).where(
                ReservationRateLimitEvent.tenant_id == tenant_id,
                ReservationRateLimitEvent.client_ip == ip,
                ReservationRateLimitEvent.created_at >= minute_ago,
            )
        ).scalar_one()
        if int(ip_min) >= int(settings.PUBLIC_RL_IP_PER_MIN):
            raise ValueError("Rate limit exceeded for IP (minute window)")

        ip_hour = db.execute(
            select(func.count(ReservationRateLimitEvent.id)).where(
                ReservationRateLimitEvent.tenant_id == tenant_id,
                ReservationRateLimitEvent.client_ip == ip,
                ReservationRateLimitEvent.created_at >= hour_ago,
            )
        ).scalar_one()
        if int(ip_hour) >= int(settings.PUBLIC_RL_IP_PER_HOUR):
            raise ValueError("Rate limit exceeded for IP (hour window)")

    if normalized_phone:
        phone_min = db.execute(
            select(func.count(ReservationRateLimitEvent.id)).where(
                ReservationRateLimitEvent.tenant_id == tenant_id,
                ReservationRateLimitEvent.phone == normalized_phone,
                ReservationRateLimitEvent.created_at >= minute_ago,
            )
        ).scalar_one()
        if int(phone_min) >= int(settings.PUBLIC_RL_PHONE_PER_MIN):
            raise ValueError("Rate limit exceeded for phone (minute window)")

        phone_hour = db.execute(
            select(func.count(ReservationRateLimitEvent.id)).where(
                ReservationRateLimitEvent.tenant_id == tenant_id,
                ReservationRateLimitEvent.phone == normalized_phone,
                ReservationRateLimitEvent.created_at >= hour_ago,
            )
        ).scalar_one()
        if int(phone_hour) >= int(settings.PUBLIC_RL_PHONE_PER_HOUR):
            raise ValueError("Rate limit exceeded for phone (hour window)")

    db.add(
        ReservationRateLimitEvent(
            tenant_id=tenant_id,
            created_at=now,
            client_ip=ip,
            phone=normalized_phone,
        )
    )
    db.commit()


def create_public_reservation(
    db: Session,
    tenant_id: int,
    requested_dt: datetime,
    client_name: str,
    service_name: str,
    phone: str | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> ReservationRequest:
    normalized_idempotency = (idempotency_key or "").strip() or None
    if normalized_idempotency:
        existing = db.execute(
            select(ReservationRequest).where(
                ReservationRequest.tenant_id == tenant_id,
                ReservationRequest.idempotency_key == normalized_idempotency,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    reservation = ReservationRequest(
        tenant_id=tenant_id,
        requested_dt=to_utc_naive(requested_dt),
        client_name=client_name.strip(),
        phone=(phone or "").strip() or None,
        service_name=service_name.strip(),
        note=(note or "").strip() or None,
        status="new",
        idempotency_key=normalized_idempotency,
    )
    db.add(reservation)
    try:
        db.flush()
        add_reservation_status_event(
            db=db,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            from_status=None,
            to_status="new",
            action="created",
        )
        db.commit()
        db.refresh(reservation)
        return reservation
    except IntegrityError:
        db.rollback()
        if not normalized_idempotency:
            raise
        existing = db.execute(
            select(ReservationRequest).where(
                ReservationRequest.tenant_id == tenant_id,
                ReservationRequest.idempotency_key == normalized_idempotency,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        raise


def update_visit(
    db: Session,
    tenant_id: int,
    visit_id: int,
    dt: datetime | None = None,
    duration_min: int | None = None,
) -> Visit | None:
    visit = db.execute(
        select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not visit:
        return None

    target_dt = to_utc_naive(dt) if dt else visit.dt
    target_duration = (
        int(duration_min) if duration_min is not None else int(visit.duration_min or 30)
    )
    if target_duration <= 0:
        raise ValueError("duration_min must be > 0")

    ok, reason = check_visit_slot_available(
        db=db,
        tenant_id=tenant_id,
        employee_name=visit.employee.name,
        service_name=visit.service.name,
        dt=target_dt,
        duration_min=target_duration,
        skip_visit_id=visit.id,
    )
    if not ok:
        raise ValueError(reason or "Slot unavailable")

    visit.dt = target_dt
    visit.duration_min = target_duration
    db.commit()
    db.refresh(visit)
    return visit


def update_visit_datetime(
    db: Session, tenant_id: int, visit_id: int, dt: datetime
) -> Visit | None:
    return update_visit(db=db, tenant_id=tenant_id, visit_id=visit_id, dt=dt)


def update_visit_status(
    db: Session,
    tenant_id: int,
    visit_id: int,
    new_status: str,
    actor: str | None = None,
    note: str | None = None,
) -> Visit | None:
    from .enterprise import DEFAULT_VISIT_STATUS_POLICY, get_policy_status_config

    visit = db.execute(
        select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not visit:
        return None

    fallback_statuses = {
        str(x).strip().lower() for x in DEFAULT_VISIT_STATUS_POLICY["statuses"]
    }
    fallback_transitions = {
        str(k).strip().lower(): {str(v).strip().lower() for v in vals}
        for k, vals in DEFAULT_VISIT_STATUS_POLICY["transitions"].items()
    }
    policy_statuses, policy_transitions = get_policy_status_config(
        db, tenant_id, "visit_status_policy"
    )
    active_statuses = policy_statuses or fallback_statuses
    active_transitions = policy_transitions or fallback_transitions

    target_status = (new_status or "").strip().lower()
    if target_status not in active_statuses:
        raise ValueError("Invalid visit status")

    current_status = (visit.status or "planned").strip().lower()
    if target_status == current_status:
        return visit

    allowed = active_transitions.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Invalid visit status transition: {current_status} -> {target_status}"
        )

    visit.status = target_status
    add_visit_status_event(
        db=db,
        tenant_id=tenant_id,
        visit_id=visit.id,
        from_status=current_status,
        to_status=target_status,
        actor=actor,
        note=note,
    )

    if target_status == "completed":
        # Senior IT: Invoicing Sync Automation
        existing_invoice = db.execute(
            select(VisitInvoice).where(VisitInvoice.visit_id == visit.id)
        ).scalar_one_or_none()
        
        if not existing_invoice:
            db.add(VisitInvoice(tenant_id=tenant_id, visit_id=visit.id, status="pending"))
            db.add(OutboxEvent(
                tenant_id=tenant_id,
                topic="invoice.create_requested",
                key=f"visit_{visit.id}",
                payload_json=json.dumps({
                    "visit_id": visit.id,
                    "client_name": visit.client.name if visit.client else "Unknown",
                    "service_name": visit.service.name if visit.service else "Service",
                    "amount": float(visit.price or 0),
                    "date": visit.dt.isoformat() if visit.dt else datetime.now().isoformat()
                })
            ))

    db.commit()
    db.refresh(visit)
    return visit


def list_visit_status_events(
    db: Session, tenant_id: int, visit_id: int
) -> list[VisitStatusEvent]:
    stmt = (
        select(VisitStatusEvent)
        .where(
            VisitStatusEvent.tenant_id == tenant_id,
            VisitStatusEvent.visit_id == visit_id,
        )
        .order_by(VisitStatusEvent.created_at.asc(), VisitStatusEvent.id.asc())
    )
    return db.execute(stmt).scalars().all()


def day_summary(db: Session, tenant_id: int, day: date):
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day, datetime.max.time())
    total = db.execute(
        select(func.coalesce(func.sum(Visit.price), 0)).where(
            Visit.tenant_id == tenant_id,
            Visit.dt.between(start, end),
        )
    ).scalar_one()
    count = db.execute(
        select(func.count(Visit.id)).where(
            Visit.tenant_id == tenant_id,
            Visit.dt.between(start, end),
        )
    ).scalar_one()
    return float(total), int(count)


def month_report(db: Session, tenant_id: int, year: int, month: int):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    total = db.execute(
        select(func.coalesce(func.sum(Visit.price), 0)).where(
            Visit.tenant_id == tenant_id,
            Visit.dt >= start,
            Visit.dt < end,
        )
    ).scalar_one()
    count = db.execute(
        select(func.count(Visit.id)).where(
            Visit.tenant_id == tenant_id,
            Visit.dt >= start,
            Visit.dt < end,
        )
    ).scalar_one()

    rows = db.execute(
        select(
            Employee.name,
            Employee.commission_pct,
            func.coalesce(func.sum(Visit.price), 0),
        )
        .join(Visit, Visit.employee_id == Employee.id)
        .where(
            Visit.tenant_id == tenant_id,
            Visit.dt >= start,
            Visit.dt < end,
            Employee.tenant_id == tenant_id,
        )
        .group_by(Employee.id)
        .order_by(Employee.name.asc())
    ).all()

    by_emp = []
    for name, pct, revenue in rows:
        revenue = float(revenue)
        pct = float(pct)
        commission_amount = round(revenue * (pct / 100.0), 2)
        by_emp.append((name, pct, revenue, commission_amount))

    return float(total), int(count), by_emp


def delete_visit(db: Session, tenant_id: int, visit_id: int) -> bool:
    visit = db.execute(
        select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not visit:
        return False
    db.delete(visit)
    db.commit()
    return True


def list_public_reservations(
    db: Session,
    tenant_id: int,
    status_filter: str | None = None,
    limit: int = 100,
) -> list[ReservationRequest]:
    stmt = select(ReservationRequest).where(ReservationRequest.tenant_id == tenant_id)
    if status_filter:
        stmt = stmt.where(ReservationRequest.status == status_filter.strip().lower())
    stmt = stmt.order_by(ReservationRequest.created_at.desc()).limit(
        max(1, min(limit, 500))
    )
    return db.execute(stmt).scalars().all()


def get_reservation_by_id(
    db: Session, tenant_id: int, reservation_id: int
) -> ReservationRequest | None:
    return db.execute(
        select(ReservationRequest).where(
            ReservationRequest.id == reservation_id,
            ReservationRequest.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()


def update_reservation_status(
    db: Session,
    tenant_id: int,
    reservation_id: int,
    new_status: str,
    actor: str | None = None,
) -> ReservationRequest | None:
    from .enterprise import DEFAULT_RESERVATION_STATUS_POLICY, get_policy_status_config

    reservation = get_reservation_by_id(db, tenant_id, reservation_id)
    if not reservation:
        return None

    fallback_statuses = {
        str(x).strip().lower() for x in DEFAULT_RESERVATION_STATUS_POLICY["statuses"]
    }
    fallback_transitions = {
        str(k).strip().lower(): {str(v).strip().lower() for v in vals}
        for k, vals in DEFAULT_RESERVATION_STATUS_POLICY["transitions"].items()
    }
    policy_statuses, policy_transitions = get_policy_status_config(
        db, tenant_id, "reservation_status_policy"
    )
    active_statuses = policy_statuses or fallback_statuses
    active_transitions = policy_transitions or fallback_transitions

    target_status = new_status.strip().lower()
    if target_status not in active_statuses:
        raise ValueError("Invalid reservation status")

    current_status = reservation.status.strip().lower()
    if target_status == current_status:
        return reservation

    if reservation.converted_visit_id and target_status != "confirmed":
        raise ValueError("Converted reservation can only stay confirmed")

    allowed_next = active_transitions.get(current_status, set())
    if target_status not in allowed_next:
        raise ValueError(
            f"Invalid status transition: {current_status} -> {target_status}"
        )

    reservation.status = target_status
    add_reservation_status_event(
        db=db,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
        from_status=current_status,
        to_status=target_status,
        action="status_update",
        actor=actor,
    )
    db.commit()
    db.refresh(reservation)
    return reservation


def _get_visit_by_source_reservation_id(
    db: Session, tenant_id: int, reservation_id: int
) -> Visit | None:
    return db.execute(
        select(Visit).where(
            Visit.tenant_id == tenant_id,
            Visit.source_reservation_id == reservation_id,
        )
    ).scalar_one_or_none()


def _link_reservation_to_visit(
    db: Session,
    reservation: ReservationRequest,
    visit: Visit,
    actor: str | None = None,
) -> ReservationRequest:
    previous_status = (reservation.status or "").strip().lower() or "new"
    previous_visit_id = reservation.converted_visit_id

    reservation.status = "confirmed"
    reservation.converted_visit_id = visit.id
    reservation.converted_at = reservation.converted_at or utc_now_naive()

    if previous_status != "confirmed" or previous_visit_id != visit.id:
        add_reservation_status_event(
            db=db,
            tenant_id=reservation.tenant_id,
            reservation_id=reservation.id,
            from_status=previous_status,
            to_status="confirmed",
            action="converted_to_visit",
            actor=actor,
            note=f"visit_id={visit.id}",
        )

    db.commit()
    db.refresh(reservation)
    return reservation


def convert_reservation_to_visit(
    db: Session,
    tenant_id: int,
    reservation_id: int,
    employee_name: str,
    price: float,
    dt: datetime | None = None,
    client_name: str | None = None,
    service_name: str | None = None,
    actor: str | None = None,
) -> tuple[ReservationRequest | None, Visit | None]:
    reservation = get_reservation_by_id(db, tenant_id, reservation_id)
    if not reservation:
        return None, None

    by_source = _get_visit_by_source_reservation_id(db, tenant_id, reservation.id)
    if by_source:
        return _link_reservation_to_visit(
            db, reservation, by_source, actor=actor
        ), by_source

    if reservation.converted_visit_id:
        existing_visit = db.execute(
            select(Visit).where(
                Visit.id == reservation.converted_visit_id,
                Visit.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if existing_visit:
            return reservation, existing_visit

    if reservation.status == "rejected":
        raise ValueError("Reservation is rejected and cannot be converted")

    visit = create_visit(
        db=db,
        tenant_id=tenant_id,
        dt=dt or reservation.requested_dt,
        client_name=(client_name or reservation.client_name).strip(),
        client_phone=reservation.phone,
        employee_name=employee_name.strip(),
        service_name=(service_name or reservation.service_name).strip(),
        price=price,
        source_reservation_id=reservation.id,
    )
    return _link_reservation_to_visit(db, reservation, visit, actor=actor), visit


def list_reservation_status_events(
    db: Session, tenant_id: int, reservation_id: int
) -> list[ReservationStatusEvent]:
    stmt = (
        select(ReservationStatusEvent)
        .where(
            ReservationStatusEvent.tenant_id == tenant_id,
            ReservationStatusEvent.reservation_id == reservation_id,
        )
        .order_by(
            ReservationStatusEvent.created_at.asc(), ReservationStatusEvent.id.asc()
        )
    )
    return db.execute(stmt).scalars().all()


def get_reservation_metrics(db: Session, tenant_id: int) -> dict:
    total = db.execute(
        select(func.count(ReservationRequest.id)).where(
            ReservationRequest.tenant_id == tenant_id
        )
    ).scalar_one()

    rows = db.execute(
        select(ReservationRequest.status, func.count(ReservationRequest.id))
        .where(ReservationRequest.tenant_id == tenant_id)
        .group_by(ReservationRequest.status)
    ).all()
    by_status = {status: int(count) for status, count in rows}

    converted = db.execute(
        select(func.count(ReservationRequest.id)).where(
            ReservationRequest.tenant_id == tenant_id,
            ReservationRequest.converted_visit_id.is_not(None),
        )
    ).scalar_one()

    total_int = int(total)
    converted_int = int(converted)
    conversion_rate = round((converted_int / total_int) if total_int else 0.0, 4)

    return {
        "total": total_int,
        "by_status": by_status,
        "converted": converted_int,
        "conversion_rate": conversion_rate,
    }


def upsert_employee_availability_day(
    db: Session,
    tenant_id: int,
    employee_name: str,
    day: date,
    is_day_off: bool,
    start_hour: int | None = None,
    end_hour: int | None = None,
    note: str | None = None,
) -> EmployeeAvailabilityDay:
    normalized_name = employee_name.strip()
    row = db.execute(
        select(EmployeeAvailabilityDay).where(
            EmployeeAvailabilityDay.tenant_id == tenant_id,
            EmployeeAvailabilityDay.employee_name == normalized_name,
            EmployeeAvailabilityDay.day == day,
        )
    ).scalar_one_or_none()
    if row is None:
        row = EmployeeAvailabilityDay(
            tenant_id=tenant_id,
            employee_name=normalized_name,
            day=day,
        )
        db.add(row)

    row.is_day_off = bool(is_day_off)
    row.note = (note or "").strip() or None
    if row.is_day_off:
        row.start_hour = None
        row.end_hour = None
    else:
        if start_hour is None or end_hour is None:
            default_hours = _default_employee_hours(normalized_name, day) or (9, 18)
            start_hour, end_hour = default_hours
        row.start_hour, row.end_hour = _normalize_hours(start_hour, end_hour)

    db.commit()
    db.refresh(row)
    return row


def list_employee_availability(
    db: Session,
    tenant_id: int,
    employee_name: str,
    start_day: date,
    end_day: date,
) -> list[dict]:
    normalized_name = employee_name.strip()
    employee = get_employee_by_name(db, tenant_id, normalized_name)
    rows = (
        db.execute(
            select(EmployeeAvailabilityDay).where(
                EmployeeAvailabilityDay.tenant_id == tenant_id,
                EmployeeAvailabilityDay.employee_name == normalized_name,
                EmployeeAvailabilityDay.day >= start_day,
                EmployeeAvailabilityDay.day <= end_day,
            )
        )
        .scalars()
        .all()
    )
    by_day = {r.day: r for r in rows}

    weekly_rows: dict[int, EmployeeWeeklySchedule] = {}
    if employee:
        weekly = (
            db.execute(
                select(EmployeeWeeklySchedule).where(
                    EmployeeWeeklySchedule.tenant_id == tenant_id,
                    EmployeeWeeklySchedule.employee_id == employee.id,
                )
            )
            .scalars()
            .all()
        )
        weekly_rows = {int(row.weekday): row for row in weekly}

    out: list[dict] = []
    cursor = start_day
    while cursor <= end_day:
        override = by_day.get(cursor)
        if override:
            out.append(
                {
                    "day": cursor,
                    "employee_name": normalized_name,
                    "is_day_off": bool(override.is_day_off),
                    "start_hour": override.start_hour,
                    "end_hour": override.end_hour,
                    "source": "override",
                    "note": override.note,
                }
            )
        else:
            if employee and not bool(employee.is_active):
                out.append(
                    {
                        "day": cursor,
                        "employee_name": normalized_name,
                        "is_day_off": True,
                        "start_hour": None,
                        "end_hour": None,
                        "source": "employee_inactive",
                        "note": None,
                    }
                )
                cursor += timedelta(days=1)
                continue
            weekly = weekly_rows.get(cursor.weekday())
            if weekly:
                if weekly.is_day_off:
                    out.append(
                        {
                            "day": cursor,
                            "employee_name": normalized_name,
                            "is_day_off": True,
                            "start_hour": None,
                            "end_hour": None,
                            "source": "weekly",
                            "note": None,
                        }
                    )
                    cursor += timedelta(days=1)
                    continue
                start_hour, end_hour = _normalize_hours(
                    weekly.start_hour, weekly.end_hour
                )
                out.append(
                    {
                        "day": cursor,
                        "employee_name": normalized_name,
                        "is_day_off": False,
                        "start_hour": int(start_hour),
                        "end_hour": int(end_hour),
                        "source": "weekly",
                        "note": None,
                    }
                )
                cursor += timedelta(days=1)
                continue
            default_hours = _default_employee_hours(normalized_name, cursor)
            if default_hours is None:
                out.append(
                    {
                        "day": cursor,
                        "employee_name": normalized_name,
                        "is_day_off": True,
                        "start_hour": None,
                        "end_hour": None,
                        "source": "default",
                        "note": None,
                    }
                )
            else:
                out.append(
                    {
                        "day": cursor,
                        "employee_name": normalized_name,
                        "is_day_off": False,
                        "start_hour": int(default_hours[0]),
                        "end_hour": int(default_hours[1]),
                        "source": "default",
                        "note": None,
                    }
                )
        cursor += timedelta(days=1)
    return out


def create_employee_block(
    db: Session,
    tenant_id: int,
    employee_name: str,
    start_dt: datetime,
    end_dt: datetime,
    reason: str | None = None,
) -> EmployeeBlock:
    if to_utc_naive(end_dt) <= to_utc_naive(start_dt):
        raise ValueError("end_dt must be after start_dt")
    row = EmployeeBlock(
        tenant_id=tenant_id,
        employee_name=employee_name.strip(),
        start_dt=to_utc_naive(start_dt),
        end_dt=to_utc_naive(end_dt),
        reason=(reason or "").strip() or None,
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_employee_blocks(
    db: Session,
    tenant_id: int,
    employee_name: str,
    start_day: date,
    end_day: date,
) -> list[EmployeeBlock]:
    start_dt = datetime.combine(start_day, time.min)
    end_dt = datetime.combine(end_day, time.max)
    return list_employee_blocks_in_range(db, tenant_id, employee_name, start_dt, end_dt)


def upsert_service_buffer(
    db: Session,
    tenant_id: int,
    service_name: str,
    before_min: int,
    after_min: int,
) -> ServiceBuffer:
    normalized_name = service_name.strip()
    row = db.execute(
        select(ServiceBuffer).where(
            ServiceBuffer.tenant_id == tenant_id,
            ServiceBuffer.service_name == normalized_name,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ServiceBuffer(tenant_id=tenant_id, service_name=normalized_name)
        db.add(row)
    row.before_min = max(0, int(before_min))
    row.after_min = max(0, int(after_min))
    db.commit()
    db.refresh(row)
    return row


def upsert_employee_buffer(
    db: Session,
    tenant_id: int,
    employee_name: str,
    before_min: int,
    after_min: int,
) -> EmployeeBuffer:
    normalized_name = employee_name.strip()
    row = db.execute(
        select(EmployeeBuffer).where(
            EmployeeBuffer.tenant_id == tenant_id,
            EmployeeBuffer.employee_name == normalized_name,
        )
    ).scalar_one_or_none()
    if row is None:
        row = EmployeeBuffer(tenant_id=tenant_id, employee_name=normalized_name)
        db.add(row)
    row.before_min = max(0, int(before_min))
    row.after_min = max(0, int(after_min))
    db.commit()
    db.refresh(row)
    return row


def get_service_buffer(
    db: Session, tenant_id: int, service_name: str
) -> ServiceBuffer | None:
    return db.execute(
        select(ServiceBuffer).where(
            ServiceBuffer.tenant_id == tenant_id,
            ServiceBuffer.service_name == service_name.strip(),
        )
    ).scalar_one_or_none()


def get_employee_buffer(
    db: Session, tenant_id: int, employee_name: str
) -> EmployeeBuffer | None:
    return db.execute(
        select(EmployeeBuffer).where(
            EmployeeBuffer.tenant_id == tenant_id,
            EmployeeBuffer.employee_name == employee_name.strip(),
        )
    ).scalar_one_or_none()


def recommend_slots(
    db: Session,
    tenant_id: int,
    employee_name: str,
    service_name: str,
    day: date,
    duration_min: int | None = None,
    step_min: int = 5,
    limit: int = 8,
) -> list[dict]:
    resolved_duration = int(duration_min or _default_duration_for_service(service_name))
    hours = get_employee_hours(db, tenant_id, employee_name, day)
    if not hours:
        return []

    start_h, end_h = hours
    start_at = datetime.combine(day, time(start_h, 0))
    end_at = datetime.combine(day, time(end_h, 0))
    step = max(5, int(step_min))
    max_items = max(1, min(limit, 50))
    out: list[dict] = []
    cursor = start_at
    while cursor < end_at and len(out) < max_items:
        ok, _ = check_visit_slot_available(
            db=db,
            tenant_id=tenant_id,
            employee_name=employee_name,
            service_name=service_name,
            dt=cursor,
            duration_min=resolved_duration,
        )
        if ok:
            day_start = datetime.combine(day, time.min)
            distance_from_start_h = int((cursor - day_start).total_seconds() // 3600)
            score = round(max(0.0, 100.0 - (distance_from_start_h * 3.5)), 2)
            out.append(
                {
                    "start_dt": cursor,
                    "end_dt": cursor + timedelta(minutes=resolved_duration),
                    "employee_name": employee_name.strip(),
                    "service_name": service_name.strip(),
                    "score": score,
                }
            )
        cursor += timedelta(minutes=step)
    return out


def search_clients(
    db: Session, tenant_id: int, query: str, limit: int = 10
) -> list[dict]:
    normalized = (query or "").strip().lower()
    if not normalized:
        return []
    pattern = f"%{normalized}%"
    rows = (
        db.query(Client)
        .filter(
            Client.tenant_id == tenant_id,
            (
                func.lower(Client.name).like(pattern)
                | func.lower(func.coalesce(Client.phone, "")).like(pattern)
            ),
        )
        .order_by(Client.name.asc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    out = []
    for c in rows:
        visits_count = db.execute(
            select(func.count(Visit.id)).where(
                Visit.tenant_id == tenant_id, Visit.client_id == c.id
            )
        ).scalar_one()
        last_visit_dt = db.execute(
            select(func.max(Visit.dt)).where(
                Visit.tenant_id == tenant_id, Visit.client_id == c.id
            )
        ).scalar_one()
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "visits_count": int(visits_count or 0),
                "last_visit_dt": last_visit_dt,
            }
        )
    return out


def add_client_note(
    db: Session,
    tenant_id: int,
    client_id: int,
    note: str,
    actor: str | None = None,
) -> ClientNote | None:
    client = db.execute(
        select(Client).where(Client.id == client_id, Client.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not client:
        return None
    row = ClientNote(
        tenant_id=tenant_id,
        client_id=client_id,
        note=note.strip(),
        actor=(actor or "").strip() or None,
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_client_detail(db: Session, tenant_id: int, client_id: int) -> dict | None:
    client = db.execute(
        select(Client).where(Client.id == client_id, Client.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not client:
        return None

    visits = (
        db.query(Visit)
        .join(Visit.employee)
        .join(Visit.service)
        .filter(Visit.tenant_id == tenant_id, Visit.client_id == client_id)
        .order_by(Visit.dt.desc())
        .limit(50)
        .all()
    )
    notes = (
        db.query(ClientNote)
        .filter(ClientNote.tenant_id == tenant_id, ClientNote.client_id == client_id)
        .order_by(ClientNote.created_at.desc(), ClientNote.id.desc())
        .limit(50)
        .all()
    )
    visits_count = db.execute(
        select(func.count(Visit.id)).where(
            Visit.tenant_id == tenant_id, Visit.client_id == client_id
        )
    ).scalar_one()
    last_visit_dt = db.execute(
        select(func.max(Visit.dt)).where(
            Visit.tenant_id == tenant_id, Visit.client_id == client_id
        )
    ).scalar_one()
    return {
        "id": client.id,
        "name": client.name,
        "phone": client.phone,
        "visits_count": int(visits_count or 0),
        "last_visit_dt": last_visit_dt,
        "notes": notes,
        "visits": visits,
    }


def get_day_pulse(db: Session, tenant_id: int, day: date) -> dict:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    visits = (
        db.query(Visit)
        .join(Visit.employee)
        .filter(Visit.tenant_id == tenant_id, Visit.dt >= start, Visit.dt <= end)
        .all()
    )
    total_revenue = sum(float(v.price or 0) for v in visits)
    visits_count = len(visits)
    visits_by_status: dict[str, int] = {}
    used_minutes: dict[str, int] = {}
    for v in visits:
        status = (v.status or "planned").strip().lower()
        visits_by_status[status] = visits_by_status.get(status, 0) + 1
        emp = v.employee.name
        used_minutes[emp] = used_minutes.get(emp, 0) + int(v.duration_min or 30)

    occupancy_by_employee: dict[str, float] = {}
    for emp, used in used_minutes.items():
        hours = get_employee_hours(db, tenant_id, emp, day)
        if not hours:
            occupancy_by_employee[emp] = 0.0
            continue
        capacity = max(0, (int(hours[1]) - int(hours[0])) * 60)
        occupancy_by_employee[emp] = round((used / capacity), 4) if capacity else 0.0

    reservations_new = db.execute(
        select(func.count(ReservationRequest.id)).where(
            ReservationRequest.tenant_id == tenant_id,
            ReservationRequest.status == "new",
        )
    ).scalar_one()
    reservations_contacted = db.execute(
        select(func.count(ReservationRequest.id)).where(
            ReservationRequest.tenant_id == tenant_id,
            ReservationRequest.status == "contacted",
        )
    ).scalar_one()
    metrics = get_reservation_metrics(db, tenant_id)

    return {
        "day": day,
        "total_revenue": round(total_revenue, 2),
        "visits_count": visits_count,
        "conversion_rate": float(metrics.get("conversion_rate", 0.0)),
        "reservations_new": int(reservations_new or 0),
        "reservations_contacted": int(reservations_contacted or 0),
        "visits_by_status": visits_by_status,
        "occupancy_by_employee": occupancy_by_employee,
    }


def get_reservation_assistant_actions(
    db: Session,
    tenant_id: int,
    limit: int = 25,
) -> list[dict]:
    from .enterprise import get_sla_contact_minutes

    rows = (
        db.query(ReservationRequest)
        .filter(ReservationRequest.tenant_id == tenant_id)
        .order_by(ReservationRequest.requested_dt.asc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    now = utc_now_naive()
    contact_sla_hours = max(1, int(get_sla_contact_minutes(db, tenant_id) // 60))
    out = []
    for r in rows:
        status = (r.status or "new").strip().lower()
        hours_to_visit = int((r.requested_dt - now).total_seconds() // 3600)
        if status == "new":
            suggested_action = "contact_client"
            priority = 1 if hours_to_visit <= contact_sla_hours else 2
        elif status == "contacted":
            suggested_action = "confirm_or_offer_alternative"
            priority = 1 if hours_to_visit <= 6 else 2
        elif status == "confirmed":
            suggested_action = "send_reminder"
            priority = 2
        else:
            suggested_action = "no_action"
            priority = 4

        out.append(
            {
                "reservation_id": r.id,
                "status": status,
                "requested_dt": r.requested_dt,
                "client_name": r.client_name,
                "service_name": r.service_name,
                "suggested_action": suggested_action,
                "priority": priority,
            }
        )
    out.sort(key=lambda x: (x["priority"], x["requested_dt"]))
    return out[:limit]


def get_conversion_integrity_report(
    db: Session,
    tenant_id: int,
    limit: int = 100,
) -> dict:
    issues: list[dict] = []

    reservations = (
        db.execute(
            select(ReservationRequest).where(ReservationRequest.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    )
    visits = (
        db.execute(select(Visit).where(Visit.tenant_id == tenant_id)).scalars().all()
    )

    reservation_by_id = {int(r.id): r for r in reservations}
    visit_by_id = {int(v.id): v for v in visits}
    visits_by_source: dict[int, list[Visit]] = {}
    for v in visits:
        if v.source_reservation_id is None:
            continue
        source_id = int(v.source_reservation_id)
        visits_by_source.setdefault(source_id, []).append(v)

    for r in reservations:
        if r.converted_visit_id is None:
            continue
        visit = visit_by_id.get(int(r.converted_visit_id))
        if not visit:
            issues.append(
                {
                    "type": "reservation_points_missing_visit",
                    "reservation_id": int(r.id),
                    "visit_id": int(r.converted_visit_id),
                    "detail": "Reservation has converted_visit_id but visit does not exist",
                }
            )
            continue
        if visit.source_reservation_id is None:
            issues.append(
                {
                    "type": "visit_missing_source_link",
                    "reservation_id": int(r.id),
                    "visit_id": int(visit.id),
                    "detail": "Converted visit has no source_reservation_id",
                }
            )
        elif int(visit.source_reservation_id) != int(r.id):
            issues.append(
                {
                    "type": "reservation_visit_mismatch",
                    "reservation_id": int(r.id),
                    "visit_id": int(visit.id),
                    "source_reservation_id": int(visit.source_reservation_id),
                    "detail": "Reservation converted_visit_id points to visit linked to a different reservation",
                }
            )

    for v in visits:
        if v.source_reservation_id is None:
            continue
        source_id = int(v.source_reservation_id)
        reservation = reservation_by_id.get(source_id)
        if not reservation:
            issues.append(
                {
                    "type": "visit_points_missing_reservation",
                    "visit_id": int(v.id),
                    "source_reservation_id": source_id,
                    "detail": "Visit source_reservation_id points to missing reservation",
                }
            )
            continue
        if reservation.converted_visit_id is None:
            issues.append(
                {
                    "type": "reservation_missing_converted_visit_id",
                    "reservation_id": int(reservation.id),
                    "visit_id": int(v.id),
                    "source_reservation_id": source_id,
                    "detail": "Visit links to reservation, but reservation has no converted_visit_id",
                }
            )
        elif int(reservation.converted_visit_id) != int(v.id):
            issues.append(
                {
                    "type": "reservation_visit_mismatch",
                    "reservation_id": int(reservation.id),
                    "visit_id": int(v.id),
                    "source_reservation_id": source_id,
                    "detail": "Visit source_reservation_id points to reservation linked to another visit",
                }
            )

    for source_id, linked_visits in visits_by_source.items():
        if len(linked_visits) <= 1:
            continue
        visit_ids = sorted(int(v.id) for v in linked_visits)
        issues.append(
            {
                "type": "duplicate_visit_source_reservation",
                "source_reservation_id": int(source_id),
                "detail": f"Multiple visits linked to one source reservation: {visit_ids}",
            }
        )

    by_type: dict[str, int] = {}
    for item in issues:
        key = str(item["type"])
        by_type[key] = by_type.get(key, 0) + 1

    max_items = max(1, min(int(limit), 500))
    trimmed = issues[:max_items]
    return {
        "ok": len(issues) == 0,
        "checked_at": utc_now_naive(),
        "issues_count": len(issues),
        "by_type": by_type,
        "truncated": len(issues) > max_items,
        "issues": trimmed,
    }


def _to_payload_json(payload: dict | None) -> str | None:
    if not payload:
        return None
    try:
        return json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), default=str
        )
    except TypeError:
        return json.dumps({"raw": str(payload)}, ensure_ascii=True)


def _log_schedule_audit_event(
    db: Session,
    tenant_id: int,
    action: str,
    *,
    actor_email: str | None = None,
    employee_id: int | None = None,
    related_id: str | None = None,
    payload: dict | None = None,
) -> ScheduleAuditEvent:
    row = ScheduleAuditEvent(
        tenant_id=tenant_id,
        action=(action or "").strip()[:80],
        actor_email=(actor_email or "").strip().lower() or None,
        employee_id=employee_id,
        related_id=(related_id or "").strip()[:120] or None,
        payload_json=_to_payload_json(payload),
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.flush()
    return row


def _enqueue_schedule_notification(
    db: Session,
    tenant_id: int,
    event_type: str,
    message: str,
    *,
    employee_id: int | None = None,
    channel: str = "internal",
) -> ScheduleNotification:
    row = ScheduleNotification(
        tenant_id=tenant_id,
        employee_id=employee_id,
        event_type=(event_type or "").strip()[:80] or "generic",
        message=(message or "").strip()[:500] or "Update",
        channel=(channel or "internal").strip()[:32] or "internal",
        status="pending",
        last_error=None,
        sent_at=None,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.flush()
    return row


def upsert_employee_service_capability(
    db: Session,
    tenant_id: int,
    employee_id: int,
    *,
    service_name: str,
    duration_min: int | None = None,
    price_override: float | None = None,
    is_active: bool = True,
    actor_email: str | None = None,
) -> EmployeeServiceCapability | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None

    normalized_service = (service_name or "").strip()
    if not normalized_service:
        raise ValueError("service_name is required")

    row = db.execute(
        select(EmployeeServiceCapability).where(
            EmployeeServiceCapability.tenant_id == tenant_id,
            EmployeeServiceCapability.employee_id == employee_id,
            EmployeeServiceCapability.service_name == normalized_service,
        )
    ).scalar_one_or_none()
    now = utc_now_naive()
    if row is None:
        row = EmployeeServiceCapability(
            tenant_id=tenant_id,
            employee_id=employee_id,
            service_name=normalized_service,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    if duration_min is not None:
        parsed_duration = int(duration_min)
        if parsed_duration <= 0:
            raise ValueError("duration_min must be > 0")
        row.duration_min = parsed_duration
    else:
        row.duration_min = None
    row.price_override = float(price_override) if price_override is not None else None
    row.is_active = bool(is_active)
    row.updated_at = now

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="capability.upsert",
        actor_email=actor_email,
        employee_id=employee_id,
        related_id=f"capability:{employee_id}:{normalized_service.lower()}",
        payload={
            "employee_name": employee.name,
            "service_name": normalized_service,
            "duration_min": row.duration_min,
            "price_override": float(row.price_override)
            if row.price_override is not None
            else None,
            "is_active": row.is_active,
        },
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=employee_id,
        event_type="capability_changed",
        message=f"Updated capability for {employee.name}: {normalized_service}",
    )
    db.commit()
    db.refresh(row)
    return row


def list_employee_service_capabilities(
    db: Session,
    tenant_id: int,
    employee_id: int,
    *,
    active_only: bool = False,
) -> list[EmployeeServiceCapability] | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None
    stmt = (
        select(EmployeeServiceCapability)
        .where(
            EmployeeServiceCapability.tenant_id == tenant_id,
            EmployeeServiceCapability.employee_id == employee_id,
        )
        .order_by(
            EmployeeServiceCapability.service_name.asc(),
            EmployeeServiceCapability.id.asc(),
        )
    )
    if active_only:
        stmt = stmt.where(EmployeeServiceCapability.is_active.is_(True))
    return db.execute(stmt).scalars().all()


def create_employee_leave_request(
    db: Session,
    tenant_id: int,
    *,
    employee_id: int,
    start_day: date,
    end_day: date,
    reason: str | None = None,
    requested_by: str | None = None,
) -> EmployeeLeaveRequest | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None
    if end_day < start_day:
        raise ValueError("end_day must be >= start_day")

    conflict = db.execute(
        select(EmployeeLeaveRequest.id).where(
            EmployeeLeaveRequest.tenant_id == tenant_id,
            EmployeeLeaveRequest.employee_id == employee_id,
            EmployeeLeaveRequest.status.in_(["pending", "approved"]),
            EmployeeLeaveRequest.start_day <= end_day,
            EmployeeLeaveRequest.end_day >= start_day,
        )
    ).first()
    if conflict is not None:
        raise ValueError("Overlapping leave already exists")

    now = utc_now_naive()
    row = EmployeeLeaveRequest(
        tenant_id=tenant_id,
        employee_id=employee_id,
        start_day=start_day,
        end_day=end_day,
        status="pending",
        reason=(reason or "").strip()[:500] or None,
        requested_by=(requested_by or "").strip().lower()[:160] or None,
        decided_by=None,
        decision_note=None,
        decided_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="leave.create",
        actor_email=requested_by,
        employee_id=employee_id,
        related_id=f"leave:{row.id}",
        payload={"start_day": start_day.isoformat(), "end_day": end_day.isoformat()},
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=employee_id,
        event_type="leave_requested",
        message=f"{employee.name} requested leave {start_day.isoformat()}-{end_day.isoformat()}",
    )
    db.commit()
    db.refresh(row)
    return row


def list_employee_leave_requests(
    db: Session,
    tenant_id: int,
    *,
    status_filter: str | None = None,
    employee_id: int | None = None,
    start_day: date | None = None,
    end_day: date | None = None,
) -> list[EmployeeLeaveRequest]:
    stmt = select(EmployeeLeaveRequest).where(
        EmployeeLeaveRequest.tenant_id == tenant_id
    )
    if status_filter:
        stmt = stmt.where(EmployeeLeaveRequest.status == status_filter.strip().lower())
    if employee_id:
        stmt = stmt.where(EmployeeLeaveRequest.employee_id == employee_id)
    if start_day:
        stmt = stmt.where(EmployeeLeaveRequest.end_day >= start_day)
    if end_day:
        stmt = stmt.where(EmployeeLeaveRequest.start_day <= end_day)
    stmt = stmt.order_by(
        EmployeeLeaveRequest.start_day.asc(), EmployeeLeaveRequest.id.asc()
    )
    return db.execute(stmt).scalars().all()


def decide_employee_leave_request(
    db: Session,
    tenant_id: int,
    leave_id: int,
    *,
    decision: str,
    decision_note: str | None = None,
    decided_by: str | None = None,
) -> EmployeeLeaveRequest | None:
    row = db.execute(
        select(EmployeeLeaveRequest).where(
            EmployeeLeaveRequest.tenant_id == tenant_id,
            EmployeeLeaveRequest.id == leave_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    normalized = (decision or "").strip().lower()
    if normalized not in {"approved", "rejected", "canceled"}:
        raise ValueError("Invalid leave decision")

    row.status = normalized
    row.decided_by = (decided_by or "").strip().lower()[:160] or None
    row.decision_note = (decision_note or "").strip()[:500] or None
    row.decided_at = utc_now_naive()
    row.updated_at = utc_now_naive()
    employee = get_employee_by_id(db, tenant_id, row.employee_id)

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="leave.decide",
        actor_email=decided_by,
        employee_id=row.employee_id,
        related_id=f"leave:{row.id}",
        payload={"decision": normalized},
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=row.employee_id,
        event_type="leave_decision",
        message=f"Leave request #{row.id} for {(employee.name if employee else 'employee')} is {normalized}",
    )
    db.commit()
    db.refresh(row)
    return row


def apply_employee_weekly_schedule_to_range(
    db: Session,
    tenant_id: int,
    employee_id: int,
    *,
    start_day: date,
    end_day: date,
    actor_email: str | None = None,
) -> int | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None
    if end_day < start_day:
        raise ValueError("end_day must be >= start_day")

    weekly_rows = list_employee_weekly_schedule(db, tenant_id, employee_id)
    if weekly_rows is None:
        return None
    weekly_by_weekday = {int(row["weekday"]): row for row in weekly_rows}
    count = 0
    cursor = start_day
    while cursor <= end_day:
        template = weekly_by_weekday.get(cursor.weekday())
        if template is None:
            cursor += timedelta(days=1)
            continue
        upsert_employee_availability_day(
            db=db,
            tenant_id=tenant_id,
            employee_name=employee.name,
            day=cursor,
            is_day_off=bool(template.get("is_day_off")),
            start_hour=template.get("start_hour"),
            end_hour=template.get("end_hour"),
            note="generated_from_weekly_schedule",
        )
        count += 1
        cursor += timedelta(days=1)

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="weekly_schedule.apply_range",
        actor_email=actor_email,
        employee_id=employee_id,
        related_id=f"employee:{employee_id}",
        payload={
            "start_day": start_day.isoformat(),
            "end_day": end_day.isoformat(),
            "days_written": count,
        },
    )
    db.commit()
    return count


def create_shift_swap_request(
    db: Session,
    tenant_id: int,
    *,
    shift_day: date,
    from_employee_id: int,
    to_employee_id: int,
    from_start_hour: int,
    from_end_hour: int,
    to_start_hour: int,
    to_end_hour: int,
    reason: str | None = None,
    requested_by: str | None = None,
) -> ShiftSwapRequest | None:
    if from_employee_id == to_employee_id:
        raise ValueError("Employees in shift swap must be different")

    from_employee = get_employee_by_id(db, tenant_id, from_employee_id)
    to_employee = get_employee_by_id(db, tenant_id, to_employee_id)
    if from_employee is None or to_employee is None:
        return None
    if not bool(from_employee.is_active) or not bool(to_employee.is_active):
        raise ValueError("Shift swap employees must be active")

    if int(from_end_hour) <= int(from_start_hour) or int(to_end_hour) <= int(
        to_start_hour
    ):
        raise ValueError("Shift hours are invalid")

    now = utc_now_naive()
    row = ShiftSwapRequest(
        tenant_id=tenant_id,
        shift_day=shift_day,
        from_employee_id=from_employee_id,
        to_employee_id=to_employee_id,
        from_start_hour=int(from_start_hour),
        from_end_hour=int(from_end_hour),
        to_start_hour=int(to_start_hour),
        to_end_hour=int(to_end_hour),
        status="pending",
        reason=(reason or "").strip()[:500] or None,
        requested_by=(requested_by or "").strip().lower()[:160] or None,
        decided_by=None,
        decision_note=None,
        decided_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="swap.create",
        actor_email=requested_by,
        related_id=f"swap:{row.id}",
        payload={
            "shift_day": shift_day.isoformat(),
            "from_employee_id": from_employee_id,
            "to_employee_id": to_employee_id,
        },
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=from_employee_id,
        event_type="swap_requested",
        message=f"Shift swap requested on {shift_day.isoformat()} between {from_employee.name} and {to_employee.name}",
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=to_employee_id,
        event_type="swap_requested",
        message=f"Shift swap requested on {shift_day.isoformat()} between {from_employee.name} and {to_employee.name}",
    )
    db.commit()
    db.refresh(row)
    return row


def list_shift_swap_requests(
    db: Session,
    tenant_id: int,
    *,
    status_filter: str | None = None,
    start_day: date | None = None,
    end_day: date | None = None,
) -> list[ShiftSwapRequest]:
    stmt = select(ShiftSwapRequest).where(ShiftSwapRequest.tenant_id == tenant_id)
    if status_filter:
        stmt = stmt.where(ShiftSwapRequest.status == status_filter.strip().lower())
    if start_day:
        stmt = stmt.where(ShiftSwapRequest.shift_day >= start_day)
    if end_day:
        stmt = stmt.where(ShiftSwapRequest.shift_day <= end_day)
    stmt = stmt.order_by(ShiftSwapRequest.shift_day.asc(), ShiftSwapRequest.id.asc())
    return db.execute(stmt).scalars().all()


def decide_shift_swap_request(
    db: Session,
    tenant_id: int,
    swap_id: int,
    *,
    decision: str,
    decision_note: str | None = None,
    decided_by: str | None = None,
) -> ShiftSwapRequest | None:
    row = db.execute(
        select(ShiftSwapRequest).where(
            ShiftSwapRequest.tenant_id == tenant_id,
            ShiftSwapRequest.id == swap_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    normalized = (decision or "").strip().lower()
    if normalized not in {"approved", "rejected", "canceled"}:
        raise ValueError("Invalid swap decision")

    row.status = normalized
    row.decided_by = (decided_by or "").strip().lower()[:160] or None
    row.decision_note = (decision_note or "").strip()[:500] or None
    row.decided_at = utc_now_naive()
    row.updated_at = utc_now_naive()
    from_employee = get_employee_by_id(db, tenant_id, row.from_employee_id)
    to_employee = get_employee_by_id(db, tenant_id, row.to_employee_id)

    if normalized == "approved" and from_employee and to_employee:
        upsert_employee_availability_day(
            db=db,
            tenant_id=tenant_id,
            employee_name=from_employee.name,
            day=row.shift_day,
            is_day_off=False,
            start_hour=row.to_start_hour,
            end_hour=row.to_end_hour,
            note=f"swap:{row.id}",
        )
        upsert_employee_availability_day(
            db=db,
            tenant_id=tenant_id,
            employee_name=to_employee.name,
            day=row.shift_day,
            is_day_off=False,
            start_hour=row.from_start_hour,
            end_hour=row.from_end_hour,
            note=f"swap:{row.id}",
        )

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="swap.decide",
        actor_email=decided_by,
        related_id=f"swap:{row.id}",
        payload={"decision": normalized},
    )
    if from_employee:
        _enqueue_schedule_notification(
            db=db,
            tenant_id=tenant_id,
            employee_id=from_employee.id,
            event_type="swap_decision",
            message=f"Shift swap #{row.id} is {normalized}",
        )
    if to_employee:
        _enqueue_schedule_notification(
            db=db,
            tenant_id=tenant_id,
            employee_id=to_employee.id,
            event_type="swap_decision",
            message=f"Shift swap #{row.id} is {normalized}",
        )

    db.commit()
    db.refresh(row)
    return row


def reassign_visit_employee(
    db: Session,
    tenant_id: int,
    visit_id: int,
    *,
    to_employee_id: int,
    reason: str | None = None,
    actor_email: str | None = None,
) -> Visit | None:
    visit = (
        db.query(Visit)
        .join(Visit.employee)
        .join(Visit.service)
        .filter(Visit.tenant_id == tenant_id, Visit.id == visit_id)
        .first()
    )
    if visit is None:
        return None

    target = get_employee_by_id(db, tenant_id, to_employee_id)
    if target is None:
        raise ValueError("Target employee not found")
    if not bool(target.is_active):
        raise ValueError("Target employee is archived")
    if int(target.id) == int(visit.employee_id):
        return visit

    _, capability = _get_employee_capability(
        db=db,
        tenant_id=tenant_id,
        employee_name=target.name,
        service_name=visit.service.name,
    )
    if (
        _employee_has_any_active_capability(db, tenant_id, target.id)
        and capability is None
    ):
        raise ValueError("Target employee is not assigned to this service")

    ok, detail = check_visit_slot_available(
        db=db,
        tenant_id=tenant_id,
        employee_name=target.name,
        service_name=visit.service.name,
        dt=visit.dt,
        duration_min=int(visit.duration_min or 30),
        skip_visit_id=visit.id,
    )
    if not ok:
        raise ValueError(detail or "Slot unavailable for target employee")

    old_employee_id = int(visit.employee_id)
    old_employee_name = visit.employee.name
    visit.employee_id = target.id

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="visit.reassign",
        actor_email=actor_email,
        employee_id=target.id,
        related_id=f"visit:{visit.id}",
        payload={
            "from_employee_id": old_employee_id,
            "to_employee_id": target.id,
            "reason": (reason or "").strip(),
        },
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=old_employee_id,
        event_type="visit_reassigned",
        message=f"Visit #{visit.id} reassigned from {old_employee_name} to {target.name}",
    )
    _enqueue_schedule_notification(
        db=db,
        tenant_id=tenant_id,
        employee_id=target.id,
        event_type="visit_reassigned",
        message=f"Visit #{visit.id} reassigned from {old_employee_name} to {target.name}",
    )
    db.commit()
    db.refresh(visit)
    return visit


def create_time_clock_entry(
    db: Session,
    tenant_id: int,
    *,
    employee_id: int,
    event_type: str,
    event_dt: datetime | None = None,
    source: str | None = None,
    note: str | None = None,
    actor_email: str | None = None,
) -> TimeClockEntry | None:
    employee = get_employee_by_id(db, tenant_id, employee_id)
    if employee is None:
        return None
    if not bool(employee.is_active):
        raise ValueError("Employee is archived")

    normalized_event = (event_type or "").strip().lower()
    if normalized_event not in {"check_in", "check_out"}:
        raise ValueError("event_type must be check_in or check_out")

    last_row = db.execute(
        select(TimeClockEntry)
        .where(
            TimeClockEntry.tenant_id == tenant_id,
            TimeClockEntry.employee_id == employee_id,
        )
        .order_by(TimeClockEntry.event_dt.desc(), TimeClockEntry.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_row and str(last_row.event_type).lower() == normalized_event:
        raise ValueError(f"Consecutive {normalized_event} is not allowed")

    row = TimeClockEntry(
        tenant_id=tenant_id,
        employee_id=employee_id,
        event_type=normalized_event,
        event_dt=to_utc_naive(event_dt or utc_now_naive()),
        source=(source or "").strip()[:80] or None,
        note=(note or "").strip()[:300] or None,
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.flush()
    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="time_clock.event",
        actor_email=actor_email,
        employee_id=employee_id,
        related_id=f"time_clock:{row.id}",
        payload={"event_type": normalized_event, "event_dt": row.event_dt.isoformat()},
    )
    db.commit()
    db.refresh(row)
    return row


def list_time_clock_day_report(
    db: Session,
    tenant_id: int,
    *,
    day: date,
) -> list[dict]:
    start_dt = datetime.combine(day, time.min)
    end_dt = datetime.combine(day, time.max)
    active_employees = list_team_employees(db, tenant_id, include_inactive=False)
    entry_rows = (
        db.execute(
            select(TimeClockEntry)
            .where(
                TimeClockEntry.tenant_id == tenant_id,
                TimeClockEntry.event_dt >= start_dt,
                TimeClockEntry.event_dt <= end_dt,
            )
            .order_by(
                TimeClockEntry.employee_id.asc(),
                TimeClockEntry.event_dt.asc(),
                TimeClockEntry.id.asc(),
            )
        )
        .scalars()
        .all()
    )
    entries_by_employee: dict[int, list[TimeClockEntry]] = {}
    for row in entry_rows:
        entries_by_employee.setdefault(int(row.employee_id), []).append(row)

    all_employee_ids = {int(e.id) for e in active_employees}
    all_employee_ids.update(entries_by_employee.keys())

    out: list[dict] = []
    for employee_id in sorted(all_employee_ids):
        employee = get_employee_by_id(db, tenant_id, employee_id)
        if employee is None:
            continue
        hours = get_employee_hours(db, tenant_id, employee.name, day)
        planned_start_hour = int(hours[0]) if hours else None
        planned_end_hour = int(hours[1]) if hours else None
        rows = entries_by_employee.get(employee_id, [])
        first_check_in = next(
            (row.event_dt for row in rows if row.event_type == "check_in"), None
        )
        last_check_out = next(
            (row.event_dt for row in reversed(rows) if row.event_type == "check_out"),
            None,
        )

        worked_minutes = 0
        open_check_in: datetime | None = None
        for row in rows:
            if row.event_type == "check_in":
                open_check_in = row.event_dt
            elif row.event_type == "check_out" and open_check_in is not None:
                delta = int((row.event_dt - open_check_in).total_seconds() // 60)
                if delta > 0:
                    worked_minutes += delta
                open_check_in = None

        late_minutes = 0
        if planned_start_hour is not None and first_check_in is not None:
            planned_dt = datetime.combine(day, time(hour=planned_start_hour, minute=0))
            late_minutes = max(
                0, int((first_check_in - planned_dt).total_seconds() // 60)
            )

        overtime_minutes = 0
        if planned_end_hour is not None and last_check_out is not None:
            planned_end_dt = datetime.combine(
                day,
                time(
                    hour=min(planned_end_hour, 23),
                    minute=59 if planned_end_hour == 24 else 0,
                ),
            )
            overtime_minutes = max(
                0, int((last_check_out - planned_end_dt).total_seconds() // 60)
            )

        out.append(
            {
                "employee_id": employee_id,
                "employee_name": employee.name,
                "planned_start_hour": planned_start_hour,
                "planned_end_hour": planned_end_hour,
                "first_check_in": first_check_in,
                "last_check_out": last_check_out,
                "late_minutes": late_minutes,
                "overtime_minutes": overtime_minutes,
                "worked_minutes": worked_minutes,
            }
        )
    out.sort(
        key=lambda row: (str(row["employee_name"]).lower(), int(row["employee_id"]))
    )
    return out


def list_schedule_audit_events(
    db: Session,
    tenant_id: int,
    *,
    limit: int = 100,
    action: str | None = None,
    employee_id: int | None = None,
) -> list[ScheduleAuditEvent]:
    stmt = select(ScheduleAuditEvent).where(ScheduleAuditEvent.tenant_id == tenant_id)
    if action:
        stmt = stmt.where(ScheduleAuditEvent.action == action.strip())
    if employee_id:
        stmt = stmt.where(ScheduleAuditEvent.employee_id == employee_id)
    stmt = stmt.order_by(
        ScheduleAuditEvent.created_at.desc(), ScheduleAuditEvent.id.desc()
    )
    stmt = stmt.limit(max(1, min(int(limit), 1000)))
    return db.execute(stmt).scalars().all()


def list_schedule_notifications(
    db: Session,
    tenant_id: int,
    *,
    status_filter: str | None = None,
    limit: int = 200,
) -> list[tuple[ScheduleNotification, str | None]]:
    stmt = (
        select(ScheduleNotification, Employee.name)
        .select_from(ScheduleNotification)
        .outerjoin(
            Employee,
            (Employee.id == ScheduleNotification.employee_id)
            & (Employee.tenant_id == ScheduleNotification.tenant_id),
        )
        .where(ScheduleNotification.tenant_id == tenant_id)
    )
    if status_filter:
        stmt = stmt.where(ScheduleNotification.status == status_filter.strip().lower())
    stmt = stmt.order_by(
        ScheduleNotification.created_at.desc(), ScheduleNotification.id.desc()
    )
    stmt = stmt.limit(max(1, min(int(limit), 1000)))
    return db.execute(stmt).all()


def set_schedule_notification_status(
    db: Session,
    tenant_id: int,
    notification_id: int,
    *,
    status_value: str,
    last_error: str | None = None,
    actor_email: str | None = None,
) -> ScheduleNotification | None:
    row = db.execute(
        select(ScheduleNotification).where(
            ScheduleNotification.tenant_id == tenant_id,
            ScheduleNotification.id == notification_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    normalized = (status_value or "").strip().lower()
    if normalized not in {"pending", "sent", "failed"}:
        raise ValueError("Invalid notification status")
    row.status = normalized
    row.last_error = (last_error or "").strip()[:500] or None
    row.sent_at = utc_now_naive() if normalized == "sent" else None
    row.updated_at = utc_now_naive()

    _log_schedule_audit_event(
        db=db,
        tenant_id=tenant_id,
        action="notification.status",
        actor_email=actor_email,
        employee_id=row.employee_id,
        related_id=f"notification:{row.id}",
        payload={"status": normalized},
    )
    db.commit()
    db.refresh(row)
    return row
