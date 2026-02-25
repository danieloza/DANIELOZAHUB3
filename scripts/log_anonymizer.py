import re
import glob

LOG_DIR = "logs"

def anonymize_logs():
    print("--- Running Hard Log Anonymizer ---")
    ip_pattern = r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    
    for log_file in glob.glob(f"{LOG_DIR}/*.log*"):
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        new_content = re.sub(ip_pattern, "0.0.0.0", content)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Anonymized: {log_file}")

if __name__ == "__main__":
    anonymize_logs()
