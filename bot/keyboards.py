# -*- coding: utf-8 -*-
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
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
    ])
