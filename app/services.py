from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    Client,
    Employee,
    ReservationRequest,
    ReservationStatusEvent,
    Service,
    Tenant,
    Visit,
)


RESERVATION_STATUSES = {"new", "contacted", "confirmed", "rejected"}
ALLOWED_STATUS_TRANSITIONS = {
    "new": {"contacted"},
    "contacted": {"confirmed", "rejected"},
    "confirmed": set(),
    "rejected": set(),
}


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_or_create_tenant(db: Session, slug: str, name: str | None = None) -> Tenant:
    normalized_slug = slug.strip().lower()
    tenant = db.execute(select(Tenant).where(Tenant.slug == normalized_slug)).scalar_one_or_none()
    if tenant:
        return tenant

    tenant = Tenant(slug=normalized_slug, name=(name or normalized_slug).strip())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def get_or_create_client(db: Session, tenant_id: int, name: str) -> Client:
    obj = db.execute(select(Client).where(Client.tenant_id == tenant_id, Client.name == name)).scalar_one_or_none()
    if obj:
        return obj
    obj = Client(tenant_id=tenant_id, name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_or_create_employee(db: Session, tenant_id: int, name: str) -> Employee:
    obj = db.execute(select(Employee).where(Employee.tenant_id == tenant_id, Employee.name == name)).scalar_one_or_none()
    if obj:
        return obj
    obj = Employee(tenant_id=tenant_id, name=name, commission_pct=0)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_or_create_service(db: Session, tenant_id: int, name: str, default_price: float = 0) -> Service:
    obj = db.execute(select(Service).where(Service.tenant_id == tenant_id, Service.name == name)).scalar_one_or_none()
    if obj:
        return obj
    obj = Service(tenant_id=tenant_id, name=name, default_price=default_price)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_visit(
    db: Session,
    tenant_id: int,
    dt: datetime,
    client_name: str,
    employee_name: str,
    service_name: str,
    price: float,
) -> Visit:
    client = get_or_create_client(db, tenant_id, client_name.strip())
    employee = get_or_create_employee(db, tenant_id, employee_name.strip())
    service = get_or_create_service(db, tenant_id, service_name.strip())

    visit = Visit(
        tenant_id=tenant_id,
        dt=to_utc_naive(dt),
        client_id=client.id,
        employee_id=employee.id,
        service_id=service.id,
        price=price,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return visit


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


def update_visit_datetime(db: Session, tenant_id: int, visit_id: int, dt: datetime) -> Visit | None:
    visit = db.execute(select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id)).scalar_one_or_none()
    if not visit:
        return None
    visit.dt = to_utc_naive(dt)
    db.commit()
    db.refresh(visit)
    return visit


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
        select(Employee.name, Employee.commission_pct, func.coalesce(func.sum(Visit.price), 0))
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
    visit = db.execute(select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id)).scalar_one_or_none()
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
    stmt = stmt.order_by(ReservationRequest.created_at.desc()).limit(max(1, min(limit, 500)))
    return db.execute(stmt).scalars().all()


def get_reservation_by_id(db: Session, tenant_id: int, reservation_id: int) -> ReservationRequest | None:
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
    reservation = get_reservation_by_id(db, tenant_id, reservation_id)
    if not reservation:
        return None

    target_status = new_status.strip().lower()
    if target_status not in RESERVATION_STATUSES:
        raise ValueError("Invalid reservation status")

    current_status = reservation.status.strip().lower()
    if target_status == current_status:
        return reservation

    if reservation.converted_visit_id and target_status != "confirmed":
        raise ValueError("Converted reservation can only stay confirmed")

    allowed_next = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_next:
        raise ValueError(f"Invalid status transition: {current_status} -> {target_status}")

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

    from_status = reservation.status
    visit = create_visit(
        db=db,
        tenant_id=tenant_id,
        dt=dt or reservation.requested_dt,
        client_name=(client_name or reservation.client_name).strip(),
        employee_name=employee_name.strip(),
        service_name=(service_name or reservation.service_name).strip(),
        price=price,
    )

    reservation.status = "confirmed"
    reservation.converted_visit_id = visit.id
    reservation.converted_at = utc_now_naive()
    add_reservation_status_event(
        db=db,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
        from_status=from_status,
        to_status="confirmed",
        action="converted_to_visit",
        actor=actor,
        note=f"visit_id={visit.id}",
    )
    db.commit()
    db.refresh(reservation)
    return reservation, visit


def list_reservation_status_events(db: Session, tenant_id: int, reservation_id: int) -> list[ReservationStatusEvent]:
    stmt = (
        select(ReservationStatusEvent)
        .where(
            ReservationStatusEvent.tenant_id == tenant_id,
            ReservationStatusEvent.reservation_id == reservation_id,
        )
        .order_by(ReservationStatusEvent.created_at.asc(), ReservationStatusEvent.id.asc())
    )
    return db.execute(stmt).scalars().all()


def get_reservation_metrics(db: Session, tenant_id: int) -> dict:
    total = db.execute(select(func.count(ReservationRequest.id)).where(ReservationRequest.tenant_id == tenant_id)).scalar_one()

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


