import asyncio
import json
import ssl
import time
import requests
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from google.protobuf.json_format import MessageToDict
from datetime import datetime
import pytz
from . import MarketDataFeedV3_pb2 as pb


class LiveOptionDataConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keep_running = True
        self.upstox_ws = None
        self.latest_spot_price = None
        self.market_value = None 
        self.trade_executed = False
        self.access_token = None 

    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        self.keep_running = False
        if self.upstox_ws:
            await self.upstox_ws.close()

    async def receive(self, text_data):
        try:
            print(f"Raw WebSocket message: {text_data}")
            text_data = text_data.strip()
            payload = json.loads(text_data)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {str(e)}")
            await self.send(text_data=json.dumps({'error': f'Invalid JSON payload: {str(e)}'}))
            return

      
        instrument_key = payload.get('instrument_key')
        expiry_date = payload.get('expiry_date')
        access_token = payload.get('access_token')
        trading_symbol = payload.get('trading_symbol')
        self.market_value = payload.get('market_value')  
        self.access_token = access_token  

        if not all([instrument_key, expiry_date, access_token, trading_symbol, self.market_value]):
            await self.send(text_data=json.dumps({'error': 'Missing required fields (instrument_key, expiry_date, access_token, trading_symbol, market_value)'}))
            return

        market_instrument_key = instrument_key.replace('NSE_INDEX|Nifty 50', 'NSE_INDEX:Nifty 50')
        print(f"Using instrument_key: {instrument_key} for option chain, {market_instrument_key} for market quote and WebSocket")

        asyncio.create_task(
            self.fetch_and_stream_data(instrument_key, market_instrument_key, expiry_date, access_token, trading_symbol)
        )

    async def fetch_initial_spot_price(self, market_instrument_key, headers, max_retries=3, retry_delay=5):
        quote_url = "https://api.upstox.com/v2/market-quote/quotes"
        params = {'instrument_key': market_instrument_key}
        for attempt in range(max_retries):
            try:
                quote_response = requests.get(quote_url, headers=headers, params=params)
                quote_response.raise_for_status()
                quote_data = quote_response.json()
                print(f"Market quote API response: {json.dumps(quote_data, indent=2)}")
                if quote_data.get('status') == 'success' and market_instrument_key in quote_data.get('data', {}):
                    self.latest_spot_price = quote_data['data'][market_instrument_key]['last_price']
                    print(f"Initial spot price for {market_instrument_key}: {self.latest_spot_price}")
                    return True
                else:
                    print(f"No quote data for {market_instrument_key} in attempt {attempt + 1}")
            except Exception as e:
                print(f"Initial spot price fetch failed for {market_instrument_key}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
        await self.send(text_data=json.dumps({'warning': f'Failed to fetch initial spot price for {market_instrument_key} after {max_retries} attempts'}))
        return False

    async def place_trade(self, trading_symbol, option_type):
        """Place a trade using Upstox trade API (not called, kept for reference)."""
        trade_url = "https://api.upstox.com/v2/order/place"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
       
        payload = {
            "instrument_key": trading_symbol,
            "quantity": 1,
            "order_type": "MARKET",
            "product": "I", 
            "transaction_type": "BUY",
            "validity": "DAY",
            "price": 0, 
            "trigger_price": 0,
            "disclosed_quantity": 0,
            "is_amo": False
        }
        try:
            response = requests.post(trade_url, headers=headers, json=payload)
            response.raise_for_status()
            trade_data = response.json()
            print(f"Trade placed successfully for {option_type}: {json.dumps(trade_data, indent=2)}")
            await self.send(text_data=json.dumps({
                'info': f'Trade placed successfully for {option_type}',
                'trade_data': trade_data
            }))
            return True
        except Exception as e:
            print(f"Trade placement failed for {option_type}: {str(e)}")
            await self.send(text_data=json.dumps({
                'error': f'Trade placement failed for {option_type}: {str(e)}'
            }))
            return False

    async def fetch_and_stream_data(self, instrument_key, market_instrument_key, expiry_date, access_token, trading_symbol):
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        
        option_chain_url = "https://api.upstox.com/v2/option/chain"
        params = {
            'instrument_key': instrument_key,
            'expiry_date': expiry_date
        }
        try:
            chain_response = requests.get(option_chain_url, headers=headers, params=params)
            chain_response.raise_for_status()
            option_data = chain_response.json()['data']
            print(f"Option chain response: {json.dumps(option_data, indent=2)}")
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'Option chain fetch failed: {str(e)}'}))
            return

       
        instrument_type_map = {market_instrument_key: {'type': 'SPOT', 'strike': None}}
        for item in option_data:
            if 'call_options' in item and item['call_options'] and item['call_options']['instrument_key'] == trading_symbol:
                instrument_type_map[trading_symbol] = {'type': 'CE', 'strike': item.get('strike_price')}
                self.latest_spot_price = item.get('underlying_spot_price')
                print(f"Initial spot price from option chain for {instrument_key}: {self.latest_spot_price}")
                break
            if 'put_options' in item and item['put_options'] and item['put_options']['instrument_key'] == trading_symbol:
                instrument_type_map[trading_symbol] = {'type': 'PE', 'strike': item.get('strike_price')}
                self.latest_spot_price = item.get('underlying_spot_price')
                print(f"Initial spot price from option chain for {instrument_key}: {self.latest_spot_price}")
                break

        if trading_symbol not in instrument_type_map:
            await self.send(text_data=json.dumps({'error': f'Trading symbol {trading_symbol} not found in option chain'}))
            return

        if self.latest_spot_price is None:
            await self.fetch_initial_spot_price(market_instrument_key, headers)

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
                sub_msg = {
                    "guid": "some-guid",
                    "method": "sub",
                    "data": {
                        "mode": "full",
                        "instrumentKeys": [trading_symbol, market_instrument_key]
                    }
                }
                await ws.send(json.dumps(sub_msg).encode("utf-8"))
                print(f"Subscribed to: {trading_symbol}, {market_instrument_key}")

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
                        print(f"Received WebSocket message for instruments: {list(data_dict.get('feeds', {}).keys())}")
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
                            if info['type'] == 'SPOT':
                                self.latest_spot_price = ltp
                                print(f"Updated spot price for {ik}: {ltp}")

                              
                                if not self.trade_executed and self.latest_spot_price is not None and self.market_value is not None:
                                    option_type = instrument_type_map.get(trading_symbol, {}).get('type')
                                    if option_type in ['CE', 'PE']:
                                        if option_type == 'CE' and self.market_value >= self.latest_spot_price:
                                            print(f"Condition met: market_value ({self.market_value}) >= spot_price ({self.latest_spot_price}). Trade completed for CE.")
                                            print("Trade completed")
                                            self.trade_executed = True 
                                        elif option_type == 'PE' and self.market_value <= self.latest_spot_price:
                                            print(f"Condition met: market_value ({self.market_value}) <= spot_price ({self.latest_spot_price}). Trade completed for PE.")
                                            print("Trade completed")
                                            self.trade_executed = True 
                            elif info['type'] in ['CE', 'PE']:
                                result = {
                                    'type': info['type'],
                                    'strike': info['strike'],
                                    'ltp': ltp,
                                    'spot_price': self.latest_spot_price,
                                    'latency_ms': latency,
                                    'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')
                                }
                                await self.send(text_data=json.dumps(result))

                                now = time.time()
                                if last_sent_time:
                                    time_diff = now - last_sent_time
                                    print(f"⏱️ Time since last data sent: {time_diff * 1000:.2f} ms")
                                last_sent_time = now

        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))