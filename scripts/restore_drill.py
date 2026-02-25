import shutil
import sqlite3
import os
import glob
from pathlib import Path

BACKUP_DIR = r"C:\Users\syfsy\projekty\salonos\backups"
RESTORE_TEST_DIR = r"C:\Users\syfsy\projekty\salonos\backupsestore_test"

def run_restore_drill():
    print("--- Starting Automated Restore Drill ---")
    
    # 1. Find latest backup
    list_of_files = glob.glob(os.path.join(BACKUP_DIR, '*.bak'))
    if not list_of_files:
        print("[FAIL] No backups found to test.")
        return

    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"Testing backup: {os.path.basename(latest_file)}")

    # 2. Prepare isolated environment
    if not os.path.exists(RESTORE_TEST_DIR):
        os.makedirs(RESTORE_TEST_DIR)
        
    target_db = os.path.join(RESTORE_TEST_DIR, "restored_test.db")
    if os.path.exists(target_db):
        os.remove(target_db)

    # 3. Restore (Copy)
    try:
        shutil.copy2(latest_file, target_db)
    except Exception as e:
        print(f"[FAIL] Copy failed: {e}")
        return

    # 4. Integrity Check
    try:
        conn = sqlite3.connect(target_db)
        cursor = conn.cursor()
        
        # Basic check
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        count = cursor.fetchone()[0]
        
        # Deep check
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        
        conn.close()
        
        if count > 0 and integrity == "ok":
            print(f"[PASS] Backup is valid. Tables found: {count}. Integrity: {integrity}.")
        else:
            print(f"[FAIL] Database corrupted. Integrity: {integrity}")
            
    except Exception as e:
        print(f"[FAIL] Database connection failed: {e}")
    finally:
        # Cleanup
        if os.path.exists(target_db):
            os.remove(target_db)
            print("Cleanup complete.")

if __name__ == "__main__":
    run_restore_drill()
