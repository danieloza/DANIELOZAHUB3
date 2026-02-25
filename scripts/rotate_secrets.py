import secrets
import re
from pathlib import Path

ENV_PATH = Path(".env")

def rotate_secrets():
    print("--- Starting Emergency Secret Rotation ---")
    if not ENV_PATH.exists():
        print("Error: .env not found")
        return

    content = ENV_PATH.read_text(encoding="utf-8")
    
    # Rotate JWT_SECRET
    new_secret = secrets.token_urlsafe(64)
    if "JWT_SECRET=" in content:
        content = re.sub(r"JWT_SECRET=.*", f"JWT_SECRET={new_secret}", content)
        print("[OK] JWT_SECRET rotated.")
    
    # Rotate API Key
    new_key = secrets.token_hex(32)
    if "ADMIN_API_KEY=" in content:
        content = re.sub(r"ADMIN_API_KEY=.*", f"ADMIN_API_KEY={new_key}", content)
        print("[OK] ADMIN_API_KEY rotated.")

    ENV_PATH.write_text(content, encoding="utf-8")
    print("Secrets updated. RESTART APPLICATION NOW!")

if __name__ == "__main__":
    rotate_secrets()
