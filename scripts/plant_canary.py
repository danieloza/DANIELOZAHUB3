import sqlite3

DB_PATH = r"C:\Users\syfsy\projekty\salonos\salonos.db"

def plant_canari():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Create a table that should never be touched
    c.execute("CREATE TABLE IF NOT EXISTS canary_tokens (token TEXT, alert_email TEXT)")
    c.execute("INSERT INTO canary_tokens VALUES ('admin_reset_token_DoNotTouch', 'alert@danex.pl')")
    conn.commit()
    print("Canary planted. Monitor 'canary_tokens' table for unauthorized access.")
    conn.close()

if __name__ == "__main__":
    plant_canari()
