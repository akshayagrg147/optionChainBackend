import logging
import os

# Ensure logs directory exists
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# ===== Buy Logger =====
buy_log_file = os.path.join(LOG_DIR, 'order_log.txt')
buy_logger = logging.getLogger('buy_order_logger')
buy_logger.setLevel(logging.INFO)
if not buy_logger.handlers:
    buy_handler = logging.FileHandler(buy_log_file)
    buy_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    buy_logger.addHandler(buy_handler)

# ===== Sell Logger =====
sell_log_file = os.path.join(LOG_DIR, 'sell_log.txt')
sell_logger = logging.getLogger('sell_order_logger')
sell_logger.setLevel(logging.INFO)
if not sell_logger.handlers:
    sell_handler = logging.FileHandler(sell_log_file)
    sell_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    sell_logger.addHandler(sell_handler)
