import structlog
from sqlalchemy.orm import Session
from ..models import Client

logger = structlog.get_logger("marketing.loyalty")

def update_loyalty_after_visit(db: Session, client_id: int, price: float):
    """
    Senior IT: Increments visits and awards points (1 point per 10 PLN spent).
    Automatically promotes to VIP if visits > 10.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return
    
    points_earned = int(price // 10)
    client.visits_count += 1
    client.loyalty_points += points_earned
    
    if client.visits_count >= 10:
        client.is_vip = True
        logger.info("client_promoted_to_vip", client_id=client_id)
        
    db.commit()
    logger.info("loyalty_updated", client_id=client_id, points_earned=points_earned)
    return client
