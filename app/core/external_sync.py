import httpx
from icalendar import Calendar
from datetime import datetime
import structlog

logger = structlog.get_logger("sync.booksy")

async def fetch_booksy_events(ical_url: str):
    """
    Senior IT: Periodic fetch of Booksy iCal feed.
    """
    logger.info("starting_booksy_sync", url=ical_url[:20] + "...")
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(ical_url)
            response.raise_for_status()
            
        cal = Calendar.from_ical(response.content)
        events = []
        
        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary'))
                start_dt = component.get('dtstart').dt
                end_dt = component.get('dtend').dt
                
                # Normalize to naive datetime for SQLite comparison if needed
                if isinstance(start_dt, datetime):
                    start_dt = start_dt.replace(tzinfo=None)
                
                events.append({
                    "summary": summary,
                    "start": start_dt,
                    "end": end_dt,
                    "source": "booksy"
                })
        
        logger.info("booksy_sync_complete", found_events=len(events))
        return events
        
    except Exception as e:
        logger.error("booksy_sync_failed", error=str(e))
        return []
