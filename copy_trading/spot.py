import requests

# ------------------------ Config ------------------------
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODZhMDg5ZjI1MzgzMzU3MjUyODdiMTkiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTc3OTQ4NywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxODM5MjAwfQ.5hUYTTw6JxLtb3jW6EhqDrxgccAYJoGrgS5sDZ83N-c"
SPOT_SYMBOL = "NSE_INDEX|Nifty Bank"  # You can change this to "NSE_INDEX|Nifty 50", etc.

LTP_URL = "https://api.upstox.com/v2/market-quote/ltp"
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# ------------------------ Spot Fetch Logic ------------------------
def get_spot_price():
    print("🔍 Fetching spot price...")
    try:
        response = requests.get(LTP_URL, headers=HEADERS, params={"symbol": SPOT_SYMBOL})
        print(f"🔍 Raw API Response: {response.status_code} | {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            actual_key = list(data['data'].keys())[0]
            ltp = data['data'][actual_key].get('last_price')
            print(f"📉 Live Spot Price: {ltp}")
            return ltp
        else:
            print(f"❌ Error fetching spot. Status: {response.status_code} | {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception in get_spot_price: {e}")
        return None

# ------------------------ Entry Point ------------------------
if __name__ == "__main__":
    get_spot_price()