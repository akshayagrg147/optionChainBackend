
import websocket
import json
import redis
import time
import msgpack
import uuid

from io import BytesIO

ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODVmNzUzOTk2ZDE4ODdiMjFmYzFlMzgiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTA4NjM5MywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxMTQ4MDAwfQ.oJYx9iIVi46TTmCtGBfxrzM0-w3KdYdusbiKE2w6CPE"
REDIS = redis.StrictRedis(host='localhost', port=6379, db=0)

def on_open(ws):
    print(" WebSocket connected")
    guid = str(uuid.uuid4())

    
    r = redis.StrictRedis(host='127.0.0.1', port=6379, db=0)
    expiry_date = "2025-07-03"  
    raw_tokens = r.get(f"option_chain_tokens:{expiry_date}")
    tokens = json.loads(raw_tokens)
    
    if not raw_tokens:
        print(f" No tokens found for {expiry_date} in Redis")
        return

    try:
        tokens = json.loads(raw_tokens)
    except json.JSONDecodeError:
        print("Error decoding token JSON")
        return

    print("Subscribing to tokens:", tokens)
   
    payload = {
        "guid": guid,  
        "method": "sub",
        "data": {
            "mode": "full",  
            "instrumentKeys": tokens
        }
    }
    ws.send(msgpack.packb(payload))
    print("Subscribed to tokens:", tokens)

def on_message(ws, message):
    try:
        unpacker = msgpack.Unpacker(BytesIO(message), raw=False)

        for decoded in unpacker:
            if not isinstance(decoded, dict):
                print("Skipped non-dict message:", decoded)
                continue

            print("Decoded message:", decoded)

            data = decoded.get("data", {}).get("feeds", {})
            if not data:
                continue

            for token, info in data.items():
                strike_price = info.get("strikePrice")
                option_type = info.get("optionType")
                ltp = info.get("ltp")
                volume = info.get("volumeTradedToday")

                if strike_price is None or option_type not in ["CE", "PE"]:
                    continue

                redis_data = {
                    "strike": strike_price,
                    "type": option_type,
                    "ltp": ltp,
                    "volume": volume
                }

                # Publish to Redis channel
                REDIS.publish("live_option_data", json.dumps(redis_data))

    except Exception as e:
        print("Error processing message:", e)

def on_error(ws, error):
    print("Error:", error)

def on_close(ws, close_status_code, close_msg):
    print(" WebSocket closed")

if __name__ == "__main__":
    while True:
        try:
            ws = websocket.WebSocketApp(
            "wss://api.upstox.com/v3/feed/market-data-feed",
            header=[
                f"Authorization: Bearer {ACCESS_TOKEN}"
            ],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
            ws.run_forever()
        except Exception as e:
            print("🔥 Reconnecting in 5 seconds...", str(e))
            time.sleep(5)
