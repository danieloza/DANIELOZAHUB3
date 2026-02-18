# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta

from requests.exceptions import RequestException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.api import api_post, fetch_busy_intervals, overlaps
from bot.config import (
    DEFAULT_DURATION_MIN,
    SERVICE_DURATIONS,
    get_employee_hours,
    is_within_employee_hours,
)
from bot.keyboards import main_menu
from bot.ui_kb import (
    kb_calendar,
    kb_clients_step,
    kb_employees,
    kb_hours,
    kb_minutes_for_hour,
    kb_prices,
    kb_services,
    visit_summary,
)


def _hours_or_warn(emp: str, day_iso: str):
    hours = get_employee_hours(emp, day_iso)
    return hours


async def handle_visit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    q = update.callback_query

    if data == "ADD_VISIT":
        context.user_data["visit_draft"] = {}
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False
        await q.message.reply_text("Wybierz fryzjerkę:", reply_markup=kb_employees())
        return True

    if not data.startswith("V:"):
        return False

    if data == "V:NOOP":
        return True

    if data == "V:CANCEL":
        context.user_data.pop("visit_draft", None)
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False
        await q.message.reply_text("Anulowano.", reply_markup=main_menu())
        return True

    if data.startswith("V:MON_PREV:") or data.startswith("V:MON_NEXT:"):
        ym = data.split(":")[-1]
        y, m = map(int, ym.split("-"))
        cur = date(y, m, 1)
        target = (cur - timedelta(days=1)).replace(day=1) if data.startswith("V:MON_PREV:") else (cur + timedelta(days=32)).replace(day=1)
        await q.message.reply_text("Wybierz datę wizyty:", reply_markup=kb_calendar(target.year, target.month))
        return True

    if data == "V:BACK_DATE":
        today = date.today()
        await q.message.reply_text("Wybierz datę wizyty:", reply_markup=kb_calendar(today.year, today.month))
        return True

    if data.startswith("V:DATE:"):
        day_iso = data.split("V:DATE:")[1]
        d = context.user_data.setdefault("visit_draft", {})
        d["date"] = day_iso
        d.pop("hour", None)
        d.pop("time", None)

        emp = d.get("employee_name")
        if emp:
            hours = _hours_or_warn(emp, day_iso)
            if not hours:
                await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu. Wybierz inną datę.")
                return True
            start_h, end_h = hours
            await q.message.reply_text("Wybierz godzinę:", reply_markup=kb_hours(start_h, end_h - 1))
        else:
            await q.message.reply_text("Wybierz godzinę:", reply_markup=kb_hours())
        return True

    if data.startswith("V:HOUR:"):
        hour = int(data.split("V:HOUR:")[1])
        d = context.user_data.setdefault("visit_draft", {})
        d["hour"] = hour
        emp = d.get("employee_name") or ""
        day_iso = d.get("date")
        hours = get_employee_hours(emp, day_iso) if emp and day_iso else get_employee_hours(emp)
        if not hours:
            await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu. Wybierz inną datę.")
            return True
        _, end_h = hours
        await q.message.reply_text("Wybierz minuty:", reply_markup=kb_minutes_for_hour(hour, end_h))
        return True

    if data == "V:BACK_HOUR":
        d = context.user_data.setdefault("visit_draft", {})
        emp = d.get("employee_name")
        day_iso = d.get("date")
        if emp and day_iso:
            hours = get_employee_hours(emp, day_iso)
            if not hours:
                await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu. Wybierz inną datę.")
                return True
            start_h, end_h = hours
            await q.message.reply_text("Wybierz godzinę:", reply_markup=kb_hours(start_h, end_h - 1))
        else:
            await q.message.reply_text("Wybierz godzinę:", reply_markup=kb_hours())
        return True

    if data.startswith("V:MIN:"):
        minute = int(data.split("V:MIN:")[1])
        d = context.user_data.setdefault("visit_draft", {})
        hour = d.get("hour")
        day_iso = d.get("date")
        emp = d.get("employee_name")

        if hour is None:
            await q.message.reply_text("⚠️ Najpierw wybierz godzinę.")
            return True
        if not day_iso or not emp:
            await q.message.reply_text("⚠️ Najpierw wybierz fryzjerkę i datę.", reply_markup=kb_employees())
            return True

        dur = int(d.get("duration_min") or DEFAULT_DURATION_MIN)
        if not is_within_employee_hours(emp, int(hour), int(minute), dur, day_iso):
            hours = get_employee_hours(emp, day_iso)
            if not hours:
                await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu. Wybierz inną datę.")
                return True
            _, end_h = hours
            await q.message.reply_text(
                f"⛔ Termin wypada poza godzinami pracy {emp}.\nWybierz inne minuty:",
                reply_markup=kb_minutes_for_hour(int(hour), end_h),
            )
            return True

        start_dt = datetime.strptime(f"{day_iso} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=dur)

        busy = fetch_busy_intervals(day_iso, emp, DEFAULT_DURATION_MIN)
        for b_start, b_end in busy:
            if overlaps(start_dt, end_dt, b_start, b_end):
                _, end_h = get_employee_hours(emp, day_iso) or (9, 18)
                await q.message.reply_text(
                    f"⛔ Ten termin jest zajęty ({emp}).\nWybierz inne minuty:",
                    reply_markup=kb_minutes_for_hour(int(hour), end_h),
                )
                return True

        d["time"] = f"{hour:02d}:{minute:02d}"
        await q.message.reply_text(
            f"✅ Termin: {day_iso} {d['time']}\n💇 Fryzjerka: {emp}\n\nWybierz klienta (opcjonalnie):",
            reply_markup=kb_clients_step(),
        )
        return True

    if data == "V:CLIENT_SKIP":
        context.user_data.setdefault("visit_draft", {})["client_name"] = None
        await q.message.reply_text("Wybierz usługę:", reply_markup=kb_services())
        return True

    if data == "V:CLIENT_TEXT":
        context.user_data["awaiting_client_text"] = True
        await q.message.reply_text("Wpisz imię i nazwisko klienta (albo '-' żeby pominąć):")
        return True

    if data.startswith("V:SVC:"):
        svc = data.split("V:SVC:")[1]
        d = context.user_data.setdefault("visit_draft", {})
        d["service_name"] = svc
        d["duration_min"] = int(SERVICE_DURATIONS.get(svc) or DEFAULT_DURATION_MIN)
        await q.message.reply_text("Wybierz cenę:", reply_markup=kb_prices())
        return True

    if data.startswith("V:EMP:"):
        emp = data.split("V:EMP:")[1]
        d = context.user_data.setdefault("visit_draft", {})
        d["employee_name"] = emp
        if not d.get("date"):
            today = date.today()
            await q.message.reply_text("Wybierz datę wizyty:", reply_markup=kb_calendar(today.year, today.month))
            return True

        day_iso = d.get("date")
        hours = get_employee_hours(emp, day_iso)
        if not hours:
            await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu. Wybierz inną datę.", reply_markup=kb_calendar(date.today().year, date.today().month))
            return True
        start_h, end_h = hours
        await q.message.reply_text("Wybierz godzinę:", reply_markup=kb_hours(start_h, end_h - 1))
        return True

    if data.startswith("V:PRICE:"):
        price = float(data.split("V:PRICE:")[1])
        d = context.user_data.setdefault("visit_draft", {})
        d["price"] = price
        await q.message.reply_text(
            visit_summary(d) + "\nZapisać?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Zapisz", callback_data="V:SAVE")],
                    [InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")],
                ]
            ),
        )
        return True

    if data == "V:PRICE_TEXT":
        context.user_data["awaiting_price_text"] = True
        await q.message.reply_text("Wpisz cenę (np. 320):")
        return True

    if data == "V:SAVE":
        d = context.user_data.get("visit_draft") or {}
        try:
            dt = datetime.strptime(f"{d['date']} {d['time']}", "%Y-%m-%d %H:%M")
            payload = {
                "dt": dt.isoformat(),
                "client_name": d.get("client_name") or "",
                "employee_name": d["employee_name"],
                "service_name": d["service_name"],
                "price": float(d["price"]),
                "duration_min": int(d.get("duration_min") or DEFAULT_DURATION_MIN),
            }
        except Exception:
            await q.message.reply_text("⚠️ Brak danych w kreatorze. Zacznij od nowa: /menu", reply_markup=main_menu())
            return True

        try:
            v = api_post("/api/visits", payload)
            await q.message.reply_text(f"✅ Dodano wizytę #{v.get('id', '?')}", reply_markup=main_menu())
        except RequestException:
            await q.message.reply_text("⚠️ Nie mogę połączyć się z API.", reply_markup=main_menu())

        context.user_data.pop("visit_draft", None)
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False
        return True

    await q.message.reply_text("⚠️ Nieznana akcja kreatora.", reply_markup=main_menu())
    return True


async def handle_visit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("awaiting_client_text"):
        txt = (update.message.text or "").strip()
        context.user_data["awaiting_client_text"] = False
        context.user_data.setdefault("visit_draft", {})["client_name"] = None if txt in ("", "-") else txt
        await update.message.reply_text("Wybierz usługę:", reply_markup=kb_services())
        return True

    if context.user_data.get("awaiting_price_text"):
        txt = (update.message.text or "").strip().replace(",", ".")
        try:
            price = float(txt)
            if price <= 0:
                raise ValueError("price<=0")
        except Exception:
            await update.message.reply_text("Podaj poprawną cenę, np. 320")
            return True

        context.user_data["awaiting_price_text"] = False
        d = context.user_data.setdefault("visit_draft", {})
        d["price"] = price
        await update.message.reply_text(
            visit_summary(d) + "\nZapisać?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Zapisz", callback_data="V:SAVE")],
                    [InlineKeyboardButton("❌ Anuluj", callback_data="V:CANCEL")],
                ]
            ),
        )
        return True

    return False


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    return await handle_visit_callback(update, context, data)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await handle_visit_text(update, context)
