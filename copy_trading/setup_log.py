import logging
import os
import boto3
from dotenv import load_dotenv 


load_dotenv()

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME2")  


LOG_FILE = os.path.join(os.getcwd(), "websocket_stream.log")


logger = logging.getLogger("WebSocketLogger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(LOG_FILE, mode='a',encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)


def upload_log_to_s3():
    try:
        s3.upload_file(LOG_FILE, S3_BUCKET_NAME, 'logs/websocket_stream.log')
        logger.info(f"✅ Log uploaded to s3://{S3_BUCKET_NAME}/logs/websocket_stream.log")
    except Exception as e:
        logger.error(f"❌ Failed to upload log to S3: {e}")


def log_order_event(account_name: str, title: str, data: dict):
    log_block = [f"\n{'='*20} {account_name.upper()} | {title} {'='*20}"]
    for key, value in data.items():
        log_block.append(f"{key}: {value}")
    log_block.append('-' * 60)
    logger.info('\n'.join(log_block))
    upload_log_to_s3()
