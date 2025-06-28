import requests


ACCESS_TOKEN = "your_access_token"
instrument_key = "NSE_INDEX|NIFTY"
expiry_date = "2025-07-03"  

def fetch_option_chain(symbol, expiry_date):
    url = f"https://api.upstox.com/v2/option/chain?instrument_key={instrument_key}&expiry_date={expiry_date}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    res = requests.get(url, headers=headers)
    data = res.json()
    
    instruments = []
    for item in data.get("data", {}).get("optionChains", []):
        ce = item.get("call", {}).get("instrumentToken")
        pe = item.get("put", {}).get("instrumentToken")
        if ce:
            instruments.append(ce)
        if pe:
            instruments.append(pe)
    return instruments