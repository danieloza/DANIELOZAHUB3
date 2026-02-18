# -*- coding: utf-8 -*-
"""
(1) Grafik i dostępność:
- godziny pracy per fryzjerka
- przerwy
- urlopy / nieobecności
- blokady (szkolenia)
Prefix callbacki: AV:
"""

async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("AV:"):
        return False
    q = update.callback_query
    await q.message.reply_text("AV: (stub) dostępność – jeszcze nie zaimplementowane")
    return True

async def on_text(update, context) -> bool:
    return False
