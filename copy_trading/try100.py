from websocket import create_connection

import json

ws = create_connection("ws://localhost:8000/ws/option-data/?api_key=1db783ee-b075-4e86-b4e4-6c18addf8f9d&access_token=eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODdiNjkzNDlkNTU2ZTZmMzJiOWYxZWUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MjkxODMyNCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUyOTYyNDAwfQ.Eins_5MP7jyJ5OTEcFn9KouQ5lCSKZTkDMrrIMJaPiE")
subscribe_msg = {"action": "subscribe", "instruments": ["NSE_FO|49487"]}
ws.send(json.dumps(subscribe_msg))

while True:
    result = ws.recv()  
    data = json.loads(result)
    ltp = data.get('ltp')  
    if ltp:
        print("LTP:", ltp)