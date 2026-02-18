from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .csv_export import export_visits_csv
from .db import get_db
from .models import Tenant, Visit
from .pdf_export import build_month_report_pdf
from .schemas import (
    DaySummary,
    MonthReport,
    PublicReservationCreate,
    PublicReservationOut,
    ReservationConvertCreate,
    ReservationMetricsOut,
    ReservationStatusEventOut,
    ReservationStatusUpdate,
    VisitCreate,
    VisitOut,
    VisitUpdate,
)
from .services import (
    convert_reservation_to_visit,
    create_public_reservation,
    create_visit,
    day_summary,
    delete_visit,
    get_or_create_tenant,
    get_reservation_by_id,
    get_reservation_metrics,
    list_public_reservations,
    list_reservation_status_events,
    month_report,
    update_reservation_status,
    update_visit_datetime,
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
        client_name=client_name,
        employee_name=employee_name,
        service_name=service_name,
        duration_min=None,
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


def _resolve_tenant_or_default(db: Session, tenant_slug: Optional[str]) -> Tenant:
    slug = (tenant_slug or settings.DEFAULT_TENANT_SLUG).strip().lower()
    tenant_name = settings.DEFAULT_TENANT_NAME if slug == settings.DEFAULT_TENANT_SLUG else slug
    return get_or_create_tenant(db, slug=slug, name=tenant_name)


def get_current_tenant(
    db: Session = Depends(get_db),
    x_tenant_slug: Optional[str] = Header(default=None),
) -> Tenant:
    return _resolve_tenant_or_default(db, x_tenant_slug)


@router.post("/visits", response_model=VisitOut)
def add_visit(
    payload: VisitCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    v = create_visit(
        db=db,
        tenant_id=tenant.id,
        dt=payload.dt,
        client_name=payload.client_name,
        employee_name=payload.employee_name,
        service_name=payload.service_name,
        price=payload.price,
    )
    return _to_visit_out(v)


@router.get("/visits", response_model=List[VisitOut])
def list_visits(
    day: date = Query(...),
    employee_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)

    q = db.query(Visit).filter(Visit.tenant_id == tenant.id, Visit.dt >= start, Visit.dt < end)
    if employee_name:
        q = q.join(Visit.employee).filter_by(name=employee_name, tenant_id=tenant.id)

    visits = q.order_by(Visit.dt.asc()).all()
    return [_to_visit_out(v) for v in visits]


@router.patch("/visits/{visit_id}", response_model=VisitOut)
def patch_visit(
    visit_id: int,
    payload: VisitUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    if payload.dt is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    visit = update_visit_datetime(db, tenant.id, visit_id, payload.dt)
    if not visit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return _to_visit_out(visit)


@router.delete("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_visit(
    visit_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    ok = delete_visit(db, tenant.id, visit_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/reservations", response_model=List[PublicReservationOut])
def list_reservations(
    status_filter: Optional[str] = Query(default=None, alias="status"),
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


@router.patch("/reservations/{reservation_id}/status", response_model=PublicReservationOut)
def patch_reservation_status(
    reservation_id: int,
    payload: ReservationStatusUpdate,
    x_actor_email: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        reservation = update_reservation_status(
            db=db,
            tenant_id=tenant.id,
            reservation_id=reservation_id,
            new_status=payload.status,
            actor=x_actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    return _to_reservation_out(tenant.slug, reservation)


@router.post("/reservations/{reservation_id}/convert", response_model=VisitOut)
def convert_reservation(
    reservation_id: int,
    payload: ReservationConvertCreate,
    x_actor_email: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
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
            actor=x_actor_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not reservation or not visit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    return _to_visit_out(visit)


@router.get("/reservations/{reservation_id}/history", response_model=list[ReservationStatusEventOut])
def reservation_status_history(
    reservation_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    reservation = get_reservation_by_id(db, tenant.id, reservation_id)
    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

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


@router.get("/summary/day", response_model=DaySummary)
def get_day_summary(
    day: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    total, count = day_summary(db, tenant.id, day)
    return DaySummary(date=day.isoformat(), total_revenue=total, visits_count=count)


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
        headers={"Content-Disposition": f"attachment; filename=report_{month_label}.pdf"},
    )


@public_router.post("/{tenant_slug}/reservations", response_model=PublicReservationOut)
def create_public_reservation_endpoint(
    tenant_slug: str,
    payload: PublicReservationCreate,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    tenant = db.execute(select(Tenant).where(Tenant.slug == tenant_slug.strip().lower())).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

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
    return _to_reservation_out(tenant.slug, reservation)
