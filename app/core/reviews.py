import structlog
from .sentiment import analyze_sentiment

logger = structlog.get_logger("marketing.reviews")

def evaluate_for_review_request(client_name: str, visit_note: str, price: float):
    """
    Senior IT: Determines if we should ask a client for a Google review.
    Logic: High price + Positive sentiment in notes = High probability of satisfaction.
    """
    sentiment = analyze_sentiment(visit_note)
    
    if sentiment == "POSITIVE" or (price > 200 and sentiment == "NEUTRAL"):
        logger.info(
            "review_candidate_found",
            client=client_name,
            reason="High value or positive feedback"
        )
        return True
    
    return False
