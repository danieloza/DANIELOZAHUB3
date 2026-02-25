import hashlib
import json
from datetime import datetime

def calculate_audit_hash(previous_hash: str, action: str, actor: str, timestamp: str, payload: dict) -> str:
    """
    Creates a tamper-proof hash linking this entry to the previous one.
    """
    data_string = f"{previous_hash}|{action}|{actor}|{timestamp}|{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha256(data_string.encode()).hexdigest()

def sign_audit_entry(entry: dict, previous_entry: dict | None) -> dict:
    prev_hash = previous_entry.get("hash", "00000000000000000000000000000000") if previous_entry else "0" * 64
    
    current_hash = calculate_audit_hash(
        prev_hash,
        entry.get("action"),
        entry.get("actor_email"),
        entry.get("created_at", datetime.now().isoformat()),
        entry.get("payload_json", {})
    )
    
    entry["hash"] = current_hash
    entry["previous_hash"] = prev_hash
    return entry
