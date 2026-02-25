from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api import fetch_employee_availability, set_employee_day_off
from bot.config import EMPLOYEES
from bot.keyboards import main_menu


def _emp_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"👩 {e}", callback_data=f"AV:EMP:{e}")]
        for e in EMPLOYEES
    ]
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="AV:BACK")])
    return InlineKeyboardMarkup(rows)


def _emp_actions(emp: str) -> InlineKeyboardMarkup:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📆 Pokaż 7 dni", callback_data=f"AV:SHOW:{emp}")],
            [
                InlineKeyboardButton(
                    "🚫 Jutro wolne", callback_data=f"AV:DAYOFF:{emp}:{tomorrow}"
                )
            ],
            [InlineKeyboardButton("⬅️ Pracownicy", callback_data="AV:MENU")],
        ]
    )


def _format_availability(rows: list[dict], emp: str) -> str:
    lines = [f"🗓️ Dostępność: {emp}", ""]
    if not rows:
        return "\n".join(lines + ["Brak danych."])
    for row in rows:
        d = row.get("day")
        if row.get("is_day_off"):
            lines.append(f"- {d}: wolne ({row.get('source')})")
        else:
            lines.append(
                f"- {d}: {row.get('start_hour'):02d}:00-{row.get('end_hour'):02d}:00 ({row.get('source')})"
            )
    return "\n".join(lines)


async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("AV:"):
        return False
    q = update.callback_query

    if data in ("AV:MENU",):
        await q.message.reply_text("Dostępność zespołu:", reply_markup=_emp_menu())
        return True

    if data in ("AV:BACK",):
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    if data.startswith("AV:EMP:"):
        emp = data.split("AV:EMP:")[1]
        await q.message.reply_text(f"Wybrano: {emp}", reply_markup=_emp_actions(emp))
        return True

    if data.startswith("AV:SHOW:"):
        emp = data.split("AV:SHOW:")[1]
        start_day = date.today()
        end_day = start_day + timedelta(days=6)
        rows = fetch_employee_availability(
            emp, start_day.isoformat(), end_day.isoformat()
        )
        await q.message.reply_text(
            _format_availability(rows, emp), reply_markup=_emp_actions(emp)
        )
        return True

    if data.startswith("AV:DAYOFF:"):
        _, _, emp, day_iso = data.split(":", 3)
        res = set_employee_day_off(emp, day_iso, is_day_off=True, note="set from bot")
        if not res:
            await q.message.reply_text(
                "Nie udało się zapisać dnia wolnego.", reply_markup=_emp_actions(emp)
            )
            return True
        await q.message.reply_text(
            f"✅ Ustawiono wolne: {emp} {day_iso}", reply_markup=_emp_actions(emp)
        )
        return True

    await q.message.reply_text("Nieznana akcja AV.", reply_markup=main_menu())
    return True


async def on_text(update, context) -> bool:
    return False
