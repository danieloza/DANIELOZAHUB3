import os
import glob

DANGEROUS_OPS = ["ALTER TABLE", "DROP COLUMN", "DEFAULT"]

def scan_migrations():
    print("--- Senior IT: Migration Safety Check ---")
    files = glob.glob("alembic/versions/*.py")
    
    clean = True
    for file in files:
        with open(file, 'r') as f:
            content = f.read()
            for op in DANGEROUS_OPS:
                if op in content:
                    print(f"[WARN] {file} contains potentially locking operation: {op}")
                    clean = False
    
    if clean:
        print("[PASS] No dangerous migration operations found.")

if __name__ == "__main__":
    scan_migrations()
