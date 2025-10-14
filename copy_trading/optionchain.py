import asyncio
import json
import ssl
import time
import requests
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from google.protobuf.json_format import MessageToDict
from . import MarketDataFeedV3_pb2 as pb
from datetime import datetime
from .setup_log import log_order_event, logger

class LiveOptionData(AsyncWebsocketConsumer):
    def reset_trade_flags(self):
        self.sell_order_placed = False
        self.locked_ltp = None
        self.previous_ltp = None

    def log_order_event(account_name: str, title: str, data: dict):
        log_block = [f"\n{'='*20} {account_name.upper()} | {title} {'='*20}"]
        for key, value in data.items():
            log_block.append(f"{key}: {value}")
        log_block.append('-' * 60)
        logger.info('\n'.join(log_block))

    def fetch_upstox_user_name(self, access_token):
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            response = requests.get("https://api.upstox.com/v2/user/profile", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(data['data']['user_name'])
                return data['data']['user_name']
            else:
                print(f"❌ Error fetching user name: {response.status_code} {response.text}")
                return "Unknown User"
        except Exception as e:
            print(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"

    async def connect(self):
        await self.accept()
        self.keep_running = True
        self.upstox_ws = None
        self.latest_spot_price = None

    async def disconnect(self, close_code):
        self.keep_running = False
        if self.upstox_ws:
            await self.upstox_ws.close()

    async def receive(self, text_data):
        payload = json.loads(text_data)
        instrument_key = payload.get('instrument_key')
        expiry_date = payload.get('expiry_date')
        access_token = payload.get('access_token')
        
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token))

    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token):
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # 1️⃣ Fetch option chain
        option_chain_url = "https://api.upstox.com/v2/option/chain"
        try:
            chain_response = requests.get(option_chain_url, headers=headers, params={
                'instrument_key': instrument_key,
                'expiry_date': expiry_date
            })
            chain_response.raise_for_status()
            option_data = chain_response.json()['data']
        except Exception as e:
            await self.send(text_data=f"❌ Option chain fetch failed: {str(e)}")
            return

        # 2️⃣ Build instrument keys and map
        instrument_keys = []
        instrument_type_map = {}

        # Option strikes
        for item in option_data:
            if 'call_options' in item and item['call_options']:
                ik = item['call_options']['instrument_key']
                instrument_keys.append(ik)
                instrument_type_map[ik] = {'type': 'CE', 'strike': item.get('strike_price')}
            if 'put_options' in item and item['put_options']:
                ik = item['put_options']['instrument_key']
                instrument_keys.append(ik)
                instrument_type_map[ik] = {'type': 'PE', 'strike': item.get('strike_price')}

        # Add spot/index key
        if instrument_key:
            instrument_keys.append(instrument_key)
            instrument_type_map[instrument_key] = {'type': 'SPOT', 'strike': 'NIFTY'}

        if not instrument_keys:
            await self.send(text_data="❌ No instruments found.")
            return

        # 3️⃣ Authenticate WebSocket
        try:
            auth_resp = requests.get(
                "https://api.upstox.com/v3/feed/market-data-feed/authorize",
                headers=headers
            ).json()
            ws_url = auth_resp['data']['authorized_redirect_uri']
        except Exception as e:
            await self.send(text_data=f"❌ WebSocket auth failed: {str(e)}")
            return

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        last_update_time = time.time()

        try:
            async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                self.upstox_ws = ws

                # Subscribe to all instruments (spot + options)
                sub_msg = {
                    "guid": "some-guid",
                    "method": "sub",
                    "data": {
                        "mode": "full",
                        "instrumentKeys": instrument_keys
                    }
                }
                await ws.send(json.dumps(sub_msg).encode("utf-8"))

                while self.keep_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=300)
                        last_update_time = time.time()
                    except asyncio.TimeoutError:
                        if time.time() - last_update_time > 60:
                            await self.send(text_data="ℹ️ No data for 60s. Reconnecting...")
                            break
                        else:
                            await self.send(text_data="ℹ️ No new data in last 30s")
                            continue

                    try:
                        decoded = pb.FeedResponse()
                        decoded.ParseFromString(message)
                        data_dict = MessageToDict(decoded)
                        print(data_dict)

                        feeds = data_dict.get("feeds", {})

                        # Iterate over each instrument feed
                        for ik, details in feeds.items():
                            info = instrument_type_map.get(ik, {})
                            instrument_type = info.get('type', 'UNKNOWN')
                            strike = info.get('strike', '-')

                            full_feed = details.get("fullFeed", {})
                            # Spot/index data
                            index_ff = full_feed.get("indexFF", {})
                            market_ff = full_feed.get("marketFF", {})

                            # Determine LTP, cp, ltt
                            if instrument_type == "SPOT":
                                ltpc = index_ff.get("ltpc", {})
                                ltp = ltpc.get("ltp")
                                cp = ltpc.get("cp")
                                ltt = ltpc.get("ltt")
                                self.latest_spot_price = ltp or self.latest_spot_price
                            else:  # CE / PE
                                ltpc = market_ff.get("ltpc", {})
                                ltp = ltpc.get("ltp")
                                cp = ltpc.get("cp")
                                ltt = ltpc.get("ltt")

                            result = {
                                "instrument_key": ik,
                                "type": instrument_type,
                                "strike": strike,
                                "ltp": ltp,
                                "cp": cp,
                                "ltt": ltt,
                                "spot_price": self.latest_spot_price
                            }

                            await self.send(text_data=json.dumps(result))

                    except Exception as e:
                        await self.send(text_data=f"❌ Decode error: {str(e)}")
                        continue

        except Exception as e:
            await self.send(text_data=f"❌ WebSocket error: {str(e)}")
