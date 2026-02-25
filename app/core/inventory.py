from collections import defaultdict

def predict_inventory_usage(visits_last_month: list):
    """
    Analyzes services to predict product usage.
    """
    usage = defaultdict(int)
    for v in visits_last_month:
        svc = v.get("service_name", "").lower()
        if "koloryzacja" in svc:
            usage["tubka_farby"] += 1
            usage["oxydant"] += 1
        elif "mycie" in svc:
            usage["szampon_porcja"] += 1
            
    alerts = []
    if usage["tubka_farby"] > 20:
        alerts.append("📉 Kończy się farba podstawowa!")
        
    return alerts
