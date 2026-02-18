# -*- coding: utf-8 -*-
from bot.core.registry import MODULES

async def dispatch_callback(update, context, data: str) -> bool:
    for m in MODULES:
        try:
            handled = await m.on_callback(update, context, data)
            if handled:
                return True
        except Exception as e:
            # tu możesz dodać logowanie
            # print(f"[ERR] {m.__name__} callback: {e}")
            continue
    return False

async def dispatch_text(update, context) -> bool:
    for m in MODULES:
        try:
            handled = await m.on_text(update, context)
            if handled:
                return True
        except Exception as e:
            # print(f"[ERR] {m.__name__} text: {e}")
            continue
    return False
