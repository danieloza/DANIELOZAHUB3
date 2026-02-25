from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 INSTRUKCJA DLA MAMY", callback_data="WOW:MANUAL"),
            ],
            [
                InlineKeyboardButton("📅 KALENDARZ GRAFICZNY", callback_data="WOW:CALENDAR"),
            ],
            [
                InlineKeyboardButton("🚀 Start dnia", callback_data="WOW:START"),
                InlineKeyboardButton("💎 Dodaj wizytę", callback_data="WOW:ADD"),
            ],
            [
                InlineKeyboardButton("🧠 Slot Engine", callback_data="SL:MENU"),
                InlineKeyboardButton("👤 CRM 360", callback_data="CRM:MENU"),
            ],
            [
                InlineKeyboardButton("🕒 Status Flow", callback_data="ST:MENU"),
                InlineKeyboardButton("🗓️ Dostępność Live", callback_data="AV:MENU"),
            ],
            [
                InlineKeyboardButton("🧱 Bufory Pro", callback_data="BF:MENU"),
                InlineKeyboardButton("⚡ Pulse Assistant", callback_data="CRM:ASSIST"),
            ],
            [
                InlineKeyboardButton("📊 Raport miesiąca", callback_data="MONTH"),
                InlineKeyboardButton("📁 CSV", callback_data="CSV_MONTH"),
                InlineKeyboardButton("📄 PDF", callback_data="PDF_MONTH"),
            ],
        ]
    )


def persistent_panel(visit_count: int = 0) -> ReplyKeyboardMarkup:
    """Senior IT: Permanent buttons at the bottom for easy access."""
    label_calendar = f"📅 Dziś: {visit_count} wizyt" if visit_count > 0 else "📅 Kalendarz"
    return ReplyKeyboardMarkup(
        [
            ["💎 Dodaj wizytę", label_calendar],
            ["👥 Zespół", "📊 Raport miesięczny"],
            ["📖 Instrukcja", "🏠 Menu Główne"]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def employee_panel(visit_count: int = 0) -> ReplyKeyboardMarkup:
    """Senior IT: Limited view for employees with profile management."""
    label_calendar = f"📅 Mój grafik ({visit_count})" if visit_count > 0 else "📅 Mój grafik"
    return ReplyKeyboardMarkup(
        [
            [label_calendar, "💰 Moje zarobki"],
            ["📝 Mój Profil", "💎 Dodaj wizytę"],
            ["🏠 Menu Główne"]
        ],
        resize_keyboard=True,
        is_persistent=True
    )
    """Senior IT: Permanent buttons at the bottom for easy access."""
    label_calendar = f"📅 Dziś: {visit_count} wizyt" if visit_count > 0 else "📅 Kalendarz"
    return ReplyKeyboardMarkup(
        [
            ["💎 Dodaj wizytę", label_calendar],
            ["👥 Zespół", "📊 Raport miesięczny"],
            ["📖 Instrukcja", "🏠 Menu Główne"]
        ],
        resize_keyboard=True,
        is_persistent=True
    )
