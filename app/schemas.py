from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, validator


class VisitCreate(BaseModel):
    dt: datetime
    client_name: str = Field(min_length=2, max_length=120)
    client_phone: str | None = Field(default=None, min_length=7, max_length=40)
    employee_name: str = Field(min_length=2, max_length=120)
    service_name: str = Field(min_length=2, max_length=120)
    price: float = Field(gt=0)
    duration_min: int | None = Field(default=None, ge=5, le=480)


class VisitUpdate(BaseModel):
    dt: datetime | None = None
    duration_min: int | None = Field(default=None, ge=5, le=480)


class VisitOut(BaseModel):
    id: int
    dt: datetime
    client: str
    employee: str
    service: str
    price: float
    source_reservation_id: int | None = None
    client_name: str | None = None
    employee_name: str | None = None
    service_name: str | None = None
    duration_min: int | None = None
    status: str = "planned"
    client_phone: str | None = None


class PublicReservationCreate(BaseModel):
    requested_dt: datetime
    client_name: str = Field(min_length=2, max_length=120)
    service_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=7, max_length=40)
    note: str | None = Field(default=None, max_length=500)

    @validator("requested_dt")
    @classmethod
    def validate_requested_dt_not_past(cls, value: datetime) -> datetime:
        now_utc = datetime.now(timezone.utc)
        candidate = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if candidate < now_utc:
            raise ValueError("requested_dt cannot be in the past")
        return value


class PublicReservationOut(BaseModel):
    id: int
    tenant_slug: str
    status: str
    requested_dt: datetime
    client_name: str
    service_name: str
    phone: str | None = None
    note: str | None = None
    created_at: datetime
    converted_visit_id: int | None = None
    converted_at: datetime | None = None


class ReservationStatusUpdate(BaseModel):
    status: str


class ReservationConvertCreate(BaseModel):
    employee_name: str = Field(min_length=2, max_length=120)
    price: float = Field(gt=0)
    dt: datetime | None = None
    client_name: str | None = Field(default=None, min_length=2, max_length=120)
    service_name: str | None = Field(default=None, min_length=2, max_length=120)


class ReservationStatusEventOut(BaseModel):
    id: int
    reservation_id: int
    from_status: str | None = None
    to_status: str
    action: str
    actor: str | None = None
    note: str | None = None
    created_at: datetime


class ReservationMetricsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    converted: int
    conversion_rate: float


class DaySummary(BaseModel):
    date: str
    total_revenue: float
    visits_count: int


class EmployeeCommissionRow(BaseModel):
    employee: str
    commission_pct: float
    revenue: float
    commission_amount: float


class MonthReport(BaseModel):
    month: str
    total_revenue: float
    visits_count: int
    by_employee: list[EmployeeCommissionRow]


class VisitStatusUpdate(BaseModel):
    status: str = Field(min_length=2, max_length=32)
    note: str | None = Field(default=None, max_length=300)


class VisitStatusEventOut(BaseModel):
    id: int
    visit_id: int
    from_status: str | None = None
    to_status: str
    actor: str | None = None
    note: str | None = None
    created_at: datetime


class TeamEmployeeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    commission_pct: float = Field(default=0.0, ge=0, le=100)


class TeamEmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    commission_pct: float | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    is_portfolio_public: bool | None = None


class PortfolioImageOut(BaseModel):
    id: int
    image_url: str
    description: str | None = None
    order_weight: int = 0
    created_at: datetime


class PortfolioImageCreate(BaseModel):
    image_url: str = Field(min_length=10, max_length=500)
    description: str | None = Field(default=None, max_length=200)
    order_weight: int = 0


class PortfolioImageUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=200)
    order_weight: int | None = None


class TeamEmployeeOut(BaseModel):
    id: int
    name: str
    commission_pct: float
    is_active: bool
    is_portfolio_public: bool
    portfolio: list[PortfolioImageOut] = []


class EmployeeWeeklyScheduleDaySet(BaseModel):
    weekday: int = Field(ge=0, le=6)
    is_day_off: bool = False
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)

    @validator("end_hour")
    @classmethod
    def validate_end_after_start(cls, value: int | None, values: dict):
        start_hour = values.get("start_hour")
        is_day_off = bool(values.get("is_day_off"))
        if is_day_off:
            return value
        if start_hour is not None and value is not None and value <= start_hour:
            raise ValueError("end_hour must be greater than start_hour")
        return value


class EmployeeWeeklyScheduleSet(BaseModel):
    days: list[EmployeeWeeklyScheduleDaySet] = Field(min_items=1, max_items=7)

    @validator("days")
    @classmethod
    def validate_unique_weekdays(cls, value: list[EmployeeWeeklyScheduleDaySet]):
        weekdays = [day.weekday for day in value]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("weekday must be unique")
        return value


class EmployeeWeeklyScheduleDayOut(BaseModel):
    weekday: int
    is_day_off: bool
    start_hour: int | None = None
    end_hour: int | None = None
    source: str


class EmployeeAvailabilitySet(BaseModel):
    employee_name: str = Field(min_length=2, max_length=120)
    day: date
    is_day_off: bool = False
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    note: str | None = Field(default=None, max_length=300)


class EmployeeAvailabilityOut(BaseModel):
    day: date
    employee_name: str
    is_day_off: bool
    start_hour: int | None = None
    end_hour: int | None = None
    source: str
    note: str | None = None


class EmployeeBlockCreate(BaseModel):
    employee_name: str = Field(min_length=2, max_length=120)
    start_dt: datetime
    end_dt: datetime
    reason: str | None = Field(default=None, max_length=300)

    @validator("end_dt")
    @classmethod
    def validate_end_after_start(cls, value: datetime, values: dict) -> datetime:
        start_dt = values.get("start_dt")
        if start_dt and value <= start_dt:
            raise ValueError("end_dt must be after start_dt")
        return value


class EmployeeBlockOut(BaseModel):
    id: int
    employee_name: str
    start_dt: datetime
    end_dt: datetime
    reason: str | None = None
    created_at: datetime


class BufferSet(BaseModel):
    before_min: int = Field(ge=0, le=180)
    after_min: int = Field(ge=0, le=180)


class BufferOut(BaseModel):
    target: str
    before_min: int
    after_min: int


class SlotRecommendationOut(BaseModel):
    start_dt: datetime
    end_dt: datetime
    employee_name: str
    service_name: str
    score: float


class ClientSearchOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    visits_count: int
    last_visit_dt: datetime | None = None


class ClientNoteCreate(BaseModel):
    note: str = Field(min_length=2, max_length=600)


class ClientNoteOut(BaseModel):
    id: int
    client_id: int
    note: str
    actor: str | None = None
    created_at: datetime


class ClientVisitHistoryOut(BaseModel):
    visit_id: int
    dt: datetime
    service_name: str
    employee_name: str
    price: float
    status: str


class ClientDetailOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    visits_count: int
    last_visit_dt: datetime | None = None
    notes: list[ClientNoteOut]
    visits: list[ClientVisitHistoryOut]


class DayPulseOut(BaseModel):
    day: date
    total_revenue: float
    visits_count: int
    conversion_rate: float
    reservations_new: int
    reservations_contacted: int
    visits_by_status: dict[str, int]
    occupancy_by_employee: dict[str, float]


class ReservationAssistantActionOut(BaseModel):
    reservation_id: int
    status: str
    requested_dt: datetime
    client_name: str
    service_name: str
    suggested_action: str
    priority: int


class ConversionIntegrityIssueOut(BaseModel):
    type: str
    reservation_id: int | None = None
    visit_id: int | None = None
    source_reservation_id: int | None = None
    detail: str


class ConversionIntegrityReportOut(BaseModel):
    ok: bool
    checked_at: datetime
    issues_count: int
    by_type: dict[str, int]
    truncated: bool
    issues: list[ConversionIntegrityIssueOut]


class OpsPathStatOut(BaseModel):
    path: str
    count: int


class OpsMetricsOut(BaseModel):
    window_minutes: int
    checked_at: datetime
    requests_total: int
    error_5xx_count: int
    timeout_like_count: int
    latency_ms_p50: float
    latency_ms_p95: float
    by_status_class: dict[str, int]
    top_paths: list[OpsPathStatOut]
    tenant_event_count: dict[str, int]


class OpsAlertOut(BaseModel):
    code: str
    severity: str
    message: str


class OpsStatusOut(BaseModel):
    checked_at: datetime
    metrics_window_minutes: int
    requests_total: int
    latency_ms_p95: float
    error_5xx_count: int
    alerts_count: int
    active_alert_codes: list[str]
    slo_total: int
    slo_ok: int
    slo_failed: int
    jobs_health: dict
    outbox_health: dict


class TenantUserRoleSet(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    role: str = Field(min_length=4, max_length=32)


class TenantUserRoleOut(BaseModel):
    email: str
    role: str
    created_at: datetime
    updated_at: datetime


class AuditLogOut(BaseModel):
    id: int
    actor_email: str | None = None
    actor_role: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    request_id: str | None = None
    payload_json: str | None = None
    created_at: datetime


class TenantPolicySet(BaseModel):
    value: dict


class TenantPolicyOut(BaseModel):
    key: str
    value: dict
    updated_by: str | None = None
    updated_at: datetime


class BackgroundJobCreate(BaseModel):
    job_type: str = Field(min_length=2, max_length=80)
    payload: dict = Field(default_factory=dict)
    queue: str = Field(default="default", min_length=2, max_length=40)
    max_attempts: int = Field(default=5, ge=1, le=20)


class BackgroundJobOut(BaseModel):
    id: int
    tenant_id: int | None = None
    queue: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None
    run_after: datetime
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BackgroundJobsHealthOut(BaseModel):
    tenant_id: int | None = None
    checked_at: datetime
    queued_count: int
    running_count: int
    succeeded_count: int
    dead_letter_count: int
    due_queued_count: int
    stale_running_count: int
    oldest_queued_age_seconds: int


class BackgroundJobCleanupOut(BaseModel):
    tenant_id: int
    deleted_jobs: int
    statuses: list[str]
    cutoff: datetime


class CalendarConnectionSet(BaseModel):
    provider: str = Field(min_length=3, max_length=32)
    external_calendar_id: str = Field(min_length=2, max_length=200)
    sync_direction: str = Field(default="bidirectional", min_length=3, max_length=32)
    webhook_secret: str | None = Field(default=None, max_length=120)
    outbound_webhook_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class CalendarConnectionOut(BaseModel):
    id: int
    provider: str
    external_calendar_id: str
    sync_direction: str
    webhook_secret: str | None = None
    outbound_webhook_url: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CalendarSyncEventOut(BaseModel):
    id: int
    provider: str
    source: str
    external_event_id: str | None = None
    visit_id: int | None = None
    action: str
    status: str
    retries: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class SloDefinitionSet(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    metric_type: str = Field(min_length=3, max_length=32)
    target: float
    window_minutes: int = Field(ge=1, le=1440)
    enabled: bool = True


class SloDefinitionOut(BaseModel):
    id: int
    name: str
    metric_type: str
    target: float
    window_minutes: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SloEvaluationOut(BaseModel):
    name: str
    metric_type: str
    window_minutes: int
    target: float
    current: float
    ok: bool
    checked_at: datetime


class AlertRouteSet(BaseModel):
    channel: str = Field(min_length=2, max_length=32)
    target: str = Field(min_length=3, max_length=500)
    min_severity: str = Field(default="medium", min_length=2, max_length=16)
    enabled: bool = True


class AlertRouteOut(BaseModel):
    id: int
    channel: str
    target: str
    min_severity: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertDispatchOut(BaseModel):
    alerts_count: int
    routes_count: int
    dispatched_jobs: int


class DataRetentionPolicySet(BaseModel):
    client_notes_days: int = Field(ge=1, le=3650)
    audit_logs_days: int = Field(ge=1, le=3650)
    status_events_days: int = Field(ge=1, le=3650)
    rate_limit_events_hours: int = Field(ge=1, le=8760)


class DataRetentionPolicyOut(BaseModel):
    client_notes_days: int
    audit_logs_days: int
    status_events_days: int
    rate_limit_events_hours: int
    updated_by: str | None = None
    updated_at: datetime


class DataRetentionCleanupOut(BaseModel):
    tenant_id: int
    deleted_client_notes: int
    deleted_audit_logs: int
    deleted_reservation_status_events: int
    deleted_visit_status_events: int
    deleted_rate_limit_events: int
    checked_at: datetime


class DataRetentionCleanupPreviewOut(BaseModel):
    tenant_id: int
    would_delete_client_notes: int
    would_delete_audit_logs: int
    would_delete_reservation_status_events: int
    would_delete_visit_status_events: int
    would_delete_rate_limit_events: int
    checked_at: datetime
