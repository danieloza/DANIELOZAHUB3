import imaplib
import email
from email.header import decode_header
import structlog
import time
from .booksy_email_sync import BooksyEmailParser
from ..config import settings

logger = structlog.get_logger("sync.email.watcher")
parser = BooksyEmailParser()

async def check_for_new_bookings():
    """
    Senior IT: Connects to IMAP and processes unread Booksy emails.
    """
    if not settings.IMAP_ENABLED or not settings.IMAP_USER or not settings.IMAP_PASS:
        return

    try:
        # Connect to server
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST)
        mail.login(settings.IMAP_USER, settings.IMAP_PASS)
        mail.select("inbox")

        # Search for unread emails from Booksy
        # Note: You can adjust the sender address
        status, messages = mail.search(None, '(UNSEEN FROM "noreply@booksy.com")')
        
        if status != "OK":
            logger.error("imap_search_failed", status=status)
            return

        for num in messages[0].split():
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK": continue
            
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = msg.get_payload(decode=True).decode()

            # Parse
            booking = parser.parse_email(body)
            if booking:
                if booking["type"] == "cancellation":
                    logger.info("handling_cancellation", client=booking['client'])
                    # Logic: Find visit in DB and set status to 'cancelled'
                    # await cancel_visit_in_db(booking)
                else:
                    logger.info("handling_new_booking", client=booking['client'])
                    # Logic: Add to DB
                    # await add_visit_to_db(booking)
            
            # Mark as read is automatic with SELECT/SEARCH usually, 
            # but we can explicitly set flags if needed.

        mail.logout()
        
    except Exception as e:
        logger.error("email_watcher_critical_error", error=str(e))
