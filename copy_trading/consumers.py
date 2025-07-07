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
        self.latest_spot_price = None 
        self.order_placed = False
        self.ltp_at_order = None 
        self.locked_ltp = None
        self.sell_order_placed = False
        

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
        target_market_price = payload.get('target_market_price')
        step = payload.get('step')
        expected_profit_percent = payload.get('profit_percent', 0.5)
        self.step = step
        self.expected_profit_percent = expected_profit_percent

        if not instrument_key or not expiry_date or not access_token or not trading_symbol or not target_market_price or not step:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return

        try:
            self.target_market_price = float(target_market_price)  
        except ValueError:
            await self.send(text_data=json.dumps({'error': 'Invalid target_market_price'}))
            return
      
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token, trading_symbol))
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
                    self.latest_spot_price = ltp  # Save latest spot price

                  
                    # await self.send(text_data=json.dumps({
                    #     'type': 'SPOT',
                    #     'ltp': ltp,
                    #     'timestamp': time.strftime('%H:%M:%S')
                    # }))
            except Exception as e:
                await self.send(text_data=json.dumps({'error': f'Spot fetch error: {str(e)}'}))

            await asyncio.sleep(1)

    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token, trading_symbol):
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
        
        print(instrument_keys)

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
                        "instrumentKeys": [trading_symbol,instrument_key]
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
                        ltp = ltp_info.get("ltp")
                        ltt = ltp_info.get("ltt")

                        if not ltp or not ltt:
                            continue

                        current_ts = int(time.time() * 1000)
                        latency = current_ts - int(ltt)

                        info = instrument_type_map.get(ik)
                        if info:
                            
                            a = self.latest_spot_price
                            print(a)
                            
                            result = {
                                'type': info['type'],
                                'strike': info['strike'],
                                'ltp': ltp,
                                'latency_ms': latency,
                                'spot_price': self.latest_spot_price,  
                                'timestamp': time.strftime('%H:%M:%S')
                            }
                            
                            if not self.order_placed and self.latest_spot_price is not None and info['type'] == 'CE':
                                print(info['type'])
                                try:
                                    if self.target_market_price <= float(self.latest_spot_price):
                                        
                                        print(f'✅ In PlaceOrder Execution Block - Spot: {self.latest_spot_price}, Target: {self.target_market_price}')
                                        self.ltp_at_order = ltp
                                        print(self.ltp_at_order)# ✅ Store only LTP
                                        self.order_placed = True
                                        # order_response = requests.post(
                                        #     "https://your-api-url.com/place-order", 
                                        #     headers={
                                        #         "Authorization": f"Bearer {access_token}",
                                        #         "Content-Type": "application/json"
                                        #     },
                                        #     json={
                                        #         "symbol": trading_symbol,
                                        #         "order_type": "BUY",
                                        #         "quantity": 1,
                                        #         "price": self.latest_spot_price
                                        #     }
                                        # )
                                        # if order_response.status_code == 200:
                                        #     await self.send(text_data=json.dumps({'success': 'Order placed'}))
                                        # else:
                                        #     await self.send(text_data=json.dumps({'error': f'Order failed: {order_response.text}'}))
                                        # self.order_placed = True
                                        
                                        await self.send(text_data=json.dumps({
                                        'message': 'Order placed successfully...Waiting for square off',
                                        'market_value':self.latest_spot_price,
                                        'ltp': self.ltp_at_order,           
                                        'timestamp': time.strftime('%H:%M:%S')

        }))
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                                    
                                                                          
                            if not self.order_placed and self.latest_spot_price is not None and info['type'] == 'PE':
                                print(info['type'])
                                try:
                                    if self.target_market_price >= float(self.latest_spot_price):
                                        
                                        print(f'✅ In PlaceOrder Execution Block - Spot: {self.latest_spot_price}, Target: {self.target_market_price}')
                                        self.ltp_at_order = ltp  
                                        self.order_placed = True
                                        # order_response = requests.post(
                                        #     "https://your-api-url.com/place-order", 
                                        #     headers={
                                        #         "Authorization": f"Bearer {access_token}",
                                        #         "Content-Type": "application/json"
                                        #     },
                                        #     json={
                                        #         "symbol": trading_symbol,
                                        #         "order_type": "BUY",
                                        #         "quantity": 1,
                                        #         "price": self.latest_spot_price
                                        #     }
                                        # )
                                        # if order_response.status_code == 200:
                                        #     await self.send(text_data=json.dumps({'success': 'Order placed'}))
                                        # else:
                                        #     await self.send(text_data=json.dumps({'error': f'Order failed: {order_response.text}'}))
                                        # self.order_placed = True
                                        
                                        await self.send(text_data=json.dumps({
                                        'message': 'Order placed successfully....Waiting for square off',
                                        'market_value':self.latest_spot_price,
                                        'ltp': self.ltp_at_order,          
                                        'timestamp': time.strftime('%H:%M:%S')

                                            }))
                            
                                        
                                        
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                            
                            
                            if self.order_placed and not self.sell_order_placed and self.ltp_at_order is not None:
                                try:
                                    current_ltp = float(ltp)

       
                                    if self.locked_ltp is None:
                                        self.step_size = round(float(self.ltp_at_order) * self.step / 100, 2)
                                        self.locked_lTP = round(float(self.ltp_at_order) - self.step_size, 2)
                                        self.previous_ltp = float(self.ltp_at_order)
                                    
                                        await self.send(text_data=json.dumps({
                                            'init_SL': True,
                                            'locked_LTP': self.locked_lTP,
                                            'step_size': self.step_size
                                                }))

      
                                    if current_ltp > self.previous_ltp:
                                        while current_ltp >= self.locked_lTP + self.step_size:
                                            self.locked_lTP = round(self.locked_lTP + self.step_size, 2)
                                        if self.locked_lTP == self.ltp_at_order:
                                            self.locked_lTP = round(self.locked_lTP - self.step_size, 2)

       
                                    pnl_percent = round(((current_ltp - float(self.ltp_at_order)) / float(self.ltp_at_order)) * 100, 2)

   
                                    if pnl_percent < 0 and current_ltp <= self.locked_lTP:
                                        self.sell_order_placed = True
                                        print('In selling Block ')
                                        await self.send(text_data=json.dumps({
                                            'message': 'SL HIT in LOSS. In selling block ',
                                            'ltp': current_ltp,
                                            'locked_LTP': self.locked_LTP
                                            }))
                                
                                    elif pnl_percent >= 0 and current_ltp < self.previous_ltp and current_ltp <= self.locked_lTP:
                                        print('in selling block ')
                                        await self.send(text_data=json.dumps({
                                                'message': 'In selling block ',
                                                'ltp': current_ltp,
                                                'locked_LTP': self.locked_lTP
                                                                                        }))
                                        if pnl_percent < self.expected_profit_percent:
                                            await self.send(text_data=json.dumps({
                                                        'info': 'Profit less than expected. Consider reverse trade.'
                                                                }))
                                    

                                    self.previous_ltp = current_ltp

                                except Exception as e:
                                        await self.send(text_data=json.dumps({'error': f'Trailing SL error: {str(e)}'}))
                            
      
                            await self.send(text_data=json.dumps(result))

                            now = time.time()
                            if last_sent_time:
                                time_diff = now - last_sent_time
                                print(f"⏱️ Time since last data sent: {time_diff * 1000:.2f} ms")
                            last_sent_time = now

        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
