import asyncio
import json
import ssl
import requests
import websockets
from google.protobuf.json_format import MessageToDict

import MarketDataFeedV3_pb2 as pb


ACCESS_TOKEN = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJBSDIyNTciLCJqdGkiOiI2ODYzNjU0NjY2NWYzYjFiYjQzYWYzZGMiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1MTM0NDQ1NCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzUxNDA3MjAwfQ.h2EFnJu-PXBg65HphVjPLEw2ZsB_DbaAeZqqjqTTkaA'  # 🔒 Replace with your actual token


def get_market_data_feed_authorize_v3():
    """
    Gets authorized WebSocket URI for market data from Upstox API.
    """
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {ACCESS_TOKEN}'
    }
    url = 'https://api.upstox.com/v3/feed/market-data-feed/authorize'
    api_response = requests.get(url=url, headers=headers)
    return api_response.json()


def decode_protobuf(buffer):
    """
    Decode protobuf binary WebSocket response into readable dictionary.
    """
    feed_response = pb.FeedResponse()
    feed_response.ParseFromString(buffer)
    return feed_response


async def fetch_market_data():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Step 1: Get WebSocket URI
    response = get_market_data_feed_authorize_v3()
    ws_url = response["data"]["authorized_redirect_uri"]

    # Step 2: Get all instrument keys (call and put options)
    option_chain_url = "https://api.upstox.com/v2/option/chain"
    headers = {
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    params = {
        'instrument_key': 'NSE_INDEX|Nifty 50',
        'expiry_date': '2025-07-10' 
    }

    chain_response = requests.get(option_chain_url, headers=headers, params=params)
    if chain_response.status_code != 200:
        print("❌ Failed to fetch option chain:", chain_response.status_code)
        return

    option_data = chain_response.json()['data']

    # Extract CE and PE instrument keys
    instrument_keys = []
    for item in option_data:
        if 'call_options' in item and item['call_options']:
            instrument_keys.append(item['call_options']['instrument_key'])
        if 'put_options' in item and item['put_options']:
            instrument_keys.append(item['put_options']['instrument_key'])

    print(f"📦 Total instruments: {len(instrument_keys)}")
    print(instrument_keys)

    # Step 3: Connect to WebSocket
    async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
        print("✅ WebSocket connection established.")

        # Step 4: Subscribe in chunks to avoid rate limits
        for i in range(0, len(instrument_keys), 5):
            chunk = instrument_keys[i:i + 5]
            subscribe_payload = {
                "guid": "some-guid-123",  # You can use uuid.uuid4() if needed
                "method": "sub",
                "data": {
                    "mode": "full",
                    "instrumentKeys": ['NSE_FO|40196']
                }
            }
            await websocket.send(json.dumps(subscribe_payload))
            await asyncio.sleep(0.2)  # avoid overloading

        print("📡 Subscriptions sent. Waiting for live data...")

        # Step 5: Handle live data stream
        while True:
            try:
                message = await websocket.recv()
                decoded = decode_protobuf(message)
                data_dict = MessageToDict(decoded)
                print(json.dumps(data_dict, indent=2))
            except Exception as e:
                print(f"⚠️ Error decoding message: {e}")


# Entry point
asyncio.run(fetch_market_data())
