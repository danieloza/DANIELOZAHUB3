import structlog

logger = structlog.get_logger("security.blacklist")

def record_no_show(client_id: int):
    """
    Senior IT: Tracks missing clients and applies penalties.
    """
    # 1. Logic to increment 'no_show_count' in DB
    # 2. If count >= 2, mark client as 'blacklisted'
    
    logger.warning("client_no_show_recorded", client_id=client_id)
    return "Ostrzeżenie dodane do profilu klienta."

def is_client_allowed_to_book(client_id: int) -> bool:
    """
    Checks if client is on the blacklist.
    """
    # Logic: SELECT is_blacklisted FROM clients WHERE id = :client_id
    # Mocking for now:
    blacklisted = False 
    return not blacklisted
