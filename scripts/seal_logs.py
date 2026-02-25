import hashlib
import glob
import os

LOG_DIR = "logs"
SEAL_FILE = "logs/log_seals.sha256"

def seal_logs():
    print("--- Sealing Logs (Immutability Check) ---")
    
    with open(SEAL_FILE, 'a') as seal:
        for log_file in glob.glob(f"{LOG_DIR}/*.log*"):
            if log_file == SEAL_FILE: continue
            
            with open(log_file, 'rb') as f:
                bytes = f.read()
                readable_hash = hashlib.sha256(bytes).hexdigest()
                
            entry = f"{readable_hash}  {log_file}  {os.path.getmtime(log_file)}
"
            seal.write(entry)
            print(f"Sealed: {log_file} -> {readable_hash[:10]}...")

if __name__ == "__main__":
    seal_logs()
