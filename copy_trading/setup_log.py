import logging
import os
import boto3
from dotenv import load_dotenv 


load_dotenv()


LOG_FILE = os.path.join(os.getcwd(), "websocket_stream.log")


logger = logging.getLogger("WebSocketLogger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(LOG_FILE, mode='a',encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)





def log_order_event(account_name: str, title: str, data: dict):
    log_block = [f"\n{'='*20} {account_name.upper()} | {title} {'='*20}"]
    for key, value in data.items():
        log_block.append(f"{key}: {value}")
    log_block.append('-' * 60)
    logger.info('\n'.join(log_block))
   
