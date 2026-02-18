# -*- coding: utf-8 -*-
"""
(3) Bufory:
- bufor przed/po wizycie per usługa lub per pracownik
- uwzględnij w kolizjach i dostępności
Prefix callbacki: BF:
"""

async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("BF:"):
        return False
    q = update.callback_query
    await q.message.reply_text("BF: (stub) bufory – jeszcze nie zaimplementowane")
    return True

async def on_text(update, context) -> bool:
    return False
