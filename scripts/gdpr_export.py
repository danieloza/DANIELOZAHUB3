import sqlite3
import json
import sys
from datetime import datetime

DB_PATH = r"C:\Users\syfsy\projekty\salonos\salonos.db"

def export_client_data(client_name_part):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Find Client
    c.execute("SELECT * FROM clients WHERE name LIKE ?", (f"%{client_name_part}%",))
    clients = c.fetchall()
    
    if not clients:
        print("Client not found.")
        return
        
    for client in clients:
        client_id = client['id']
        print(f"--- Exporting data for: {client['name']} (ID: {client_id}) ---")
        
        data = {
            "profile": dict(client),
            "visits": [],
            "notes": [],
            "exported_at": datetime.now().isoformat()
        }
        
        # 2. Get Visits
        c.execute("SELECT * FROM visits WHERE client_id = ?", (client_id,))
        visits = c.fetchall()
        for v in visits:
            data["visits"].append(dict(v))
            
        # 3. Get Notes
        c.execute("SELECT * FROM client_notes WHERE client_id = ?", (client_id,))
        notes = c.fetchall()
        for n in notes:
            data["notes"].append(dict(n))
            
        # Save to file
        filename = f"GDPR_EXPORT_{client['id']}_{datetime.now().strftime('%Y%m%d')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Data saved to {filename}")

    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python gdpr_export.py <client_name>")
    else:
        export_client_data(sys.argv[1])
