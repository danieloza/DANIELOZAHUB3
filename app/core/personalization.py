from sqlalchemy import Column, String, Date
from .db import Base

# Senior IT: Extend Client Model (Conceptual - requires migration)
# We assume this is added to models.py

class ClientPreferences(Base):
    __tablename__ = "client_preferences"
    # ... FK setup ...
    coffee_type = Column(String(50)) # "Black", "Latte"
    conversation_style = Column(String(50)) # "Chatty", "Silent"
    birthday = Column(Date)
    
def get_client_briefing(client_id: int):
    """
    Returns a short text for the stylist before visit.
    """
    # ... logic to fetch prefs ...
    return "☕ Kawa: Czarna | 🗣 Rozmowa: Mało | 🎂 Urodziny: Za 3 dni!"
