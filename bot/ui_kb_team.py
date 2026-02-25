from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def kb_team_management() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Dodaj pracownika", callback_data="TEAM:ADD")],
        [InlineKeyboardButton("❌ Usuń/Archiwizuj", callback_data="TEAM:LIST_REMOVE")],
        [InlineKeyboardButton("📋 Lista aktywnych", callback_data="TEAM:LIST")],
        [InlineKeyboardButton("🏠 Wróć", callback_data="WOW:BACK")]
    ])

def kb_employee_list_remove(employees: list) -> InlineKeyboardMarkup:
    rows = []
    for emp in employees:
        rows.append([InlineKeyboardButton(f"❌ Usuń: {emp['name']}", callback_data=f"TEAM:DELETE:{emp['id']}")])
    rows.append([InlineKeyboardButton("🏠 Wróć", callback_data="WOW:BACK")])
    return InlineKeyboardMarkup(rows)

def kb_profile_edit() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Zmień Bio", callback_data="PROFILE:EDIT_BIO")],
        [InlineKeyboardButton("✂️ Zmień Specjalizacje", callback_data="PROFILE:EDIT_SPECS")],
        [InlineKeyboardButton("🏠 Wróć", callback_data="WOW:BACK")]
    ])
