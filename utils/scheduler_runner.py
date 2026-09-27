import time
from utils.scheduler import run_hourly_aggregation, run_shift_aggregation
def start_scheduler():
    print("Scheduler started...")

    while True:
        try:
            run_shift_aggregation()   # every loop (near real-time)
            run_hourly_aggregation() # safe (idempotent)

        except Exception as e:
            print("Scheduler error:", e)

        time.sleep(300)  # run every 5 minutes