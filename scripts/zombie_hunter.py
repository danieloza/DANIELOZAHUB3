from datetime import datetime, timedelta

def find_zombies():
    # Pseudo-code logic for DB check
    print("Scanning for zombie tokens (inactive > 30 days)...")
    cutoff = datetime.now() - timedelta(days=30)
    # query = "SELECT * FROM api_keys WHERE last_used_at < :cutoff"
    print("No zombies found (mock).")

if __name__ == "__main__":
    find_zombies()
