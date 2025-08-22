from filelock import FileLock
import os
from datetime import datetime
import boto3
from dotenv import load_dotenv  

# ✅ Load .env variables
load_dotenv()



# ✅ Set log file paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE_PATH = os.path.join(LOG_DIR, 'upstox_orders.txt')
LOCK_FILE_PATH = LOG_FILE_PATH + '.lock'

# ✅ Function to write and upload log
def write_log_to_txt(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"{timestamp} - {message}\n"

    lock = FileLock(LOCK_FILE_PATH)

    with lock:
        with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(full_message)

   