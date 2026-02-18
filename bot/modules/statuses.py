# -*- coding: utf-8 -*-
"""
(5) Statusy wizyty / check-in:
- planned/confirmed/arrived/in_service/done/no_show
- widok dnia z statusami
Prefix callbacki: ST:
"""

async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("ST:"):
        return False
    q = update.callback_query
    await q.message.reply_text("ST: (stub) statusy – jeszcze nie zaimplementowane")
    return True

async def on_text(update, context) -> bool:
    return False
