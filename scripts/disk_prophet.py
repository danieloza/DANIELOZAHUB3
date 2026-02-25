import shutil
import os

def predict_disk_usage():
    total, used, free = shutil.disk_usage(".")
    
    # Estimate daily growth (mocked logic, normally would check historical file sizes)
    # Assume 50MB / day growth
    daily_growth_mb = 50 
    
    free_mb = free // (1024 * 1024)
    days_left = free_mb // daily_growth_mb
    
    print(f"--- Disk Space Prophet ---")
    print(f"Free Space: {free_mb} MB")
    print(f"Est. Growth: {daily_growth_mb} MB/day")
    print(f"Safe for approx: {days_left} days")
    
    if days_left < 30:
        print("WARNING: Less than 30 days of storage left!")

if __name__ == "__main__":
    predict_disk_usage()
