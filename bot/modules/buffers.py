from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api import set_employee_buffer, set_service_buffer
from bot.config import EMPLOYEES, SERVICES
from bot.keyboards import main_menu


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Usługa +10/+10", callback_data="BF:SVC:10:10")],
            [InlineKeyboardButton("Usługa +15/+15", callback_data="BF:SVC:15:15")],
            [InlineKeyboardButton("Pracownik +5/+5", callback_data="BF:EMP:5:5")],
            [InlineKeyboardButton("Pracownik +10/+10", callback_data="BF:EMP:10:10")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="BF:BACK")],
        ]
    )


async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("BF:"):
        return False
    q = update.callback_query

    if data == "BF:MENU":
        await q.message.reply_text("Bufory: szybkie presety", reply_markup=_menu())
        return True

    if data == "BF:BACK":
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    if data.startswith("BF:SVC:"):
        _, _, before, after = data.split(":")
        changed = 0
        for svc in SERVICES:
            if set_service_buffer(svc, int(before), int(after)):
                changed += 1
        await q.message.reply_text(
            f"✅ Ustawiono bufory usług ({changed}): {before}/{after} min",
            reply_markup=_menu(),
        )
        return True

    if data.startswith("BF:EMP:"):
        _, _, before, after = data.split(":")
        changed = 0
        for emp in EMPLOYEES:
            if set_employee_buffer(emp, int(before), int(after)):
                changed += 1
        await q.message.reply_text(
            f"✅ Ustawiono bufory pracowników ({changed}): {before}/{after} min",
            reply_markup=_menu(),
        )
        return True

    await q.message.reply_text("Nieznana akcja BF.", reply_markup=main_menu())
    return True


async def on_text(update, context) -> bool:
    return False
