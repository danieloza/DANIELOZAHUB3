from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, validator


class VisitCreate(BaseModel):
    dt: datetime
    client_name: str = Field(min_length=2, max_length=120)
    employee_name: str = Field(min_length=2, max_length=120)
    service_name: str = Field(min_length=2, max_length=120)
    price: float = Field(gt=0)


class VisitUpdate(BaseModel):
    dt: Optional[datetime] = None


class VisitOut(BaseModel):
    id: int
    dt: datetime
    client: str
    employee: str
    service: str
    price: float
    client_name: Optional[str] = None
    employee_name: Optional[str] = None
    service_name: Optional[str] = None
    duration_min: Optional[int] = None


class PublicReservationCreate(BaseModel):
    requested_dt: datetime
    client_name: str = Field(min_length=2, max_length=120)
    service_name: str = Field(min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, min_length=7, max_length=40)
    note: Optional[str] = Field(default=None, max_length=500)

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
    phone: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    converted_visit_id: Optional[int] = None
    converted_at: Optional[datetime] = None


class ReservationStatusUpdate(BaseModel):
    status: str


class ReservationConvertCreate(BaseModel):
    employee_name: str = Field(min_length=2, max_length=120)
    price: float = Field(gt=0)
    dt: Optional[datetime] = None
    client_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    service_name: Optional[str] = Field(default=None, min_length=2, max_length=120)


class ReservationStatusEventOut(BaseModel):
    id: int
    reservation_id: int
    from_status: Optional[str] = None
    to_status: str
    action: str
    actor: Optional[str] = None
    note: Optional[str] = None
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


