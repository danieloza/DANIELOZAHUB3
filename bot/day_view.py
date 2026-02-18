# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta

from requests.exceptions import RequestException
from telegram import Update
from telegram.ext import ContextTypes

from bot.api import api_delete, api_patch, fetch_busy_intervals, fetch_visits_for_day, overlaps
from bot.config import DEFAULT_DURATION_MIN, get_employee_hours, is_within_employee_hours
from bot.keyboards import main_menu
from bot.ui_kb import (
    kb_day_actions,
    kb_day_cancel_confirm,
    kb_day_cancel_list,
    kb_day_employees,
    kb_day_move_list,
    kb_hours,
    kb_move_calendar,
    kb_move_hours,
    kb_move_minutes,
)


def render_day_view(day_iso: str, employee_name: str) -> str:
    visits = fetch_visits_for_day(day_iso, employee_name)
    lines = [f"Day {day_iso} - {employee_name}"]

    if not visits:
        lines.append("")
        lines.append("No visits.")
        return "\n".join(lines)

    def _parse_dt(v):
        try:
            return datetime.fromisoformat(v.get("dt", ""))
        except Exception:
            return datetime.min

    visits_sorted = sorted(visits, key=_parse_dt)
    lines.append("")

    for v in visits_sorted:
        try:
            dt = datetime.fromisoformat(v.get("dt", ""))
            hhmm = dt.strftime("%H:%M")
        except Exception:
            hhmm = "??:??"

        client = (v.get("client") or v.get("client_name") or "").strip() or "-"
        service = (v.get("service") or v.get("service_name") or "").strip() or "-"
        dur = int(v.get("duration_min") or DEFAULT_DURATION_MIN)

        price = v.get("price", None)
        price_txt = "-"
        if price is not None and str(price) != "":
            try:
                price_txt = f"{float(price):.0f} PLN"
            except Exception:
                price_txt = str(price)

        lines.append(f"- {hhmm} | {client} | {service} ({dur}m) | {price_txt}")

    return "\n".join(lines)


async def handle_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    q = update.callback_query

    if data == "TODAY":
        day_iso = date.today().isoformat()
        await q.message.reply_text("Select employee (today):", reply_markup=kb_day_employees(day_iso))
        return True

    if not data.startswith("D:"):
        return False

    if data.startswith("D:CHOOSE:"):
        day_iso = data.split("D:CHOOSE:")[1]
        await q.message.reply_text("Select employee (today):", reply_markup=kb_day_employees(day_iso))
        return True

    if data.startswith("D:EMP:"):
        _, _, day_iso, emp = data.split(":", 3)
        text = render_day_view(day_iso, emp)
        await q.message.reply_text(text, reply_markup=kb_day_actions(day_iso, emp))
        return True

    if data.startswith("D:ADD:"):
        _, _, day_iso, emp = data.split(":", 3)

        context.user_data["visit_draft"] = {
            "date": day_iso,
            "employee_name": emp,
        }
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False

        hours = get_employee_hours(emp, day_iso)
        if not hours:
            await q.message.reply_text(f"⛔ {emp} nie pracuje w tym dniu.", reply_markup=kb_day_actions(day_iso, emp))
            return True

        start_h, end_h = hours
        await q.message.reply_text(
            f"Add visit\nDate: {day_iso}\nEmployee: {emp}\n\nSelect hour:",
            reply_markup=kb_hours(start_h, end_h - 1),
        )
        return True

    if data.startswith("D:CANCEL_SELECT:"):
        _, _, _, day_iso, emp = data.split(":", 4)
        visits = fetch_visits_for_day(day_iso, emp)
        if not visits:
            await q.message.reply_text("No visits to cancel.", reply_markup=kb_day_actions(day_iso, emp))
            return True
        await q.message.reply_text("Select visit to cancel:", reply_markup=kb_day_cancel_list(day_iso, emp, visits))
        return True

    if data.startswith("D:CANCEL_CONFIRM:"):
        _, _, _, visit_id, day_iso, emp = data.split(":", 5)
        await q.message.reply_text(
            f"Cancel visit #{visit_id}?",
            reply_markup=kb_day_cancel_confirm(day_iso, emp, int(visit_id)),
        )
        return True

    if data.startswith("D:CANCEL_DO:"):
        _, _, _, visit_id, day_iso, emp = data.split(":", 5)
        try:
            api_delete(f"/api/visits/{int(visit_id)}")
            text = render_day_view(day_iso, emp)
            await q.message.reply_text("Visit canceled.\n\n" + text, reply_markup=kb_day_actions(day_iso, emp))
        except RequestException:
            await q.message.reply_text("Could not cancel visit (API error).", reply_markup=kb_day_actions(day_iso, emp))
        return True

    if data.startswith("D:MOVE_SELECT:"):
        _, _, _, day_iso, emp = data.split(":", 4)
        visits = fetch_visits_for_day(day_iso, emp)
        if not visits:
            await q.message.reply_text("No visits to move.", reply_markup=kb_day_actions(day_iso, emp))
            return True
        await q.message.reply_text("Select visit to move:", reply_markup=kb_day_move_list(day_iso, emp, visits))
        return True

    if data.startswith("D:MOVE_PICK:"):
        _, _, _, visit_id, source_day, emp = data.split(":", 5)
        context.user_data["move_visit_id"] = int(visit_id)
        context.user_data["move_hour"] = None
        context.user_data["move_source_day"] = source_day

        original_dt = None
        for v in fetch_visits_for_day(source_day, emp):
            if int(v.get("id")) == int(visit_id):
                try:
                    original_dt = datetime.fromisoformat(v.get("dt", ""))
                except Exception:
                    original_dt = None
                break

        if original_dt is None:
            original_dt = datetime.combine(date.fromisoformat(source_day), datetime.min.time())

        context.user_data["move_original_dt"] = original_dt.isoformat()
        context.user_data["move_date"] = original_dt.date().isoformat()

        await q.message.reply_text(
            f"Select new date for visit #{visit_id}:",
            reply_markup=kb_move_calendar(original_dt.year, original_dt.month, source_day, emp),
        )
        return True

    if data == "D:MOVE_NOOP":
        return True

    if data.startswith("D:MOVE_MON_PREV:") or data.startswith("D:MOVE_MON_NEXT:"):
        _, _, _, ym, source_day, emp = data.split(":", 5)
        y, m = map(int, ym.split("-"))
        cur = date(y, m, 1)
        target = (cur - timedelta(days=1)).replace(day=1) if data.startswith("D:MOVE_MON_PREV:") else (cur + timedelta(days=32)).replace(day=1)
        await q.message.reply_text(
            "Select new date:",
            reply_markup=kb_move_calendar(target.year, target.month, source_day, emp),
        )
        return True

    if data.startswith("D:MOVE_DATE:"):
        _, _, _, selected_day, source_day, emp = data.split(":", 5)
        context.user_data["move_date"] = selected_day
        context.user_data["move_hour"] = None

        hours = get_employee_hours(emp, selected_day)
        if not hours:
            await q.message.reply_text(
                f"⛔ {emp} nie pracuje w wybranym dniu. Wybierz inną datę.",
                reply_markup=kb_move_calendar(date.fromisoformat(selected_day).year, date.fromisoformat(selected_day).month, source_day, emp),
            )
            return True

        start_h, end_h = hours
        await q.message.reply_text(
            f"Selected date: {selected_day}\nSelect new hour:",
            reply_markup=kb_move_hours(selected_day, source_day, emp, start_h, end_h),
        )
        return True

    if data.startswith("D:MOVE_BACK_DATE:"):
        _, _, _, selected_day, source_day, emp = data.split(":", 5)
        d = date.fromisoformat(selected_day)
        await q.message.reply_text(
            "Select new date:",
            reply_markup=kb_move_calendar(d.year, d.month, source_day, emp),
        )
        return True

    if data.startswith("D:MOVE_BACK_HOUR:"):
        _, _, _, selected_day, source_day, emp = data.split(":", 5)
        hours = get_employee_hours(emp, selected_day)
        if not hours:
            await q.message.reply_text("Selected day is not available for this employee.")
            return True
        start_h, end_h = hours
        await q.message.reply_text("Select new hour:", reply_markup=kb_move_hours(selected_day, source_day, emp, start_h, end_h))
        return True

    if data.startswith("D:MOVE_HOUR:"):
        _, _, _, hour, selected_day, source_day, emp = data.split(":", 6)
        context.user_data["move_hour"] = int(hour)
        hours = get_employee_hours(emp, selected_day)
        if not hours:
            await q.message.reply_text("Selected day is not available for this employee.")
            return True
        _, end_h = hours
        await q.message.reply_text(
            "Select new minutes:",
            reply_markup=kb_move_minutes(int(hour), selected_day, source_day, emp, end_h),
        )
        return True

    if data.startswith("D:MOVE_MIN:"):
        _, _, _, minute, selected_day, source_day, emp = data.split(":", 6)
        visit_id = context.user_data.get("move_visit_id")
        hour = context.user_data.get("move_hour")

        if not visit_id or hour is None:
            await q.message.reply_text("Move state expired. Start again.", reply_markup=kb_day_actions(source_day, emp))
            return True

        if not is_within_employee_hours(emp, int(hour), int(minute), DEFAULT_DURATION_MIN, selected_day):
            hours = get_employee_hours(emp, selected_day)
            if not hours:
                await q.message.reply_text("Selected day is not available for this employee.")
                return True
            _, end_h = hours
            await q.message.reply_text(
                "This slot is outside employee work hours. Choose different minutes:",
                reply_markup=kb_move_minutes(int(hour), selected_day, source_day, emp, end_h),
            )
            return True

        start_dt = datetime.strptime(f"{selected_day} {int(hour):02d}:{int(minute):02d}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MIN)

        busy = fetch_busy_intervals(selected_day, emp, DEFAULT_DURATION_MIN)

        original_start = None
        raw_original = context.user_data.get("move_original_dt")
        if raw_original:
            try:
                original_start = datetime.fromisoformat(raw_original)
            except Exception:
                original_start = None

        for b_start, b_end in busy:
            if original_start and b_start == original_start:
                continue
            if overlaps(start_dt, end_dt, b_start, b_end):
                _, end_h = get_employee_hours(emp, selected_day) or (9, 18)
                await q.message.reply_text(
                    "This slot is occupied. Choose different minutes:",
                    reply_markup=kb_move_minutes(int(hour), selected_day, source_day, emp, end_h),
                )
                return True

        try:
            api_patch(f"/api/visits/{int(visit_id)}", {"dt": start_dt.isoformat()})
            context.user_data["move_visit_id"] = None
            context.user_data["move_hour"] = None
            context.user_data["move_date"] = None
            context.user_data["move_source_day"] = None
            context.user_data["move_original_dt"] = None

            text = render_day_view(selected_day, emp)
            await q.message.reply_text("Visit moved.\n\n" + text, reply_markup=kb_day_actions(selected_day, emp))
        except RequestException:
            await q.message.reply_text("Could not move visit (API error).", reply_markup=kb_day_actions(source_day, emp))
        return True

    if data == "D:BACK_MENU":
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    return False


async def on_callback(update, context, data: str) -> bool:
    return await handle_day_callback(update, context, data)


async def on_text(update, context) -> bool:
    return False
