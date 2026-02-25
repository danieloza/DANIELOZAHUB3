import httpx
from .config import settings

async def notify_waitlist(slot_time: str, service_name: str):
    """
    Blasts a message to clients waiting for a slot.
    """
    # Mocked list of interested clients
    waitlist = [settings.OWNER_TELEGRAM_ID] 
    
    msg = f"🔥 <b>WOLNY TERMIN!</b>

Zwolniło się miejsce: <b>{slot_time}</b>
Usługa: {service_name}

<i>Kto pierwszy ten lepszy!</i>"
    
    async with httpx.AsyncClient() as client:
        for chat_id in waitlist:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}
            )
