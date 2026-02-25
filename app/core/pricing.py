from datetime import datetime

def calculate_price(base_price: float, dt: datetime) -> float:
    multiplier = 1.0
    
    # Friday / Saturday Evening Surge
    if dt.weekday() in [4, 5] and dt.hour >= 17:
        multiplier = 1.1
        
    # December Surge
    if dt.month == 12:
        multiplier = 1.15
        
    return round(base_price * multiplier, 2)
