from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_clients_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_employees_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    commission_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_services_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    default_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    dt: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    client = relationship("Client")
    employee = relationship("Employee")
    service = relationship("Service")


class ReservationRequest(Base):
    __tablename__ = "reservation_requests"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_reservation_tenant_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    requested_dt: Mapped[datetime] = mapped_column(DateTime, index=True)
    client_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    service_name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    converted_visit_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ReservationStatusEvent(Base):
    __tablename__ = "reservation_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservation_requests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(40), default="status_update")
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
