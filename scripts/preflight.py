import shutil
import socket
import sys

def check_disk_space():
    total, used, free = shutil.disk_usage(".")
    free_gb = free // (2**30)
    if free_gb < 1:
        print(f"[FAIL] Low disk space: {free_gb}GB free")
        return False
    print(f"[PASS] Disk space: {free_gb}GB free")
    return True

def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        is_free = s.connect_ex(('localhost', port)) != 0
    if not is_free:
        print(f"[FAIL] Port {port} is occupied")
        return False
    print(f"[PASS] Port {port} is free")
    return True

if __name__ == "__main__":
    ok = check_disk_space()
    ok = check_port(8000) and ok
    
    if not ok:
        sys.exit(1)
    print("System ready for takeoff ✈️")
