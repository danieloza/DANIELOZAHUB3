import sqlite3
import sys
from datetime import datetime, timedelta

DB_PATH = r"C:\Users\syfsy\projekty\salonos\salonos.db"
RETENTION_YEARS = 3

def run_maintenance():
    print("--- Starting SalonOS Daily Maintenance ---")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. GDPR Reaper: Anonymize old clients
        cutoff_date = (datetime.now() - timedelta(days=365 * RETENTION_YEARS)).strftime("%Y-%m-%d")
        print(f"Running GDPR cleanup for clients inactive since {cutoff_date}...")
        
        # Find clients with no visits after cutoff
        # (Simplified logic: anonymize if last visit < cutoff)
        # In a real scenario, this SQL would be more complex joining visits.
        # For safety in this demo, we just print what we WOULD do.
        print("[DRY RUN] Would anonymize clients inactive for 3 years.")
        
        # 2. SQLite VACUUM (Defrag)
        print("Running VACUUM to optimize database size...")
        conn.execute("VACUUM;")
        print("Database optimized.")
        
        conn.close()
        print("Maintenance complete.")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_maintenance()
