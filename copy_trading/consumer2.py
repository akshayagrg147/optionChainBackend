import asyncio
import json
import ssl
import time
import requests
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from google.protobuf.json_format import MessageToDict
from . import MarketDataFeedV3_pb2 as pb
import os
import csv
from django.conf import settings
import time
from datetime import datetime
class LiveOptionData(AsyncWebsocketConsumer): 
    def reset_trade_flags(self):
        self.sell_order_placed = False
        self.locked_ltp = None
        self.previous_ltp = None
    

    def get_instrument_keys_by_trading_symbol(self, file_path, trading_symbol_input):
        print("🔍 Raw input symbol:", trading_symbol_input)

        if not os.path.exists(file_path):
            print("❌ CSV file not found at path:", file_path)
            return "CSV file not found."
        base_symbol = trading_symbol_input.replace(" ", "").upper()
        ce_symbol = base_symbol.replace("PE", "CE") if base_symbol.endswith("PE") else base_symbol
        pe_symbol = base_symbol.replace("CE", "PE") if base_symbol.endswith("CE") else base_symbol

        print("🔍 CE symbol to check:", ce_symbol)
        print("🔍 PE symbol to check:", pe_symbol)

        result = {
        "CE": None,
        "PE": None
            }
        try:
            with open(file_path, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    symbol_in_file = row.get('tradingsymbol', '').replace(" ", "").upper()

                    if symbol_in_file == ce_symbol:
                        result["CE"] = row.get('instrument_key')
                        print("✅ CE Match found:", symbol_in_file)

                    if symbol_in_file == pe_symbol:
                        result["PE"] = row.get('instrument_key')
                        print("✅ PE Match found:", symbol_in_file)

                    if result["CE"] and result["PE"]:
                        break

        except Exception as e:
            print("❌ Error reading CSV:", str(e))
            return "CSV read error."

        if not result["CE"] and not result["PE"]:
            print("❌ No CE or PE match found.")
            return "Instrument key not found for CE or PE."

        return result
 
    async def connect(self):
        await self.accept()
        self.keep_running = True
        self.upstox_ws = None
        self.latest_spot_price = None 
        self.order_placedCE= False
        self.order_placedPE = False
        self.ltp_at_order = None 
        self.locked_ltp = None
        self.sell_order_placed = False
        self.rever_trade = None
        self.toggle = True
        self.buy_token = None

    async def disconnect(self, close_code):
        self.keep_running = False
        if self.upstox_ws:
            await self.upstox_ws.close()

    async def receive(self, text_data):
        payload = json.loads(text_data)

        instrument_key = payload.get('instrument_key')
        expiry_date = payload.get('expiry_date')
        access_token = payload.get('access_token')
        trading_symbol = payload.get('trading_symbol')
        trading_symbol_2 = payload.get('trading_symbol_2')
        target_market_priceCE = payload.get('target_market_price_CE')
        target_market_pricePE = payload.get('target_market_price_PE')
        step = payload.get('step')
        expected_profit_percent = payload.get('profit_percent')
        self.step = step
        self.expected_profit_percent = expected_profit_percent
        
        if not instrument_key or not expiry_date or not access_token or not target_market_priceCE or not target_market_pricePE or not step:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return
        try:
            self.target_market_priceCE = float(target_market_priceCE)  
            self.target_market_pricePE= float(target_market_pricePE)  
        except ValueError:
            await self.send(text_data=json.dumps({'error': 'Invalid target_market_price'}))
            return  
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2))
        asyncio.create_task(self.fetch_spot_price_forever(access_token, instrument_key))

    async def fetch_spot_price_forever(self, access_token, instrument_key):
        headers = {"Authorization": f"Bearer {access_token}"}
        url = "https://api.upstox.com/v2/market-quote/ltp"

        while self.keep_running:
            try:
                response = requests.get(url, headers=headers, params={"symbol": instrument_key})
                if response.status_code == 200:
                    data = response.json()
                    actual_key = list(data['data'].keys())[0]
                    ltp = data['data'][actual_key].get('last_price')
                    self.latest_spot_price = ltp  
            except Exception as e:
                await self.send(text_data=json.dumps({'error': f'Spot fetch error: {str(e)}'}))

            await asyncio.sleep(1)

    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2):
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

        if instrument_key:
            instrument_keys.append(instrument_key)
            instrument_type_map[instrument_key] = {'type': 'SPOT', 'strike': 'NIFTY'}

        if not instrument_keys:
            await self.send(text_data=json.dumps({'error': 'No instruments found.'}))
            return
        
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
        
        file_path = os.path.join(settings.BASE_DIR,'nse.csv')
        a =  trading_symbol
        instrument_token = self.get_instrument_keys_by_trading_symbol(file_path, a)

        ce_token = instrument_token.get("CE")
        ce_reverse_token = instrument_token.get("PE")
        b = trading_symbol_2
        instrument_token_2 = self.get_instrument_keys_by_trading_symbol(file_path, b)
        pe_token = instrument_token_2.get("PE")
        pe_reverse_token = instrument_token_2.get("CE")

        print("🎯 CE Token:", ce_token)
        print("🎯 CE REVERSE Token:", ce_reverse_token)
        
        print("🎯 PE Token:", pe_token)
        print("🎯 Pe REVERSE Token:", pe_reverse_token)
        last_update_time = time.time()

        try:
            async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                self.upstox_ws = ws

                sub_msg = {
                    "guid": "some-guid",
                    "method": "sub",
                    "data": {
                        "mode": "full",
                        "instrumentKeys": [ce_token,instrument_key]
                    }
                }
                await ws.send(json.dumps(sub_msg).encode("utf-8"))

                last_sent_time = None           

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
                        ws_ltp = ltp_info.get("ltp")
                        ltt = ltp_info.get("ltt")
                        

                        if not ws_ltp or not ltt:
                            continue

                        current_ts = int(time.time() * 1000)
                        latency = current_ts - int(ltt)
                        
                        ltt_int = int(ltt)
                        ltt_dt = datetime.fromtimestamp(ltt_int / 1000.0)
                        ltt_str = ltt_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        print(f"🕒 WebSocket LTT (ms): {ltt_int} | Human: {ltt_str} | LTP: {ws_ltp} | Latency: {latency}ms")

                        
                        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        print('TIME', timestamp)
                        
                        current_time = datetime.now()
                        
                        print('🕓 Current Time:', current_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
                        
                        
                        
                        
                        
                        

                        rest_ltp = ws_ltp
                        key_to_symbol = {
                                    ce_token: trading_symbol,
                                    ce_reverse_token: trading_symbol_2,
                                    pe_token: trading_symbol_2,
                                    pe_reverse_token: trading_symbol
                                    }
                        info = instrument_type_map.get(ik)
                        if info:
                            
                            a = self.latest_spot_price            
                            result = {
                                'type': info['type'],
                                'strike': info['strike'],
                                'ltp': rest_ltp,
                                'latency_ms': latency,
                                'spot_price': self.latest_spot_price,  
                                'timestamp': time.strftime('%H:%M:%S')
                            }
                            
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))

                            