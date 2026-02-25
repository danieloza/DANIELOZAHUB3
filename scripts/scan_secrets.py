import sys
import re

# Simple patterns for secrets
PATTERNS = [
    r"sk_live_[0-9a-zA-Z]{24}", # Stripe
    r"xoxb-[0-9]{10}", # Slack
    r"-----BEGIN PRIVATE KEY-----",
    r"PESEL\s*[:=]\s*\d{11}",
    r"CVV\s*[:=]\s*\d{3}"
]

def scan_files(files):
    found = False
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
                for pattern in PATTERNS:
                    if re.search(pattern, content):
                        print(f"[FAIL] Potential secret in {file} matches {pattern}")
                        found = True
        except Exception:
            pass # Binary file or other error
    return found

if __name__ == "__main__":
    if scan_files(sys.argv[1:]):
        sys.exit(1)
    print("No secrets found.")
