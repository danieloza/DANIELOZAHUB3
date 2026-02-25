from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .config import settings

async def send_last_chance_confirmation(chat_id: int, visit_id: int, time_str: str):
    """
    Senior IT: Sending a critical confirmation message to avoid No-Show.
    """
    msg = (
        f"⏰ <b>Przypomnienie o wizycie!</b>

"
        f"Widzimy się o <b>{time_str}</b>.
"
        f"Prosimy o potwierdzenie przybycia jednym kliknięciem poniżej. "
        f"Brak potwierdzenia może skutkować anulowaniem wizyty."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ POTWIERDZAM", callback_data=f"V:CONFIRM:{visit_id}")],
        [InlineKeyboardButton("❌ ODWOŁUJĘ", callback_data=f"V:CANCEL:{visit_id}")]
    ])
    
    # Logic to send message via Bot API
    pass
