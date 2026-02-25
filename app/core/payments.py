import stripe
import structlog
from .config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = structlog.get_logger("fintech.stripe")

def create_deposit_session(visit_id: int, client_email: str):
    """
    Senior IT: Creates a Stripe Checkout Session for non-refundable deposit.
    """
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'pln',
                    'product_data': {
                        'name': 'Zadatek rezerwacyjny - Salon Danex',
                        'description': 'Zadatek bezzwrotny w przypadku niepojawienia się na wizycie (art. 394 KC)',
                    },
                    'unit_amount': settings.DEPOSIT_AMOUNT_PLN * 100, # In cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{settings.API_BASE_URL}/api/payments/success?visit_id={visit_id}",
            cancel_url=f"{settings.API_BASE_URL}/api/payments/cancel?visit_id={visit_id}",
            metadata={"visit_id": visit_id}
        )
        logger.info("payment_session_created", visit_id=visit_id, session_id=session.id)
        return session.url
    except Exception as e:
        logger.error("stripe_session_failed", error=str(e))
        return None
