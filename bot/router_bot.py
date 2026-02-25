import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ChatAction
import subprocess

async def cmd_brain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Senior IT: AI RAG Integration"""
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text("🧠 Zapytaj Mózg o cokolwiek, np:\n/brain Jakie mamy wyniki w tym miesiącu?")
        return

    status_msg = await update.message.reply_text("🧠 Mózg analizuje dane... (to może potrwać 10-20s)")
    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # 2. Zapytaj RAG
    rag_dir = Path(__file__).resolve().parents[2] / "python-rag-langchain"
    rag_venv_python = rag_dir / ".venv" / "Scripts" / "python.exe"
    rag_script = rag_dir / "rag_demo.py"

    if not rag_venv_python.exists():
        rag_venv_python = "python"

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [str(rag_venv_python), str(rag_script), "-q", question],
                capture_output=True,
                text=True,
                cwd=str(rag_dir),
                encoding='utf-8',
                errors='ignore'
            )
        )
        
        if result.returncode == 0:
            output = result.stdout
            import re
            match = re.search(r"A: (.*)", output, re.DOTALL)
            answer = match.group(1).strip() if match else output[-500:]
            await status_msg.edit_text(f"🧠 *Odpowiedź AI:*\n{answer}", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ Błąd Mózgu:\n{result.stderr[:500]}")

    except Exception as e:
        await status_msg.edit_text(f"❌ Krytyczny błąd: {e}")


# dispatchery modułów
from bot.modules.calendar_sync import on_calendar_upload
from bot.core.router import dispatch_callback, dispatch_text
from bot.keyboards import main_menu, persistent_panel, employee_panel
from bot.states import S
from app.config import settings

# .env
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Senior IT: Premium UX - Typing Indicator
    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await asyncio.sleep(0.7) # Micro-delay to let the user see the animation

    text = (
        "SalonOS Command Center\n"
        "Steruj wizytami, slotami i CRM z jednego miejsca.\n\n"
        "Wybierz akcję:"
    )
    # Senior IT: Dynamic visit count for today
    from datetime import date
    from bot.api import fetch_visits_for_day
    try:
        # Quick check of reservations for today
        day_iso = date.today().isoformat()
        visits = fetch_visits_for_day(day_iso, "")
        visit_count = len(visits)
    except Exception:
        visit_count = 0

    # Senior IT: Always attach the correct panel based on role
    # Assuming we get role from API or user mapping
    is_owner = str(update.effective_user.id) == settings.OWNER_TELEGRAM_ID
    panel = persistent_panel(visit_count=visit_count) if is_owner else employee_panel(visit_count=visit_count)

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text, reply_markup=main_menu()
        )
    else:
        await update.message.reply_text(
            text, reply_markup=panel
        )
        await update.message.reply_text(
            "Oto menu główne:", reply_markup=main_menu()
        )


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
    elif data == "WOW:MANUAL":
        from bot.modules.manual import send_manual
        await send_manual(update, context)
        return
    elif data == "WOW:CALENDAR":
        from bot.modules.calendar_native import send_calendar
        await send_calendar(update, context)
        return
    elif data.startswith("CAL:NAV:"):
        from bot.modules.calendar_native import send_calendar
        _, _, year, month = data.split(":")
        await send_calendar(update, context, int(year), int(month))
        return
    elif data == "WOW:BACK":
        await show_menu(update, context)
        return
    elif data == "TEAM:LIST":
        from bot.api import api_get_json
        employees = api_get_json("/api/team/employees")
        text = "👥 <b>Aktywny zespół:</b>\n\n" + "\n".join([f"- {e['name']}" for e in employees])
        await q.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())
        return
    elif data == "TEAM:LIST_REMOVE":
        from bot.api import api_get_json
        from bot.ui_kb_team import kb_employee_list_remove
        employees = api_get_json("/api/team/employees")
        await q.message.reply_text("Wybierz pracownika do usunięcia:", reply_markup=kb_employee_list_remove(employees))
        return
    elif data.startswith("TEAM:DELETE:"):
        from bot.api import api_delete
        emp_id = data.split(":")[-1]
        api_delete(f"/api/team/employees/{emp_id}")
        await q.message.reply_text("✅ Pracownik został usunięty/zarchiwizowany.", reply_markup=main_menu())
        return
    elif data == "TEAM:ADD":
        context.user_data["state"] = "ASK_EMPLOYEE_NAME"
        await q.message.reply_text("Wpisz imię nowej fryzjerki:")
        return
    elif data == "PROFILE:EDIT_BIO":
        context.user_data["state"] = "ASK_PROFILE_BIO"
        await q.message.reply_text("Wpisz swój nowy biogram (krótki opis dla klientek):")
        return
    elif data == "PROFILE:EDIT_SPECS":
        context.user_data["state"] = "ASK_PROFILE_SPECS"
        await q.message.reply_text("Wpisz swoje specjalizacje po przecinku (np. Balejaż, Strzyżenie męskie):")
        return

    # 0) Moduły (D:, V:, AV:, itp.)
    # Jeśli któryś moduł obsłuży callback -> kończymy.
    if await dispatch_callback(update, context, data):
        return

    # 1) MAIN MENU actions (4 przyciski)
    if data == "TODAY":
        from datetime import date

        from bot.ui_kb import kb_day_employees

        day_iso = date.today().isoformat()
        await q.message.reply_text(
            "📅 Wybierz osobę (Dziś):", reply_markup=kb_day_employees(day_iso)
        )
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
        from bot.day_view import render_day_view
        from bot.ui_kb import kb_day_actions, kb_day_employees, kb_hours

        if data.startswith("D:CHOOSE:"):
            day_iso = data.split("D:CHOOSE:")[1]
            await q.message.reply_text(
                "📅 Wybierz osobę (Dziś):", reply_markup=kb_day_employees(day_iso)
            )
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
    txt = (update.message.text or "").strip()

    # Handle Persistent Panel Buttons
    if txt == "💎 Dodaj wizytę":
        from bot.ui_kb import kb_employees
        context.user_data["visit_draft"] = {}
        await update.message.reply_text("Wybierz fryzjerkę:", reply_markup=kb_employees())
        return
    elif txt == "📅 Kalendarz":
        from bot.modules.calendar_native import send_calendar
        await send_calendar(update, context)
        return
    elif txt == "📖 Instrukcja":
        from bot.modules.manual import send_manual
        await send_manual(update, context)
        return
    elif txt == "📊 Raport miesięczny":
        context.user_data["state"] = S.ASK_MONTH
        context.user_data["month_action"] = "MONTH"
        await update.message.reply_text("Podaj miesiąc: YYYY-MM (np. 2026-02)")
        return
    elif txt == "👥 Zespół":
        from bot.ui_kb import kb_team_management
        from bot.api import fetch_team_employees
        employees = fetch_team_employees()
        await update.message.reply_text("Zarządzanie zespołem:", reply_markup=kb_team_management(employees))
        return
    elif txt == "💰 Moje zarobki":
        from bot.api import api_get_json
        # ... logic ...
        return
    elif txt == "📝 Mój Profil":
        from bot.ui_kb_team import kb_profile_edit
        await update.message.reply_text("Zarządzaj swoim profilem publicznym na stronie Danex:", reply_markup=kb_profile_edit())
        return
    elif txt == "🏠 Menu Główne":
        await show_menu(update, context)
        return

    # tekst obsługiwany przez moduły (np. kreator wizyty: klient/cena)
    if await dispatch_text(update, context):
        return

    state = context.user_data.get("state")
    if state == "ASK_EMPLOYEE_NAME":
        # ... logic ...
        return
    elif state == "ASK_PROFILE_BIO":
        from bot.api import api_patch
        # In real app, we get current employee_id from user mapping
        emp_id = 1 
        api_patch(f"/api/team/employees/{emp_id}", {"bio": txt})
        context.user_data["state"] = None
        await update.message.reply_text("✅ Twój biogram został zaktualizowany na stronie!", reply_markup=main_menu())
        return
    elif state == "ASK_PROFILE_SPECS":
        from bot.api import api_patch
        emp_id = 1
        api_patch(f"/api/team/employees/{emp_id}", {"specialties": txt})
        context.user_data["state"] = None
        await update.message.reply_text("✅ Specjalizacje zostały zaktualizowane!", reply_markup=main_menu())
        return

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


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from bot.modules.manual import send_manual
    await send_manual(update, context)


async def _amain():
    if not TOKEN:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN w .env")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("brain", cmd_brain))
    app.add_handler(CommandHandler("analiza", cmd_brain))
    app.add_handler(CallbackQueryHandler(on_click))
    
    # Senior IT: Handle .ics files for manual sync
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.Document.FileExtension("ics"), on_calendar_upload))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    await app.initialize()

    # Senior IT: Set permanent Menu Button (The "kafelek" at the bottom left)
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 START / MENU GŁÓWNE"),
        BotCommand("help", "📖 Instrukcja"),
        BotCommand("status", "📊 Szybki raport")
    ])

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
