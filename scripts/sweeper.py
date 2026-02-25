import sqlite3
from datetime import datetime, timedelta

DB_PATH = r"C:\Users\syfsy\projekty\salonos\salonos.db"

def sweep_stale_reservations():
    print("--- Running Stale Data Sweeper ---")
    
    threshold = datetime.now() - timedelta(minutes=30)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Example query assuming 'status' column exists
    query = """
    DELETE FROM reservation_requests 
    WHERE status = 'draft' 
    AND created_at < ?
    """
    
    cursor.execute(query, (threshold,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"Swept {deleted} stale reservations.")

if __name__ == "__main__":
    sweep_stale_reservations()
