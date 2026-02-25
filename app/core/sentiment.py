def analyze_sentiment(note: str) -> str:
    negative_words = {"niezadowolona", "reklamacja", "krzywo", "brzydko", "drogo"}
    positive_words = {"super", "ekstra", "polecam", "pięknie", "wrócę"}
    
    note_lower = note.lower()
    
    neg_score = sum(1 for w in negative_words if w in note_lower)
    pos_score = sum(1 for w in positive_words if w in note_lower)
    
    if neg_score > pos_score:
        return "NEGATIVE"
    if pos_score > neg_score:
        return "POSITIVE"
    return "NEUTRAL"
