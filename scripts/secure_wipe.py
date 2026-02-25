import os
import secrets

def secure_delete(file_path, passes=3):
    """Overwrites file with random data before deleting."""
    if not os.path.exists(file_path):
        return

    length = os.path.getsize(file_path)
    
    with open(file_path, "br+") as f:
        for _ in range(passes):
            f.seek(0)
            f.write(secrets.token_bytes(length))
            
    os.remove(file_path)
    print(f"Securely deleted: {file_path}")

# Example usage (commented out for safety)
# secure_delete("secret_backup.zip")
