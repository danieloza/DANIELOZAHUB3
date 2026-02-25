from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api import fetch_slot_recommendations
from bot.config import EMPLOYEES, SERVICE_DURATIONS, SERVICES
from bot.keyboards import main_menu
from bot.ui_kb import kb_clients_step


def _employees_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(e, callback_data=f"SL:EMP:{e}")] for e in EMPLOYEES]
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="SL:BACK")])
    return InlineKeyboardMarkup(rows)


def _services_kb(emp: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(s, callback_data=f"SL:SVC:{emp}:{s}")] for s in SERVICES
    ]
    rows.append([InlineKeyboardButton("⬅️ Pracownicy", callback_data="SL:MENU")])
    return InlineKeyboardMarkup(rows)


def _slots_kb(emp: str, svc: str, slots: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for s in slots[:6]:
        try:
            start_dt = datetime.fromisoformat(s["start_dt"])
        except Exception:
            continue
        packed = start_dt.strftime("%Y%m%d%H%M")
        label = f"{start_dt.strftime('%d.%m %H:%M')}  (score {s.get('score', 0)})"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"SL:PICK:{emp}:{svc}:{packed}")]
        )
    rows.append([InlineKeyboardButton("⬅️ Usługi", callback_data=f"SL:EMP:{emp}")])
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="SL:BACK")])
    return InlineKeyboardMarkup(rows)


async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("SL:"):
        return False
    q = update.callback_query

    if data == "SL:MENU":
        await q.message.reply_text(
            "Smart sloty: wybierz osobę", reply_markup=_employees_kb()
        )
        return True

    if data == "SL:BACK":
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    if data.startswith("SL:EMP:"):
        emp = data.split("SL:EMP:")[1]
        await q.message.reply_text(f"Usługa dla {emp}:", reply_markup=_services_kb(emp))
        return True

    if data.startswith("SL:SVC:"):
        _, _, emp, svc = data.split(":", 3)
        today_iso = date.today().isoformat()
        duration = int(SERVICE_DURATIONS.get(svc) or 30)
        slots = fetch_slot_recommendations(today_iso, emp, svc, duration_min=duration)
        if not slots:
            tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()
            slots = fetch_slot_recommendations(
                tomorrow_iso, emp, svc, duration_min=duration
            )
        if not slots:
            await q.message.reply_text(
                "Brak wolnych propozycji slotów.", reply_markup=_services_kb(emp)
            )
            return True
        await q.message.reply_text(
            f"Najlepsze sloty: {emp} / {svc}",
            reply_markup=_slots_kb(emp, svc, slots),
        )
        return True

    if data.startswith("SL:PICK:"):
        _, _, emp, svc, packed = data.split(":", 4)
        try:
            dt = datetime.strptime(packed, "%Y%m%d%H%M")
        except Exception:
            await q.message.reply_text("Niepoprawny slot.", reply_markup=main_menu())
            return True

        context.user_data["visit_draft"] = {
            "date": dt.date().isoformat(),
            "time": dt.strftime("%H:%M"),
            "employee_name": emp,
            "service_name": svc,
            "duration_min": int(SERVICE_DURATIONS.get(svc) or 30),
        }
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False
        await q.message.reply_text(
            f"✅ Wybrano slot {dt.strftime('%Y-%m-%d %H:%M')} ({emp}, {svc})\nWybierz klienta:",
            reply_markup=kb_clients_step(),
        )
        return True

    await q.message.reply_text("Nieznana akcja SL.", reply_markup=main_menu())
    return True


async def on_text(update, context) -> bool:
    return False
