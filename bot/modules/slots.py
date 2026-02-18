# -*- coding: utf-8 -*-
"""
(2) Inteligentne sloty:
- generuj tylko starty, które mieszczą usługę w godzinach pracy
- slot step zależny od polityki (np. 5/10/15)
Prefix callbacki: SL:
"""

async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("SL:"):
        return False
    q = update.callback_query
    await q.message.reply_text("SL: (stub) sloty inteligentne – jeszcze nie zaimplementowane")
    return True

async def on_text(update, context) -> bool:
    return False
