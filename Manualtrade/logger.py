from filelock import FileLock
import os
from datetime import datetime
import boto3
from dotenv import load_dotenv  

# ✅ Load .env variables
load_dotenv()

# ✅ Get environment variables
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

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

    upload_log_to_s3()


def upload_log_to_s3():
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )

    
        s3_key = f"logs/upstox_orders.txt"

        s3_client.upload_file(LOG_FILE_PATH, S3_BUCKET_NAME, s3_key)

    except Exception as e:
        error_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ❌ Failed to upload log to S3: {str(e)}\n"
        with FileLock(LOCK_FILE_PATH):
            with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
                f.write(error_message)
