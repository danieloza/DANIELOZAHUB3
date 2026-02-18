# -*- coding: utf-8 -*-

import calendar
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import DEFAULT_DURATION_MIN, EMPLOYEES, PRICE_PRESETS, SERVICE_DURATIONS, SERVICES


def kb_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    cal = calendar.monthcalendar(year, month)

    header = [
        InlineKeyboardButton("◀️", callback_data=f"V:MON_PREV:{year}-{month:02d}"),
        InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="V:NOOP"),
        InlineKeyboardButton("▶️", callback_data=f"V:MON_NEXT:{year}-{month:02d}"),
    ]
    week_days = [InlineKeyboardButton(d, callback_data="V:NOOP") for d in ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]]

    rows = [header, week_days]
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="V:NOOP"))
            else:
                d = date(year, month, day).isoformat()
                row.append(InlineKeyboardButton(str(day), callback_data=f"V:DATE:{d}"))
        rows.append(row)

    rows.append([InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")])
    return InlineKeyboardMarkup(rows)


def kb_hours(start_h: int = 9, end_h: int = 18) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(start_h, end_h + 1):
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"V:HOUR:{h:02d}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("⬅️ Data", callback_data="V:BACK_DATE"),
            InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def kb_minutes_for_hour(hour: int, end_h: int = 19) -> InlineKeyboardMarkup:
    minutes = list(range(0, 60, 5))
    if hour == (end_h - 1):
        minutes = [m for m in minutes if m <= 45]

    rows, row = [], []
    for m in minutes:
        row.append(InlineKeyboardButton(f"{m:02d}", callback_data=f"V:MIN:{m:02d}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("⬅️ Godzina", callback_data="V:BACK_HOUR"),
            InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def kb_clients_step() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Pomiń klienta", callback_data="V:CLIENT_SKIP")],
            [InlineKeyboardButton("✍️ Wpisz klienta", callback_data="V:CLIENT_TEXT")],
            [InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")],
        ]
    )


def kb_services() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, s in enumerate(SERVICES, 1):
        dur = int(SERVICE_DURATIONS.get(s) or DEFAULT_DURATION_MIN)
        row.append(InlineKeyboardButton(f"{s} ({dur}m)", callback_data=f"V:SVC:{s}"))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")])
    return InlineKeyboardMarkup(rows)


def kb_employees() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(e, callback_data=f"V:EMP:{e}")] for e in EMPLOYEES]
    rows.append([InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")])
    return InlineKeyboardMarkup(rows)


def kb_prices() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, p in enumerate(PRICE_PRESETS, 1):
        row.append(InlineKeyboardButton(f"{p} zł", callback_data=f"V:PRICE:{p}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✍️ Wpisz ręcznie", callback_data="V:PRICE_TEXT")])
    rows.append([InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")])
    return InlineKeyboardMarkup(rows)


def visit_summary(d: dict) -> str:
    client = d.get("client_name") or "— (pominięto)"
    dur = int(d.get("duration_min") or DEFAULT_DURATION_MIN)
    return (
        "🧾 Podsumowanie wizyty:\n"
        f"📅 {d.get('date')} {d.get('time')}\n"
        f"👤 Klient: {client}\n"
        f"✂️ Usługa: {d.get('service_name')} ({dur} min)\n"
        f"💇 Fryzjerka: {d.get('employee_name')}\n"
        f"💰 Cena: {d.get('price')} zł\n"
    )


# Widok dnia (D:)
def kb_day_employees(day_iso: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📅 Dziś → {e}", callback_data=f"D:EMP:{day_iso}:{e}")] for e in EMPLOYEES]
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="D:BACK_MENU")])
    return InlineKeyboardMarkup(rows)


def kb_day_actions(day_iso: str, employee_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Dodaj", callback_data=f"D:ADD:{day_iso}:{employee_name}")],
            [InlineKeyboardButton("🗑️ Anuluj wizytę", callback_data=f"D:CANCEL_SELECT:{day_iso}:{employee_name}")],
            [InlineKeyboardButton("🕒 Przełóż wizytę", callback_data=f"D:MOVE_SELECT:{day_iso}:{employee_name}")],
            [InlineKeyboardButton("⬅️ Zmień osobę", callback_data=f"D:CHOOSE:{day_iso}")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="D:BACK_MENU")],
        ]
    )


def kb_day_cancel_list(day_iso: str, employee_name: str, visits: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for v in visits:
        visit_id = int(v.get("id"))
        try:
            hhmm = datetime.fromisoformat(v.get("dt", "")).strftime("%H:%M")
        except Exception:
            hhmm = "??:??"
        client = (v.get("client") or v.get("client_name") or "").strip() or "-"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{hhmm} {client}",
                    callback_data=f"D:CANCEL_CONFIRM:{visit_id}:{day_iso}:{employee_name}",
                )
            ]
        )

    rows.append([InlineKeyboardButton("⬅️ Powrót", callback_data=f"D:EMP:{day_iso}:{employee_name}")])
    return InlineKeyboardMarkup(rows)


def kb_day_cancel_confirm(day_iso: str, employee_name: str, visit_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Tak, anuluj", callback_data=f"D:CANCEL_DO:{visit_id}:{day_iso}:{employee_name}")],
            [InlineKeyboardButton("❌ Nie", callback_data=f"D:EMP:{day_iso}:{employee_name}")],
        ]
    )


def kb_day_move_list(day_iso: str, employee_name: str, visits: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for v in visits:
        visit_id = int(v.get("id"))
        try:
            hhmm = datetime.fromisoformat(v.get("dt", "")).strftime("%H:%M")
        except Exception:
            hhmm = "??:??"
        client = (v.get("client") or v.get("client_name") or "").strip() or "-"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{hhmm} {client}",
                    callback_data=f"D:MOVE_PICK:{visit_id}:{day_iso}:{employee_name}",
                )
            ]
        )

    rows.append([InlineKeyboardButton("⬅️ Powrót", callback_data=f"D:EMP:{day_iso}:{employee_name}")])
    return InlineKeyboardMarkup(rows)


def kb_move_calendar(year: int, month: int, source_day: str, employee_name: str) -> InlineKeyboardMarkup:
    cal = calendar.monthcalendar(year, month)

    header = [
        InlineKeyboardButton("◀️", callback_data=f"D:MOVE_MON_PREV:{year}-{month:02d}:{source_day}:{employee_name}"),
        InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="D:MOVE_NOOP"),
        InlineKeyboardButton("▶️", callback_data=f"D:MOVE_MON_NEXT:{year}-{month:02d}:{source_day}:{employee_name}"),
    ]
    week_days = [InlineKeyboardButton(d, callback_data="D:MOVE_NOOP") for d in ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]]

    rows = [header, week_days]
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="D:MOVE_NOOP"))
            else:
                d = date(year, month, day).isoformat()
                row.append(InlineKeyboardButton(str(day), callback_data=f"D:MOVE_DATE:{d}:{source_day}:{employee_name}"))
        rows.append(row)

    rows.append([InlineKeyboardButton("⬅️ Powrót", callback_data=f"D:EMP:{source_day}:{employee_name}")])
    return InlineKeyboardMarkup(rows)


def kb_move_hours(day_iso: str, source_day: str, employee_name: str, start_h: int, end_h: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(start_h, end_h):
        row.append(
            InlineKeyboardButton(
                f"{h:02d}",
                callback_data=f"D:MOVE_HOUR:{h:02d}:{day_iso}:{source_day}:{employee_name}",
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("⬅️ Data", callback_data=f"D:MOVE_BACK_DATE:{day_iso}:{source_day}:{employee_name}"),
            InlineKeyboardButton("⬅️ Powrót", callback_data=f"D:EMP:{source_day}:{employee_name}"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def kb_move_minutes(hour: int, day_iso: str, source_day: str, employee_name: str, end_h: int) -> InlineKeyboardMarkup:
    minutes = list(range(0, 60, 5))
    if hour == (end_h - 1):
        minutes = [m for m in minutes if m <= 45]

    rows, row = [], []
    for m in minutes:
        row.append(
            InlineKeyboardButton(
                f"{m:02d}",
                callback_data=f"D:MOVE_MIN:{m:02d}:{day_iso}:{source_day}:{employee_name}",
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("⬅️ Godzina", callback_data=f"D:MOVE_BACK_HOUR:{day_iso}:{source_day}:{employee_name}"),
            InlineKeyboardButton("⬅️ Powrót", callback_data=f"D:EMP:{source_day}:{employee_name}"),
        ]
    )
    return InlineKeyboardMarkup(rows)


