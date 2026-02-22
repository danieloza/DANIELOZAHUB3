# -*- coding: utf-8 -*-

import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from bot.keyboards import main_menu
from bot.states import S

# dispatchery modułów
from bot.core.router import dispatch_callback, dispatch_text

# .env
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "SalonOS Command Center\n"
        "Steruj wizytami, slotami i CRM z jednego miejsca.\n\n"
        "Wybierz akcję:"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=main_menu())
    else:
        await update.message.reply_text(text, reply_markup=main_menu())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    context.user_data["month_action"] = None
    await show_menu(update, context)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    context.user_data["month_action"] = None
    await show_menu(update, context)


async def on_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass

    data = q.data or ""
    if data == "WOW:START":
        data = "TODAY"
    elif data == "WOW:ADD":
        data = "ADD_VISIT"

    # 0) Moduły (D:, V:, AV:, itp.)
    # Jeśli któryś moduł obsłuży callback -> kończymy.
    if await dispatch_callback(update, context, data):
        return

    # 1) MAIN MENU actions (4 przyciski)
    if data == "TODAY":
        from datetime import date
        from bot.ui_kb import kb_day_employees
        day_iso = date.today().isoformat()
        await q.message.reply_text("📅 Wybierz osobę (Dziś):", reply_markup=kb_day_employees(day_iso))
        return

    if data == "ADD_VISIT":
        from bot.ui_kb import kb_employees
        context.user_data["visit_draft"] = {}
        context.user_data["awaiting_client_text"] = False
        context.user_data["awaiting_price_text"] = False
        await q.message.reply_text("Wybierz fryzjerkę:", reply_markup=kb_employees())
        return

    if data == "CLIENTS":
        await q.message.reply_text("👤 Klienci – wkrótce.", reply_markup=main_menu())
        return

    if data == "CALENDAR":
        await q.message.reply_text("🗓️ Kalendarz – wkrótce.", reply_markup=main_menu())
        return

    # 2) DAY VIEW actions (D:...) — jeśli nie masz tego jeszcze jako moduł w registry,
    # to ten blok zapewni, że klik w Magda/Kamila/Taja nie da "Nieznana akcja".
    if data.startswith("D:"):
        from bot.ui_kb import kb_day_employees, kb_day_actions, kb_hours
        from bot.day_view import render_day_view

        if data.startswith("D:CHOOSE:"):
            day_iso = data.split("D:CHOOSE:")[1]
            await q.message.reply_text("📅 Wybierz osobę (Dziś):", reply_markup=kb_day_employees(day_iso))
            return

        if data.startswith("D:EMP:"):
            _, _, day_iso, emp = data.split(":", 3)
            text = render_day_view(day_iso, emp)
            await q.message.reply_text(text, reply_markup=kb_day_actions(day_iso, emp))
            return

        if data.startswith("D:ADD:"):
            _, _, day_iso, emp = data.split(":", 3)

            context.user_data["visit_draft"] = {"date": day_iso, "employee_name": emp}
            context.user_data["awaiting_client_text"] = False
            context.user_data["awaiting_price_text"] = False

            await q.message.reply_text(
                f"➕ Dodaj wizytę\n📅 {day_iso}\n💇 {emp}\n\nWybierz godzinę:",
                reply_markup=kb_hours(),
            )
            return

        if data == "D:BACK_MENU":
            await q.message.reply_text("Menu:", reply_markup=main_menu())
            return

        await q.message.reply_text("⚠️ Nieznana akcja (D:).", reply_markup=main_menu())
        return

    # 3) Stare akcje – MONTH/CSV/PDF
    if data in ("MONTH", "CSV_MONTH", "PDF_MONTH"):
        context.user_data["state"] = S.ASK_MONTH
        context.user_data["month_action"] = data
        await q.message.reply_text("Podaj miesiąc: YYYY-MM (np. 2026-02)")
        return

    await q.message.reply_text("⚠️ Nieznana akcja.", reply_markup=main_menu())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # tekst obsługiwany przez moduły (np. kreator wizyty: klient/cena)
    if await dispatch_text(update, context):
        return

    # stare stany (jak miałeś)
    state = context.user_data.get("state")
    if state == S.ASK_MONTH:
        txt = (update.message.text or "").strip()
        try:
            year, month = map(int, txt.split("-"))
        except Exception:
            await update.message.reply_text("Podaj YYYY-MM (np. 2026-02).")
            return

        action = context.user_data.get("month_action")
        context.user_data["state"] = None
        context.user_data["month_action"] = None

        await update.message.reply_text(
            f"✅ Wybrano {year}-{month:02d} (akcja: {action}).",
            reply_markup=main_menu(),
        )
        return

    await update.message.reply_text("Kliknij /menu", reply_markup=main_menu())


async def _amain():
    if not TOKEN:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN w .env")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(on_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    print("✅ Bot działa. Telegram: /start  |  Stop: Ctrl+C")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        try:
            await app.updater.stop()
        except Exception:
            pass
        try:
            await app.stop()
        except Exception:
            pass
        try:
            await app.shutdown()
        except Exception:
            pass


def run():
    asyncio.run(_amain())


if __name__ == "__main__":
    run()
