import requests
import urllib.parse
import webbrowser
import json
import websocket

# ------------------- CONFIG -------------------
API_KEY = '1db783ee-b075-4e86-b4e4-6c18addf8f9d'
API_SECRET = 'jdt8pfnu8c'
REDIRECT_URI = 'http://localhost:8000/callback'

LOGIN_URL = f"https://api.upstox.com/v2/login/authorization/dialog" \
            f"?response_type=code&client_id={API_KEY}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"

# ------------------- STEP 1: User Login -------------------
print("\n🔐 Login via this URL and allow access:\n")
print(LOGIN_URL)
webbrowser.open(LOGIN_URL)

# ------------------- STEP 2: Capture Auth Code -------------------
auth_code = input("\n📥 Paste the 'code' from redirected URL: ").strip()

# ------------------- STEP 3: Exchange Auth Code for Token -------------------
def get_access_token(code):
    token_url = "https://api.upstox.com/v2/login/authorization/token"
    payload = {
        "client_id": API_KEY,
        "client_secret": API_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    print("\n🔄 Exchanging code for access token...")
    res = requests.post(token_url, headers=headers, data=payload)
    data = res.json()

    if "access_token" not in data:
        print("❌ Failed to get access token:\n", json.dumps(data, indent=2))
        exit(1)

    return data["access_token"]

access_token = get_access_token(auth_code)
print("✅ Access Token received.")

# ------------------- STEP 4: Get Authorized WebSocket URL -------------------
def get_ws_url(token):
    ws_auth_url = "https://api.upstox.com/v2/feed/market-data-feed/authorize"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(ws_auth_url, headers=headers)
    data = res.json()
    print("🧾 WS Auth Response:", json.dumps(data, indent=2))

    if "authorized_redirect_uri" not in data.get("data", {}):
        print("❌ Failed to get WebSocket URL:\n", json.dumps(data, indent=2))
        exit(1)

    return data["data"]["authorized_redirect_uri"]

ws_url = get_ws_url(access_token)
print("✅ Authorized WebSocket URL:", ws_url)

# ------------------- STEP 5: WebSocket Connection -------------------
def on_open(ws):
    print("📡 Connected to WebSocket!")

    # Use valid instrument key - Reliance example
    subscription_payload = {
        "guid": "abcde",
        "method": "sub",
        "data": {
            "mode": "full",  # Use 'full' for complete data
            "instrumentKeys": ["NSE_FO|49489"]  # Reliance Industries
        }
    }

    print("🔄 Sending subscription payload:\n", json.dumps(subscription_payload, indent=2))
    ws.send(json.dumps(subscription_payload))

def on_message(ws, message):
    print("📥 Market Feed:", message)

def on_error(ws, error):
    print("❗ WebSocket Error:", error)

def on_close(ws, status_code, msg):
    print("❌ WebSocket Disconnected. Code:", status_code, "Msg:", msg)

print("\n🔌 Connecting to WebSocket...\n")
ws = websocket.WebSocketApp(ws_url,
                            on_open=on_open,
                            on_message=on_message,
                            on_error=on_error,
                            on_close=on_close)

# Run WebSocket Forever
ws.run_forever()
