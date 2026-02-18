# -*- coding: utf-8 -*-
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Add visit", callback_data="ADD_VISIT"),
            InlineKeyboardButton("Today", callback_data="TODAY"),
        ],
        [
            InlineKeyboardButton("Calendar", callback_data="CALENDAR"),
            InlineKeyboardButton("Clients", callback_data="CLIENTS"),
        ],
        [
            InlineKeyboardButton("Month report", callback_data="MONTH"),
            InlineKeyboardButton("Month revenue", callback_data="MONTH"),
        ],
        [
            InlineKeyboardButton("Export CSV", callback_data="CSV_MONTH"),
            InlineKeyboardButton("Export PDF", callback_data="PDF_MONTH"),
        ],
    ])
