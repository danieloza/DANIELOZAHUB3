from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    
    # Senior IT: Premium Profile Fields
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(200), nullable=True) # e.g. "Najlepsze paznokcie w mieście"
    about_us: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    google_maps_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Social Media
    instagram_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Contact
    contact_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    
    # Meta
    industry_type: Mapped[str] = mapped_column(String(50), default="general_beauty") # hair, nails, tattoo
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), default=5.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_clients_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    
    # Senior IT: Loyalty System
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)
    visits_count: Mapped[int] = mapped_column(Integer, default=0)
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_employees_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    specialties: Mapped[str | None] = mapped_column(String(200), nullable=True) # CSV or JSON
    rating: Mapped[float] = mapped_column(Numeric(3, 2), default=5.0)
    commission_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_portfolio_public: Mapped[bool] = mapped_column(Boolean, default=True)

    portfolio: Mapped[list["EmployeePortfolioImage"]] = relationship(
        "EmployeePortfolioImage", back_populates="employee"
    )


class EmployeePortfolioImage(Base):
    __tablename__ = "employee_portfolio_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    image_url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_weight: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="portfolio")


class EmployeeWeeklySchedule(Base):
    __tablename__ = "employee_weekly_schedules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employee_id", "weekday", name="uq_employee_weekly_schedule"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    is_day_off: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EmployeeServiceCapability(Base):
    __tablename__ = "employee_service_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "service_name",
            name="uq_employee_service_capability",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    service_name: Mapped[str] = mapped_column(String(120), index=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_override: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class EmployeeLeaveRequest(Base):
    __tablename__ = "employee_leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    start_day: Mapped[date] = mapped_column(Date, index=True)
    end_day: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class ShiftSwapRequest(Base):
    __tablename__ = "shift_swap_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    shift_day: Mapped[date] = mapped_column(Date, index=True)
    from_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True
    )
    to_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    from_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    from_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    to_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    to_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class TimeClockEntry(Base):
    __tablename__ = "time_clock_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    event_dt: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class ScheduleAuditEvent(Base):
    __tablename__ = "schedule_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    actor_email: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )
    related_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class ScheduleNotification(Base):
    __tablename__ = "schedule_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(String(500))
    channel: Mapped[str] = mapped_column(String(32), default="internal", index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_services_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    default_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)


class Workstation(Base):
    __tablename__ = "workstations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80)) # e.g. "Fotel 1", "Gabinet VIP"
    type: Mapped[str] = mapped_column(String(40)) # chair, bed, desk
    pos_x: Mapped[int] = mapped_column(Integer, default=0) # percentage for grid
    pos_y: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1) # How many items we have
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_reservation_id",
            name="uq_visits_tenant_source_reservation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    dt: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    source_reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation_requests.id"), nullable=True, index=True
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)

    client = relationship("Client")
    employee = relationship("Employee")
    service = relationship("Service")


class ReservationRequest(Base):
    __tablename__ = "reservation_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_reservation_tenant_idempotency"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    requested_dt: Mapped[datetime] = mapped_column(DateTime, index=True)
    client_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    service_name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    converted_visit_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ReservationStatusEvent(Base):
    __tablename__ = "reservation_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservation_requests.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(40), default="status_update")
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class VisitStatusEvent(Base):
    __tablename__ = "visit_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class VisitInvoice(Base):
    __tablename__ = "visit_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id"), unique=True, index=True
    )
    external_invoice_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    visit = relationship("Visit")


class EmployeeAvailabilityDay(Base):
    __tablename__ = "employee_availability_days"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "employee_name",
            "day",
            name="uq_availability_tenant_employee_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_name: Mapped[str] = mapped_column(String(120), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    is_day_off: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class EmployeeBlock(Base):
    __tablename__ = "employee_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_name: Mapped[str] = mapped_column(String(120), index=True)
    start_dt: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_dt: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class ServiceBuffer(Base):
    __tablename__ = "service_buffers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "service_name", name="uq_service_buffer_tenant_service"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    service_name: Mapped[str] = mapped_column(String(120), index=True)
    before_min: Mapped[int] = mapped_column(Integer, default=0)
    after_min: Mapped[int] = mapped_column(Integer, default=0)


class EmployeeBuffer(Base):
    __tablename__ = "employee_buffers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employee_name", name="uq_employee_buffer_tenant_employee"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    employee_name: Mapped[str] = mapped_column(String(120), index=True)
    before_min: Mapped[int] = mapped_column(Integer, default=0)
    after_min: Mapped[int] = mapped_column(Integer, default=0)


class ClientNote(Base):
    __tablename__ = "client_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    note: Mapped[str] = mapped_column(String(600))
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class ReservationRateLimitEvent(Base):
    __tablename__ = "reservation_rate_limit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)


class TenantUserRole(Base):
    __tablename__ = "tenant_user_roles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "email", name="uq_tenant_user_roles_tenant_email"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_email: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class TenantPolicy(Base):
    __tablename__ = "tenant_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_policies_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    queue: Mapped[str] = mapped_column(String(40), default="default", index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "external_calendar_id",
            name="uq_calendar_connection_unique",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    external_calendar_id: Mapped[str] = mapped_column(String(200), index=True)
    sync_direction: Mapped[str] = mapped_column(String(32), default="bidirectional")
    webhook_secret: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outbound_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class CalendarSyncEvent(Base):
    __tablename__ = "calendar_sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(20), default="salonos", index=True)
    external_event_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        ForeignKey("visits.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class SloDefinition(Base):
    __tablename__ = "slo_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_slo_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    metric_type: Mapped[str] = mapped_column(String(32), index=True)
    target: Mapped[float] = mapped_column(Numeric(8, 4), default=0)
    window_minutes: Mapped[int] = mapped_column(Integer, default=15)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class AlertRoute(Base):
    __tablename__ = "alert_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    target: Mapped[str] = mapped_column(String(500))
    min_severity: Mapped[str] = mapped_column(String(16), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_data_retention_policy_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_notes_days: Mapped[int] = mapped_column(Integer, default=365)
    audit_logs_days: Mapped[int] = mapped_column(Integer, default=365)
    status_events_days: Mapped[int] = mapped_column(Integer, default=365)
    rate_limit_events_hours: Mapped[int] = mapped_column(Integer, default=24)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class AuthUser(Base):
    __tablename__ = "auth_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_auth_users_tenant_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(160), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="reception", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), index=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_slug",
            "method",
            "path",
            "idempotency_key",
            name="uq_idempotency_scope_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_slug: Mapped[str] = mapped_column(String(80), index=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    method: Mapped[str] = mapped_column(String(8), index=True)
    path: Mapped[str] = mapped_column(String(300), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), index=True)
    request_hash: Mapped[str] = mapped_column(String(128), index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    response_body_b64: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    topic: Mapped[str] = mapped_column(String(80), index=True)
    key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "flag_key", name="uq_feature_flags_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    flag_key: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rollout_pct: Mapped[int] = mapped_column(Integer, default=0)
    allowlist_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class NoShowPolicy(Base):
    __tablename__ = "no_show_policies"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_no_show_policy_tenant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fee_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation_requests.id"), nullable=True, index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        ForeignKey("visits.id"), nullable=True, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="PLN")
    reason: Mapped[str] = mapped_column(String(80), default="deposit", index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, index=True
    )
