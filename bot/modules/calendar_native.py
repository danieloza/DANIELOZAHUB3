import calendar
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.core.availability import availability

def create_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    # Header: Month and Year
    month_name = [
        "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
        "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
    ][month - 1]
    
    keyboard = []
    
    # Row 1: Navigation
    keyboard.append([
        InlineKeyboardButton("<", callback_data=f"CAL:NAV:{year}:{month-1}"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="IGNORE"),
        InlineKeyboardButton(">", callback_data=f"CAL:NAV:{year}:{month+1}")
    ])
    
    # Row 2: Days of week
    week_days = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]
    keyboard.append([InlineKeyboardButton(day, callback_data="IGNORE") for day in week_days])
    
    # Days grid
    month_calendar = calendar.monthcalendar(year, month)
    today = date.today()
    
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
            else:
                check_date = date(year, month, day)
                is_open = availability.is_working_day(check_date)
                
                # Senior IT: Heatmap Logic
                # In real scenario, fetch counts from DB. For now, we use a placeholder.
                visit_count = 0 
                heat_icon = ""
                if visit_count > 5: heat_icon = "🔥"
                elif visit_count > 0: heat_icon = "📍"

                # Visual logic
                if not is_open:
                    label = f"❌{day}"
                elif today == check_date:
                    label = f"•{day}•"
                else:
                    label = f"{day}{heat_icon}"
                
                # Callback logic: disable clicking on closed days or show they are closed
                callback_data = f"D:EMP:{year}-{month:02d}-{day:02d}:all" if is_open else "IGNORE"
                row.append(InlineKeyboardButton(label, callback_data=callback_data))
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("⬅️ Powrót do menu", callback_data="WOW:BACK")])
    return InlineKeyboardMarkup(keyboard)

async def send_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE, year=None, month=None):
    if year is None or month is None:
        now = datetime.now()
        year, month = now.year, now.month
    
    # Logic for month wrapping
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1
        
    reply_markup = create_calendar(year, month)
    text = """<b>📅 KALENDARZ WIZYT</b>

Wybierz dzień, aby zobaczyć zaplanowane wizyty:"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
