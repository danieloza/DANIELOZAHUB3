import re
import quopri
import structlog

logger = structlog.get_logger("sync.booksy.email")

class BooksyEmailParser:
    """
    Senior IT: Parses Booksy notification emails to extract booking data.
    """
    def parse_email(self, html_body: str):
        # 1. Check if it's a cancellation
        is_cancellation = any(word in html_body.lower() for word in ["odwołana", "anulowana", "cancelled"])
        
        # 2. Extract Data
        patterns = {
            "client": r"Klient:\s*<b>(.*?)<\/b>",
            "service": r"Usługa:\s*<b>(.*?)<\/b>",
            "date": r"Data:\s*<b>(\d{4}-\d{2}-\d{2})",
            "time": r"Godzina:\s*<b>(\d{2}:\d{2})"
        }
        
        extracted = {}
        for key, regex in patterns.items():
            match = re.search(regex, html_body, re.IGNORECASE)
            extracted[key] = match.group(1) if match else None
            
        if all(extracted.values()):
            extracted["type"] = "cancellation" if is_cancellation else "new_booking"
            logger.info("booksy_email_processed", type=extracted["type"], client=extracted['client'])
            return extracted
        
        return None

def process_imap_emails(host, user, password):
    """
    Connects to Gmail/Poczta and looks for Booksy messages.
    (Conceptual implementation)
    """
    print(f"Connecting to {host} for user {user}...")
    # Logic: 
    # 1. search(UNSEEN FROM "noreply@booksy.com")
    # 2. for each msg: parse and push to salonos API
    pass
