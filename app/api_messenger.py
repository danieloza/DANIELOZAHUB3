from fastapi import APIRouter, Request, HTTPException
from starlette.responses import Response
import structlog

router = APIRouter(prefix="/messenger", tags=["messenger"])
logger = structlog.get_logger("bridge.messenger")

VERIFY_TOKEN = "DANEX_MASTER_TOKEN_2026" # You set this in Meta Developer Portal

@router.get("/webhook")
async def verify_messenger(request: Request):
    """
    Standard Meta Webhook verification.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("messenger_webhook_verified")
        return Response(content=challenge)
    
    raise HTTPException(status_code=403, detail="Verification failed")

import httpx
from .config import settings
from .core.sentiment import analyze_sentiment

RAG_API_URL = "http://127.0.0.1:8002/ask"

@router.post("/webhook")
async def handle_messenger_message(request: Request):
    """
    Receives messages from Messenger, asks AI for answer, and alerts owner.
    """
    body = await request.json()
    logger.info("messenger_message_received", payload=body)
    
    try:
        entry = body.get("entry", [{}])[0]
        messaging = entry.get("messaging", [{}])[0]
        sender_id = messaging.get("sender", {}).get("id")
        message_text = messaging.get("message", {}).get("text", "")
        
        if not sender_id or not message_text:
            return {"status": "no_content"}

        # 1. Analyze Sentiment
        sentiment = analyze_sentiment(message_text)
        
        # 2. Get AI Answer from RAG
        ai_answer = await _get_ai_suggestion(message_text)
        
        # 3. Detect Booking Intent (Simple heuristic for Senior Level)
        booking_intent = any(word in message_text.lower() for word in ["rezerwacja", "umów", "zapisać", "termin", "wolne"])
        
        # 4. Generate Stripe Link if intent detected
        payment_url = None
        if booking_intent:
            from .core.payments import create_deposit_session
            # We use a dummy visit_id (0) for generic intent, or real ID if integrated with slots
            payment_url = create_deposit_session(0, f"fb_{sender_id}@messenger.com")

        # 5. AUTO-RESPOND with optional Button
        await _send_messenger_reply(sender_id, ai_answer, payment_url)
        
        # 6. Send Telegram Alert
        await _send_smart_telegram_alert(sender_id, message_text, sentiment, ai_answer)
            
    except Exception as e:
        logger.error("messenger_parsing_failed", error=str(e))
    
    return {"status": "event_received"}

async def _get_ai_suggestion(text: str) -> str:
    """Consults the RAG system for a suggested answer."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(RAG_API_URL, json={"text": text}, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("answer", "AI nie znalazło odpowiedzi.")
    except Exception:
        return "AI Offline (RAG service not responding)"
    return "Błąd połączenia z AI."

async def _send_messenger_reply(recipient_id: str, text: str, payment_url: str = None):
    """
    Senior IT: Sends an automated reply, with an optional payment button.
    """
    access_token = settings.STRIPE_SECRET_KEY # Placeholder, use PAGE_ACCESS_TOKEN in prod
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={access_token}"
    
    if payment_url:
        # Send a Button Template
        message_payload = {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": f"{text}\n\nAby zarezerwować termin, wpłać zadatek:",
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": payment_url,
                            "title": "WPŁAĆ ZADATEK 20 ZŁ"
                        }
                    ]
                }
            }
        }
    else:
        # Simple text reply with Quick Replies
        message_payload = {
            "text": text,
            "quick_replies": [
                {
                    "content_type": "text",
                    "title": "📅 Zarezerwuj wizytę",
                    "payload": "BOOK_VISIT"
                },
                {
                    "content_type": "text",
                    "title": "🗓️ Sprawdź dostępność",
                    "payload": "CHECK_AVAILABILITY"
                },
                {
                    "content_type": "text",
                    "title": "📞 Zadzwoń do nas",
                    "payload": "CALL_SALON"
                },
                {
                    "content_type": "text",
                    "title": "📜 Cennik usług",
                    "payload": "SHOW_PRICES"
                }
            ]
        }

    payload = {
        "recipient": {"id": recipient_id},
        "message": message_payload
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Note: This requires a valid PAGE_ACCESS_TOKEN in .env
            # We skip the real call if token is placeholder to avoid errors.
            if len(access_token) > 20:
                await client.post(url, json=payload, timeout=5)
                logger.info("messenger_reply_sent", recipient=recipient_id)
        except Exception as e:
            logger.error("messenger_reply_failed", error=str(e))

async def _send_smart_telegram_alert(sender_id: str, text: str, sentiment: str, ai_answer: str):
    """Sends a detailed alert to the owner."""
    sentiment_icon = "🚨 PILNE" if sentiment == "NEGATIVE" else "📩"
    
    msg = (
        f"{sentiment_icon} <b>WIADOMOŚĆ (Messenger)</b>\n\n"
        f"<b>Klient ID:</b> <code>{sender_id}</code>\n"
        f"<b>Treść:</b> <i>{text}</i>\n\n"
        f"🤖 <b>Sugestia AI (RAG):</b>\n{ai_answer}\n\n"
        f"<i>Kliknij, aby odpowiedzieć w Meta Suite.</i>"
    )
    
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": settings.OWNER_TELEGRAM_ID, "text": msg, "parse_mode": "HTML"}
    
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, timeout=5)
