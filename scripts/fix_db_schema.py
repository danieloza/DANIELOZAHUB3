import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "salonos.db"

def fix_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("🔧 Naprawianie schematu bazy danych...")
        
        # Sprawdź i dodaj kolumny do employees
        cursor.execute("PRAGMA table_info(employees)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "rating" not in columns:
            cursor.execute("ALTER TABLE employees ADD COLUMN rating FLOAT DEFAULT 5.0")
            print("✅ Dodano employees.rating")

        # --- TENANTS ---
        cursor.execute("PRAGMA table_info(tenants)")
        t_cols = [row[1] for row in cursor.fetchall()]
        
        tenant_fixes = [
            ("logo_url", "VARCHAR(500)"),
            ("headline", "VARCHAR(200)"),
            ("about_us", "TEXT"),
            ("address", "VARCHAR(255)"),
            ("city", "VARCHAR(100)"),
            ("google_maps_url", "VARCHAR(500)"),
            ("instagram_url", "VARCHAR(255)"),
            ("facebook_url", "VARCHAR(255)"),
            ("website_url", "VARCHAR(255)"),
            ("contact_email", "VARCHAR(160)"),
            ("contact_phone", "VARCHAR(40)"),
            ("industry_type", "VARCHAR(50) DEFAULT 'general_beauty'"),
            ("rating_avg", "FLOAT DEFAULT 5.0")
        ]

        for col_name, col_type in tenant_fixes:
            if col_name not in t_cols:
                cursor.execute(f"ALTER TABLE tenants ADD COLUMN {col_name} {col_type}")
                print(f"✅ Dodano tenants.{col_name}")

        if "bio" not in columns:
            cursor.execute("ALTER TABLE employees ADD COLUMN bio VARCHAR(500)")
            print("✅ Dodano employees.bio")
            
        if "specialties" not in columns:
            cursor.execute("ALTER TABLE employees ADD COLUMN specialties VARCHAR(200)")
            print("✅ Dodano employees.specialties")
            
        if "is_portfolio_public" not in columns:
            cursor.execute("ALTER TABLE employees ADD COLUMN is_portfolio_public BOOLEAN DEFAULT 1")
            print("✅ Dodano employees.is_portfolio_public")

        # Sprawdź i dodaj kolumnę do visits (jeśli brakuje)
        # Tu przykład, gdybyśmy coś zmieniali w visits, ale na razie chyba OK.
        
        conn.commit()
        print("🎉 Baza danych zaktualizowana!")
        
    except Exception as e:
        print(f"❌ Błąd aktualizacji bazy: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_schema()
