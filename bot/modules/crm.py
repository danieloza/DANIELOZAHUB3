# -*- coding: utf-8 -*-
"""
(4) CRM Klientów:
- wyszukiwanie po 3 literach / telefonie
- historia wizyt
- notatki
Prefix callbacki: CRM:
"""

async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("CRM:"):
        return False
    q = update.callback_query
    await q.message.reply_text("CRM: (stub) klienci – jeszcze nie zaimplementowane")
    return True

async def on_text(update, context) -> bool:
    return False
