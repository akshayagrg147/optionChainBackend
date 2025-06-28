import requests

ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODVlZTYyOTk2ZDE4ODdiMjFmYzFiMGEiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTA0OTc2OSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxMDYxNjAwfQ.T5DXcTz1FqGLm3pm0FTLJ75tsWX7YYl_pzI_mZJc758"
instrument_key = "NSE_INDEX|Nifty 50"
expiry_date = "2025-07-03"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

url = f"https://api.upstox.com/v2/option/chain?instrument_key={instrument_key}&expiry_date={expiry_date}"

response = requests.get(url, headers=headers)

print(response.status_code)
print(response.json())