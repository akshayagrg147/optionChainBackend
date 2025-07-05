import requests

# 🔐 Paste your valid access token here
access_token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODY3NWNmODE4NzU5ZDY1ZGJhMjFjNTciLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTYwNDQ3MiwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxNjY2NDAwfQ.W4xv-1bQ7PkkeFIhwhg1IuMR26-vhpvEkZpmr1gsgZ4"

url = "https://api.upstox.com/v2/user/profile"

headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {access_token}"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()
    user_name = data.get("data", {}).get("user_name", "Unknown")
    print(f"✅ Upstox User Name: {user_name}")
else:
    print("❌ Failed to fetch profile")
    print(response.status_code)
    print(response.text)