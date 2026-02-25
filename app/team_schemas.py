from datetime import date, datetime

from pydantic import BaseModel, Field, validator


class TeamEmployeeCapabilitySet(BaseModel):
    service_name: str = Field(min_length=2, max_length=120)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    price_override: float | None = Field(default=None, ge=0)
    is_active: bool = True


class TeamEmployeeCapabilityOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    service_name: str
    duration_min: int | None = None
    price_override: float | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TeamLeaveCreate(BaseModel):
    employee_id: int = Field(gt=0)
    start_day: date
    end_day: date
    reason: str | None = Field(default=None, max_length=500)

    @validator("end_day")
    @classmethod
    def validate_end_after_start(cls, value: date, values: dict):
        start_day = values.get("start_day")
        if start_day and value < start_day:
            raise ValueError("end_day must be >= start_day")
        return value


class TeamLeaveDecision(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|canceled)$")
    decision_note: str | None = Field(default=None, max_length=500)


class TeamLeaveOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    start_day: date
    end_day: date
    status: str
    reason: str | None = None
    requested_by: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TeamWeeklyApplyRangeIn(BaseModel):
    start_day: date
    end_day: date

    @validator("end_day")
    @classmethod
    def validate_end_after_start(cls, value: date, values: dict):
        start_day = values.get("start_day")
        if start_day and value < start_day:
            raise ValueError("end_day must be >= start_day")
        return value


class TeamSwapCreate(BaseModel):
    shift_day: date
    from_employee_id: int = Field(gt=0)
    to_employee_id: int = Field(gt=0)
    from_start_hour: int = Field(default=9, ge=0, le=23)
    from_end_hour: int = Field(default=18, ge=1, le=24)
    to_start_hour: int = Field(default=9, ge=0, le=23)
    to_end_hour: int = Field(default=18, ge=1, le=24)
    reason: str | None = Field(default=None, max_length=500)

    @validator("from_end_hour")
    @classmethod
    def validate_from_hours(cls, value: int, values: dict):
        if "from_start_hour" in values and value <= int(values["from_start_hour"]):
            raise ValueError("from_end_hour must be > from_start_hour")
        return value

    @validator("to_end_hour")
    @classmethod
    def validate_to_hours(cls, value: int, values: dict):
        if "to_start_hour" in values and value <= int(values["to_start_hour"]):
            raise ValueError("to_end_hour must be > to_start_hour")
        return value


class TeamSwapDecision(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|canceled)$")
    decision_note: str | None = Field(default=None, max_length=500)


class TeamSwapOut(BaseModel):
    id: int
    shift_day: date
    from_employee_id: int
    from_employee_name: str
    to_employee_id: int
    to_employee_name: str
    from_start_hour: int
    from_end_hour: int
    to_start_hour: int
    to_end_hour: int
    status: str
    reason: str | None = None
    requested_by: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TeamVisitReassignIn(BaseModel):
    to_employee_id: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=300)


class TeamTimeClockIn(BaseModel):
    employee_id: int = Field(gt=0)
    event_type: str = Field(pattern="^(check_in|check_out)$")
    event_dt: datetime | None = None
    source: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=300)


class TeamTimeClockOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    event_type: str
    event_dt: datetime
    source: str | None = None
    note: str | None = None
    created_at: datetime


class TeamTimeClockDayRowOut(BaseModel):
    employee_id: int
    employee_name: str
    planned_start_hour: int | None = None
    planned_end_hour: int | None = None
    first_check_in: datetime | None = None
    last_check_out: datetime | None = None
    late_minutes: int
    overtime_minutes: int
    worked_minutes: int


class ScheduleAuditOut(BaseModel):
    id: int
    action: str
    actor_email: str | None = None
    employee_id: int | None = None
    related_id: str | None = None
    payload_json: str | None = None
    created_at: datetime


class ScheduleNotificationOut(BaseModel):
    id: int
    employee_id: int | None = None
    employee_name: str | None = None
    event_type: str
    message: str
    channel: str
    status: str
    last_error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleNotificationSetStatus(BaseModel):
    status: str = Field(pattern="^(pending|sent|failed)$")
    last_error: str | None = Field(default=None, max_length=500)
