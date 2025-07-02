import asyncio
import json
import ssl
import time
import requests
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from google.protobuf.json_format import MessageToDict
from . import MarketDataFeedV3_pb2 as pb


class LiveOptionDataConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.keep_running = True
        self.upstox_ws = None

    async def disconnect(self, close_code):
        self.keep_running = False
        if self.upstox_ws:
            await self.upstox_ws.close()

    async def receive(self, text_data):
        payload = json.loads(text_data)
        instrument_key = payload.get('instrument_key')
        expiry_date = payload.get('expiry_date')
        access_token = payload.get('access_token')

        if not instrument_key or not expiry_date or not access_token:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return

     
        asyncio.create_task(
            self.fetch_and_stream_data(instrument_key, expiry_date, access_token)
        )

    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token):
        option_chain_url = "https://api.upstox.com/v2/option/chain"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        params = {
            'instrument_key': instrument_key,
            'expiry_date': expiry_date
        }

        try:
            chain_response = requests.get(option_chain_url, headers=headers, params=params)
            chain_response.raise_for_status()
            option_data = chain_response.json()['data']
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'Option chain fetch failed: {str(e)}'}))
            return

        instrument_keys = []
        instrument_type_map = {}
        for item in option_data:
            if 'call_options' in item and item['call_options']:
                ik = item['call_options']['instrument_key']
                instrument_keys.append(ik)
                instrument_type_map[ik] = {'type': 'CE', 'strike': item.get('strike_price')}
            if 'put_options' in item and item['put_options']:
                ik = item['put_options']['instrument_key']
                instrument_keys.append(ik)
                instrument_type_map[ik] = {'type': 'PE', 'strike': item.get('strike_price')}

        if not instrument_keys:
            await self.send(text_data=json.dumps({'error': 'No instruments found.'}))
            return

        # WebSocket authorization
        try:
            auth_resp = requests.get(
                "https://api.upstox.com/v3/feed/market-data-feed/authorize",
                headers=headers
            ).json()
            ws_url = auth_resp['data']['authorized_redirect_uri']
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket auth failed: {str(e)}'}))
            return

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        last_update_time = time.time()

        try:
            async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                self.upstox_ws = ws

            
                for i in range(0, len(instrument_keys), 5):
                    chunk = instrument_keys[i:i + 5]
                    sub_msg = {
                        "guid": "some-guid",
                        "method": "sub",
                        "data": {
                            "mode": "full",
                            "instrumentKeys": chunk
                        }
                    }
                    await ws.send(json.dumps(sub_msg).encode("utf-8"))
                    await asyncio.sleep(0.2)

          
                while self.keep_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30)
                        last_update_time = time.time()
                    except asyncio.TimeoutError:
                        
                        if time.time() - last_update_time > 60:
                            await self.send(text_data=json.dumps({'info': 'No data for 60s. Reconnecting...'}))
                            break
                        else:
                            await self.send(text_data=json.dumps({'info': 'No new data in last 30s'}))
                            continue

                    try:
                        decoded = pb.FeedResponse()
                        decoded.ParseFromString(message)
                        data_dict = MessageToDict(decoded)
                    except Exception as e:
                        await self.send(text_data=json.dumps({'error': f'Decode error: {str(e)}'}))
                        continue

                    feeds = data_dict.get("feeds", {})
                    for ik, details in feeds.items():
                        market_data = details.get("fullFeed", {}).get("marketFF", {})
                        ltp_info = market_data.get("ltpc", {})
                        ltp = ltp_info.get("ltp")
                        ltt = ltp_info.get("ltt")

                        if not ltp or not ltt:
                            continue

                        current_ts = int(time.time() * 1000)
                        latency = current_ts - int(ltt)

                        info = instrument_type_map.get(ik)
                        if info:
                            result = {
                                'type': info['type'],
                                'strike': info['strike'],
                                'ltp': ltp,
                                'latency_ms': latency,
                                'timestamp': time.strftime('%H:%M:%S')
                            }
                            await self.send(text_data=json.dumps(result))

        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
