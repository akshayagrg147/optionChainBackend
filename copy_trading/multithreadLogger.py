import time
import requests
import threading
from datetime import datetime
import os

# ------------------------ Configuration ------------------------
TOKENS = {
    "Thread 1": "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzWUNRM0MiLCJqdGkiOiI2ODgwNWNjYjk4NmI3MTI4ZGQzNzE5YzAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MzI0MjgyNywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUzMzA4MDAwfQ.6dB7LXJtZLCXbKoPoemsC9cHng3Oj0fcfgBeRDwUrhA",
    "Thread 2": "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzWUNRM0MiLCJqdGkiOiI2ODgwNWNjYjk4NmI3MTI4ZGQzNzE5YzAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MzI0MjgyNywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUzMzA4MDAwfQ.6dB7LXJtZLCXbKoPoemsC9cHng3Oj0fcfgBeRDwUrhA",
    "Thread 3": "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzWUNRM0MiLCJqdGkiOiI2ODgwNWNjYjk4NmI3MTI4ZGQzNzE5YzAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MzI0MjgyNywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUzMzA4MDAwfQ.6dB7LXJtZLCXbKoPoemsC9cHng3Oj0fcfgBeRDwUrhA",
    "Thread 4": "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzWUNRM0MiLCJqdGkiOiI2ODgwNWNjYjk4NmI3MTI4ZGQzNzE5YzAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MzI0MjgyNywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUzMzA4MDAwfQ.6dB7LXJtZLCXbKoPoemsC9cHng3Oj0fcfgBeRDwUrhA"
}

INSTRUMENT_KEY = "NSE_FO|54092"
LTP_URL = "https://api.upstox.com/v2/market-quote/ltp"
LOG_FILE = "ltp_log.txt"

# ------------------------ Show Log File Location ------------------------
print("Logging to:", os.path.abspath(LOG_FILE))

# ------------------------ Shared Lock for File Writes ------------------------
file_lock = threading.Lock()

# ------------------------ Log Startup Message ------------------------
with open(LOG_FILE, "a") as f:
    f.write(f"==== LTP Logging Started at {datetime.now()} ====\n")

# ------------------------ Worker Function ------------------------
def ltp_worker(thread_name, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    last_success_time = None

    while True:
        ts_req = time.time()
        try:
            response = requests.get(LTP_URL, headers=headers, params={"symbol": INSTRUMENT_KEY})
            ts_res = time.time()

            # Log status and response body for debugging
            with file_lock:
                with open(LOG_FILE, "a") as f:
                    f.write(f"{thread_name} | Status Code: {response.status_code}\n")
                    if response.status_code != 200:
                        f.write(f"{thread_name} | Response Text: {response.text}\n")

            if response.status_code == 200:
                data = response.json()
                actual_key = list(data['data'].keys())[0]
                ltp = data['data'][actual_key].get('last_price')

                latency_ms = (ts_res - ts_req) * 1000
                now_str = datetime.fromtimestamp(ts_res).strftime('%H:%M:%S.%f')[:-3]
                tsreq_str = datetime.fromtimestamp(ts_req).strftime('%H:%M:%S.%f')[:-3]
                tsres_str = datetime.fromtimestamp(ts_res).strftime('%H:%M:%S.%f')[:-3]

                if last_success_time is not None:
                    delta_t_ms = (ts_res - last_success_time) * 1000
                else:
                    delta_t_ms = 0.0

                log_line = (
                    f"{now_str} | {thread_name} | TSReq: {tsreq_str} | TSRes: {tsres_str} | "
                    f"LTP: {ltp} | Latency: {latency_ms:.1f} ms | t: {delta_t_ms:.1f} ms\n"
                )

                with file_lock:
                    with open(LOG_FILE, "a") as f:
                        f.write(log_line)

                last_success_time = ts_res

        except Exception as e:
            error_line = f"{datetime.now().strftime('%H:%M:%S')} | {thread_name} | Exception: {e}\n"
            with file_lock:
                with open(LOG_FILE, "a") as f:
                    f.write(error_line)

        time.sleep(0.05)  # Slightly higher delay to reduce throttling risk

# ------------------------ Main Execution ------------------------
if __name__ == "__main__":
    threads = []
    for name, token in TOKENS.items():
        t = threading.Thread(target=ltp_worker, args=(name, token), daemon=True)
        t.start()
        threads.append(t)

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        with file_lock:
            with open(LOG_FILE, "a") as f:
                f.write("==== Exiting due to KeyboardInterrupt ====\n")
