from datetime import date

EMPLOYEES = ["Magda", "Kamila", "Taja"]

# Base work hours per employee (start/end hour, end exclusive).
EMPLOYEE_WORK_HOURS = {
    "Magda": {"start": 9, "end": 18},
    "Kamila": {"start": 10, "end": 19},
    "Taja": {"start": 8, "end": 16},
}

# Weekday overrides per employee:
# weekday: 0=Mon ... 6=Sun
# value: {"start": int, "end": int} or None (day off)
EMPLOYEE_WEEKDAY_OVERRIDES = {
    "Magda": {
        5: {"start": 9, "end": 14},
        6: None,
    },
    "Kamila": {
        5: {"start": 10, "end": 15},
        6: None,
    },
    "Taja": {
        5: {"start": 8, "end": 13},
        6: None,
    },
}

SERVICE_DURATIONS = {
    "Strzyżenie": 30,
    "Koloryzacja": 120,
    "Tonowanie": 60,
    "Modelowanie": 45,
    "Inna": 30,
}

SERVICES = list(SERVICE_DURATIONS.keys())

PRICE_PRESETS = [150, 200, 250, 300, 320, 350, 400]

DEFAULT_DURATION_MIN = 30


def _parse_day(day_iso: str | None) -> date | None:
    if not day_iso:
        return None
    try:
        return date.fromisoformat(day_iso)
    except Exception:
        return None


def _normalize_hours(start: int, end: int) -> tuple[int, int]:
    start_i = int(start)
    end_i = int(end)
    if end_i <= start_i:
        return 9, 18
    return start_i, end_i


def get_employee_hours(
    employee_name: str, day_iso: str | None = None
) -> tuple[int, int] | None:
    base = EMPLOYEE_WORK_HOURS.get(employee_name) or {"start": 9, "end": 18}
    start_h, end_h = _normalize_hours(base.get("start", 9), base.get("end", 18))

    day = _parse_day(day_iso)
    if day is None:
        return start_h, end_h

    overrides = EMPLOYEE_WEEKDAY_OVERRIDES.get(employee_name) or {}
    if day.weekday() in overrides:
        rule = overrides[day.weekday()]
        if rule is None:
            return None
        return _normalize_hours(rule.get("start", start_h), rule.get("end", end_h))

    return start_h, end_h


def is_within_employee_hours(
    employee_name: str,
    hour: int,
    minute: int,
    duration_min: int,
    day_iso: str | None = None,
) -> bool:
    hours = get_employee_hours(employee_name, day_iso)
    if not hours:
        return False

    start_h, end_h = hours
    start_total = start_h * 60
    end_total = end_h * 60
    slot_start = (hour * 60) + minute
    slot_end = slot_start + int(duration_min)
    return start_total <= slot_start and slot_end <= end_total
