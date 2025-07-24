import requests
import time
from datetime import datetime


ACCESS_TOKEN = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODdkYzE1YzE5MDFlYTQzODMxYmU3MzEiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MzA3MTk2NCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUzMTM1MjAwfQ.khCKMXLGqMQHRk5F70CGw2XGBNm_oXCnWCZSQ8qmniY'
INSTRUMENT_KEY = 'NSE_FO|49489'  
INTERVAL_SECONDS = 0.01


URL = "https://api.upstox.com/v3/market-quote/ltp"


headers = {
    'accept': 'application/json',
    'Api-Version': '2.0',
    'Authorization': f'Bearer {ACCESS_TOKEN}'
}


def get_live_ltp():
    with open("ltp_log.txt", "a") as file:
        while True:
            try:
                params = {'instrument_key': INSTRUMENT_KEY}
                response = requests.get(URL, headers=headers, params=params)
                data = response.json()

                if response.status_code == 200 and 'data' in data:
                    instrument_data = list(data['data'].values())[0]
                    ltp = instrument_data.get('last_price')
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"🕒 {timestamp} | 📈 LTP: {ltp}")
                    file.write(f"{timestamp} | LTP: {ltp}\n")
                    file.flush()  
                else:
                    print("❌ Failed to fetch LTP:", data)

            except Exception as e:
                print("⚠️ Error:", str(e))

            time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    get_live_ltp()
    get_live_ltp()
