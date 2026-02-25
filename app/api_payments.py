from fastapi import APIRouter, Request, Header, HTTPException
import stripe
import structlog
from .config import settings

router = APIRouter(prefix="/payments", tags=["payments"])
logger = structlog.get_logger("fintech.webhook")

@router.post("/create-intent")
async def create_payment_intent(visit_id: int):
    """
    Senior IT: Creates a Stripe PaymentIntent for the web-based elements.
    """
    try:
        # Create a PaymentIntent with the order amount and currency
        intent = stripe.PaymentIntent.create(
            amount=settings.DEPOSIT_AMOUNT_PLN * 100,
            currency='pln',
            automatic_payment_methods={
                'enabled': True,
            },
            metadata={"visit_id": visit_id}
        )
        logger.info("payment_intent_created", visit_id=visit_id, intent_id=intent.id)
        return {"clientSecret": intent.client_secret}
    except Exception as e:
        logger.error("stripe_intent_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request, x_stripe_signature: str = Header(None)):
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, x_stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error("stripe_webhook_invalid", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        visit_id = session.get("metadata", {}).get("visit_id")
        
        logger.info("payment_confirmed", visit_id=visit_id)
        # Logic: Update visit status in DB to 'deposit_paid'
        # await confirm_visit_deposit(visit_id)

    return {"status": "success"}
