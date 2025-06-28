import json
from redis_config import redis_client

def store_option_data(instrument_key, data):
    redis_client.set(f"option_data:{instrument_key}", json.dumps(data))

def get_option_data(instrument_key):
    data = redis_client.get(f"option_data:{instrument_key}")
    return json.loads(data) if data else None