from kiteconnect import KiteConnect
import os

API_KEY = "e74wrp5cse4shibt"
API_SECRET = "dde81ug24m396drllbylt1ek3ocawstm"
REDIRECT_URL = "http://127.0.0.1:5000/callback/"
ACCESS_TOKEN_FILE = "zerodha_access_token.txt"

# Step 1: Generate login URL
def generate_login_url():
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    print("Open this URL in browser and login:", login_url)

# Step 2: Convert request token to access token
def generate_access_token(request_token):
    kite = KiteConnect(api_key=API_KEY)
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    # Save access token locally
    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    print("Access token saved:", access_token)
    return access_token

# Step 3 (optional): Load access token
def load_access_token():
    if not os.path.exists(ACCESS_TOKEN_FILE):
        raise Exception("Access token not found. Generate it first.")
    with open(ACCESS_TOKEN_FILE) as f:
        return f.read().strip()

# ================================
# Example usage
# ================================
if __name__ == "__main__":
    # 1️⃣ Generate login URL
    generate_login_url()

    # 2️⃣ Enter request token after logging in
    request_token = input("Enter the request token from URL: ").strip()

    # 3️⃣ Generate and save access token
    generate_access_token(request_token)

    # 4️⃣ Optional: Load the token later
    # token = load_access_token()
    # print("Loaded token:", token)
