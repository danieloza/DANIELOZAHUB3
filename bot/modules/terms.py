from telegram import Update
from telegram.ext import ContextTypes

async def send_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Senior IT: Sends the salon terms and conditions to the user.
    """
    text = (
        "<b>⚖️ REGULAMIN REZERWACJI - SALON DANEX</b>

"
        "1. Rezerwacja wymaga wpłaty <b>zadatku 20 zł</b>.
"
        "2. Zadatek jest <b>bezzwrotny</b> jeśli nie przyjdziesz (art. 394 KC).
"
        "3. Zmiana terminu możliwa do 24h przed wizytą.
"
        "4. Spóźnienie powyżej 15 min może skutkować anulowaniem wizyty.

"
        "<i>Pełny tekst dostępny u obsługi salonu.</i>"
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")
