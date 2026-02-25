from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api import api_patch, fetch_visits_for_day
from bot.config import EMPLOYEES
from bot.keyboards import main_menu

STATUSES = [
    "planned",
    "confirmed",
    "arrived",
    "in_service",
    "done",
    "no_show",
    "canceled",
]


def _employees_kb(day_iso: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(e, callback_data=f"ST:EMP:{day_iso}:{e}")]
        for e in EMPLOYEES
    ]
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="ST:BACK")])
    return InlineKeyboardMarkup(rows)


def _visits_kb(day_iso: str, emp: str, visits: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for v in visits:
        try:
            hhmm = datetime.fromisoformat(v.get("dt", "")).strftime("%H:%M")
        except Exception:
            hhmm = "??:??"
        label = f"{hhmm} {v.get('client_name') or v.get('client') or '-'} [{v.get('status') or 'planned'}]"
        rows.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"ST:VISIT:{v.get('id')}:{day_iso}:{emp}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("⬅️ Pracownicy", callback_data=f"ST:MENU:{day_iso}")]
    )
    return InlineKeyboardMarkup(rows)


def _status_kb(visit_id: int, day_iso: str, emp: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                s, callback_data=f"ST:SET:{visit_id}:{s}:{day_iso}:{emp}"
            )
        ]
        for s in STATUSES
    ]
    rows.append(
        [InlineKeyboardButton("⬅️ Lista wizyt", callback_data=f"ST:EMP:{day_iso}:{emp}")]
    )
    return InlineKeyboardMarkup(rows)


async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("ST:"):
        return False
    q = update.callback_query

    if data in ("ST:MENU", "ST:MENU:"):
        day_iso = date.today().isoformat()
        await q.message.reply_text(
            "Statusy wizyt: wybierz osobę", reply_markup=_employees_kb(day_iso)
        )
        return True

    if data.startswith("ST:MENU:"):
        day_iso = data.split("ST:MENU:")[1] or date.today().isoformat()
        await q.message.reply_text(
            "Statusy wizyt: wybierz osobę", reply_markup=_employees_kb(day_iso)
        )
        return True

    if data == "ST:BACK":
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    if data.startswith("ST:EMP:"):
        _, _, day_iso, emp = data.split(":", 3)
        visits = fetch_visits_for_day(day_iso, emp)
        if not visits:
            await q.message.reply_text(
                "Brak wizyt.", reply_markup=_employees_kb(day_iso)
            )
            return True
        await q.message.reply_text(
            f"Wybierz wizytę ({emp}):", reply_markup=_visits_kb(day_iso, emp, visits)
        )
        return True

    if data.startswith("ST:VISIT:"):
        _, _, visit_id, day_iso, emp = data.split(":", 4)
        await q.message.reply_text(
            f"Ustaw status wizyty #{visit_id}:",
            reply_markup=_status_kb(int(visit_id), day_iso, emp),
        )
        return True

    if data.startswith("ST:SET:"):
        _, _, visit_id, new_status, day_iso, emp = data.split(":", 5)
        try:
            api_patch(f"/api/visits/{int(visit_id)}/status", {"status": new_status})
            await q.message.reply_text(
                f"✅ Status wizyty #{visit_id}: {new_status}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Lista wizyt", callback_data=f"ST:EMP:{day_iso}:{emp}"
                            )
                        ]
                    ]
                ),
            )
        except Exception:
            await q.message.reply_text(
                "Nie udało się zmienić statusu.",
                reply_markup=_status_kb(int(visit_id), day_iso, emp),
            )
        return True

    await q.message.reply_text("Nieznana akcja ST.", reply_markup=main_menu())
    return True


async def on_text(update, context) -> bool:
    return False
