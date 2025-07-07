import requests

# Replace this with your actual Upstox access token
access_token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODZiNDhkNTE1MTlmNDIzMjk4ZjQ5NGYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTg2MTQ2MSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxOTI1NjAwfQ.nrGF1OajVHP77NYuvFDMIMSxzXbYU-S28AmFEyFLgKc"

url = "https://api.upstox.com/v2/user/get-funds-and-margin"

headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {access_token}"
}

try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # raises error for 4xx/5xx
    data = response.json()
    print("Funds Data:", data)
except requests.exceptions.HTTPError as http_err:
    print("HTTP error occurred:", http_err)
except Exception as err:
    print("Other error occurred:", err)
