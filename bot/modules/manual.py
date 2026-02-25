from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def send_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """<b>📖 INSTRUKCJA DLA MAMY (Danex Zarządzanie)</b>

Witaj! Oto jak używać bota w prostych krokach:

1️⃣ <b>Dodawanie wizyty:</b> Kliknij przycisk <i>'💎 Dodaj wizytę'</i>. Bot zapyta Cię o fryzjerkę, usługę i godzinę. Po prostu wybieraj opcje z listy.

2️⃣ <b>Sprawdzanie kalendarza:</b> Przycisk <i>'📅 Kalendarz'</i> pokaże Ci kto i kiedy jest zapisany.

3️⃣ <b>Dostępność fryzjerek:</b> Kliknij <i>'🗓️ Dostępność Live'</i>, aby zobaczyć wolne terminy na dziś.

4️⃣ <b>Raporty:</b> Na samym dole masz przyciski do raportów PDF i CSV - bot wyśle Ci gotowy dokument z zarobkami.

💡 <i>Pamiętaj: Jeśli się pomylisz, zawsze możesz kliknąć /start, aby wrócić do początku.</i>"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Powrót do menu", callback_data="WOW:BACK")]
    ])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
