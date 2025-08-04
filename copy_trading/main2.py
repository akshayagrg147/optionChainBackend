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


from .setup_log import log_order_event




class LiveOptionDataConsumer(AsyncWebsocketConsumer): 
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
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.get("https://api.upstox.com/v2/user/profile", headers=headers)
            if response.status_code == 200:
                data = response.json()
                
                return data['data']['user_name']
            else:
                print(f"❌ Error fetching user name: {response.status_code} {response.text}")
                return "Unknown User"
        except Exception as e:
            print(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"
            
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
        quantity = payload.get('quantity')
        step = payload.get('step')
        expected_profit_percent = payload.get('profit_percent')
        self.step = step
        self.expected_profit_percent = expected_profit_percent
        
        if not instrument_key or not expiry_date or not access_token or not target_market_priceCE or not target_market_pricePE or not step or not quantity:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return
        try:
            self.target_market_priceCE = float(target_market_priceCE)  
            self.target_market_pricePE= float(target_market_pricePE)  
        except ValueError:
            await self.send(text_data=json.dumps({'error': 'Invalid target_market_price'}))
            return  
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2,quantity))
      



    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2,quantity):
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
                        "instrumentKeys": [ce_token,pe_token,ce_reverse_token,pe_reverse_token,instrument_key]
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
                    
                    try:
                        if 'feeds' in data_dict:
                            feed_data = data_dict['feeds'].get(instrument_key)

                            if feed_data:
                                try:
                                    ltp_data = feed_data['fullFeed']

                                    if 'indexFF' in ltp_data:
                                        spot = ltp_data['indexFF']['ltpc']['ltp']
                                        print(spot)
                                except Exception as e:
                                    print(f"❌ Error fetching LTP for {instrument_key}: {e}")
                
                    except Exception as e:
                        print(f"Error while extracting LTP: {e}")

                    feeds = data_dict.get("feeds", {})
                    for ik, details in feeds.items():
                        market_data = details.get("fullFeed", {}).get("marketFF", {})
                        ltp_info = market_data.get("ltpc", {})
                        ws_ltp = ltp_info.get("ltp")
                        ltt = ltp_info.get("ltt")
                        

                        if not ws_ltp or not ltt:
                            continue   
                        ltt_int = int(ltt)
                        current_ts = int(time.time() * 1000)
                        latency = current_ts - ltt_int
                        ltt_dt = datetime.fromtimestamp(ltt_int / 1000.0)
                        ltt_str = ltt_dt.strftime("%H:%M:%S.%f")[:-3]
            
                        
                        current_dt = datetime.fromtimestamp(current_ts / 1000.0)
                       
                        
                        current_str = current_dt.strftime("%H:%M:%S.%f")[:-3]
                        
    
                        rest_ltp = ws_ltp
                       
                        info = instrument_type_map.get(ik)
                        if info:
                            
                                        
                            result = {
                                'type': info['type'],
                                'strike': info['strike'],
                                'ltp': rest_ltp,
                                'latency_ms': latency,
                                'spot_price': spot,  
                                'timestamp': time.strftime('%H:%M:%S')
                            }
                            
                            
                            self.account_name = self.fetch_upstox_user_name(access_token)
                            
                            
                            at = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzWUNRM0MiLCJqdGkiOiI2ODg4ODZiOWU1ZTA0MTc3MmMxZmFmYmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzUzNzc3ODQ5LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NTYzMzIwMDB9.Ddyu7Hy5zgwRSxT0YN9h_rEPohKQ1eQr8IFUNdH1JJs"
                            
                            if ik == ce_token and not self.order_placedCE and spot is not None:   
                                try:
    
                                    if self.target_market_priceCE <= float(spot):
                                     
                                        
                                       
                                        print(f'✅ In PlaceOrder Execution Block CE condition : {spot}, Target: {self.target_market_priceCE}')

                                        #self.ltp_at_order = rest_ltp
                                        
                                        self.buy_token = ce_token
                                        self.reverse_token = ce_reverse_token
                                        print('BUY TOKEN ',ce_token)
                                        order_data = {
                                                    "quantity": quantity,
                                                    "instrument_token": self.buy_token,
                                                    "product": "I",
                                                    "validity": "DAY",
                                                    "price": 0,
                                                    "tag": "BackendInitiatedOrder",
                                                    "order_type": "MARKET",
                                                    "transaction_type": "BUY",
                                                    "disclosed_quantity": 0,
                                                    "trigger_price": 0,
                                                    "is_amo": False,
                                                    "slice": True
                                                }

                                        url = "https://api-sandbox.upstox.com/v3/order/place"
                                        headers = {
                                            'Content-Type': 'application/json',
                                            'Authorization': f'Bearer {at}'
                                        }
                                        
                                        order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                        try:
                                            response = requests.post(url, headers=headers, data=json.dumps(order_data))
                                            order_response = response.json()
                                            print(order_response)
                                            
                                            #buy_order_successful = True
                                            if order_response.get("status") == "success":
                                                order_id = order_response["data"]["order_ids"][0]
                                                
                                                
                                                details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"

                                                detail_headers = {
                                                    'Accept': 'application/json',
                                                    'Authorization': f'Bearer {at}'
                                                }

                                                detail_resp = requests.get(details_url, headers=detail_headers)
                                                detail_data = detail_resp.json()
                                            

                                                if detail_data.get("status") == "success":
                                                    price = detail_data["data"].get("price")
                                                    
                                                    
                                                #########################################
                                                url = "https://api.upstox.com/v3/market-quote/ltp"
                                                headers = {
                                                    'Accept': 'application/json',
                                                    'Authorization': f'Bearer {access_token}'
                                                }
                                                
                                                params = {
                                                            'instrument_key': self.buy_token
                                                        }

                                                
                                                try:
                                                    response = requests.get(url, headers=headers,params=params)
                                                    response.raise_for_status()  # Raise exception for HTTP error codes

                                                    data = response.json()
                                                    # Assuming structure: {"status":"success", "data": {"instrument_key": {"last_price": 123.45}}}

                                                    if data.get("status") == "success":
                                                        ltp_data = data.get("data", {})
                                                        for instrument, quote in ltp_data.items():
                                                            last_price = quote.get("last_price")
                                                            self.ltp_at_order = last_price
                                                            print(f"✅ Instrument: {instrument}, Last Price: {last_price}")
                                                    else:
                                                        print("❌ API responded with error status:", data)

                                                except requests.exceptions.RequestException as e:
                                                    print(f"❌ Request failed: {str(e)}")

                                                except ValueError as e:
                                                    print(f"❌ JSON decode error: {str(e)}")

                                                except Exception as e:
                                                    print(f"❌ Unexpected error: {str(e)}")
                                                
                                                
                                                
                                                   
                                                    
                                                self.order_placedCE  = True
                                                self.order_placedPE  = True
                                                
                                        except requests.exceptions.RequestException as e:
                                            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
                                               
                                        try:
                                            await self.send(text_data=json.dumps({
                                                    'message': 'Order placed successfully...Waiting for square off',
                                                    'Account_name': self.account_name,
                                                    'Token_BUy': self.buy_token,
                                                    'market_value': spot,
                                                    'ltp': self.ltp_at_order,
                                                    'order_datetime': order_timestamp
                                                }))
                                            
                                            log_order_event(
                                                            self.account_name,
                                                            "Buy Order Placed",
                                                            {
                                                                'Token_BUy': self.buy_token,
                                                                'Market Value': spot,
                                                                'LTP': self.ltp_at_order,
                                                                'Order Time': order_timestamp
                                                            }
                                                        )
                          
                          
                                        except Exception as e:
                                            print(f"❌ Exception while sending message to frontend: {e}")
  
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                                                                                          
                            if not self.order_placedPE and spot is not None:
                                try:
                                    
                                    if self.target_market_pricePE >= float(spot):
                                        if ik == pe_token:
                                        
                                            print(f'✅ In PlaceOrder Execution Block PE: SPOT: {spot}, Target: {self.target_market_pricePE}')
                                            #self.ltp_at_order = rest_ltp 
                                            
                                            #print('live ltp at purchase',self.ltp_at_order) 
                                            #self.order_placedPE  = True
                                            #self.order_placedCE  = True
                                            self.buy_token = pe_token
                                            self.reverse_token = pe_reverse_token
                                            print('BUY TOKEN ',pe_token)
                                            order_data = {
                                                    "quantity": quantity,
                                                    "instrument_token": self.buy_token,
                                                    "product": "I",
                                                    "validity": "DAY",
                                                    "price": 0,
                                                    "tag": "BackendInitiatedOrder",
                                                    "order_type": "MARKET",
                                                    "transaction_type": "BUY",
                                                    "disclosed_quantity": 0,
                                                    "trigger_price": 0,
                                                    "is_amo": False,
                                                    "slice": True
                                                }

                                       
                                        
                                        url = "https://api-sandbox.upstox.com/v3/order/place"
                                        headers = {
                                            'Content-Type': 'application/json',
                                            'Authorization': f'Bearer {at}'
                                        }
                                        
                                        order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                     
                                        try:
                                            response = requests.post(url, headers=headers, data=json.dumps(order_data))
                                            order_response = response.json()
                                            print('order',order_response)
                                            
                                        
                                            if order_response.get("status") == "success":
                                                order_id = order_response["data"]["order_ids"][0]
                                                
                                                
                                                details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"

                                                detail_headers = {
                                                    'Accept': 'application/json',
                                                    'Authorization': f'Bearer {at}'
                                                }

                                                detail_resp = requests.get(details_url, headers=detail_headers)
                                                detail_data = detail_resp.json()
                                                print(detail_data)
                                            

                                                if detail_data.get("status") == "success":
                                                    price = detail_data["data"].get("price")
                                                    self.ltp_at_order = 3800
                                                    
                                                self.order_placedCE  = True
                                                self.order_placedPE  = True
                                              
                                
                                            
                                        except requests.exceptions.RequestException as e:
                                            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
                      
                                            try:
                                                await self.send(text_data=json.dumps({
                                                    'message': 'Order placed successfully...Waiting for square off',
                                                    'Account_name': self.account_name,
                                                    'Token_BUy': self.buy_token,
                                                    'market_value': spot,
                                                    'ltp': self.ltp_at_order,
                                                    'order_datetime': order_timestamp
                                                }))
                                                
                                                log_order_event(
                                                            self.account_name,
                                                            "Buy Order Placed",
                                                            {
                                                                'Token_BUy': self.buy_token,
                                                                'Market Value': spot,
                                                                'LTP': self.ltp_at_order,
                                                                'Order Time': order_timestamp
                                                            }
                                                        )
                                                                                                        
                            
                                            except Exception as e:
                                                print(f"❌ Exception while sending message to frontend: {e}")
                                                                                
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                            
                       
                            if (self.order_placedPE or self.order_placedCE) and not self.sell_order_placed and self.ltp_at_order is not None and ik == self.buy_token:
                                try:
                                              
                                    current_ltp = float(rest_ltp)

                                    if self.locked_ltp is None:
                                        self.step_size = round(float(self.ltp_at_order) * self.step / 100, 2) # gap 
                                        print(self.step_size)
                                        self.locked_ltp = round(float(self.ltp_at_order) - self.step_size, 2) # 150 - 0.75
                                        print(self.locked_ltp)
                                        self.previous_ltp = float(self.ltp_at_order)
                                        print(self.previous_ltp)
                                        await self.send(text_data=json.dumps({
                                            'init_SL': True,    
                                            'locked_LTP': self.locked_ltp,
                                            'step_size': self.step_size
                                                }))   
                                    print(f"📈 Buy: {self.ltp_at_order} | Locked SL: {self.locked_ltp} | Live LTP: {current_ltp}")
                                    if current_ltp > self.previous_ltp:
                                        while current_ltp >= self.locked_ltp + self.step_size:
                                            self.locked_ltp = round(self.locked_ltp + self.step_size, 2)
                                            
                                        if self.locked_ltp == self.ltp_at_order:
                                            self.locked_ltp = round(self.locked_ltp - self.step_size, 2)
                                            
                                    pnl_percent = round(((current_ltp - float(self.ltp_at_order)) / float(self.ltp_at_order)) * 100, 2)
                                    print(f"📈 Buy: {self.ltp_at_order} | Locked SL: {self.locked_ltp} | Live LTP: {current_ltp} | P&L: {pnl_percent}%")

                                    if (current_ltp <= self.locked_ltp and current_ltp < self.previous_ltp) or (current_ltp < self.locked_ltp) :
                                        self.sell_order_placed = True
                                        print(f'Selling the token : {self.buy_token}') 
                                        order_data = {
                                                    "quantity": quantity,
                                                    "instrument_token": self.buy_token,
                                                    "product": "I",
                                                    "validity": "DAY",
                                                    "price": 0,
                                                    "tag": "BackendInitiatedOrder",
                                                    "order_type": "MARKET",
                                                    "transaction_type": "SELL",
                                                    "disclosed_quantity": 0,
                                                    "trigger_price": 0,
                                                    "is_amo": False,
                                                    "slice": True
                                                }

                                        url = "https://api-sandbox.upstox.com/v3/order/place"
                                        headers = {
                                            'Content-Type': 'application/json',
                                            'Authorization': f'Bearer {access_token}'
                                        }
                                        
                                        order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                        try:
                                            response = requests.post(url, headers=headers, data=json.dumps(order_data))
                                            order_response = response.json()
                                            
                                        
                                            if order_response.get("status") == "success":
                                                order_id = order_response["data"]["order_ids"][0]
                                                
                                                
                                                details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"

                                                detail_headers = {
                                                    'Accept': 'application/json',
                                                    'Authorization': f'Bearer {access_token}'
                                                }

                                                detail_resp = requests.get(details_url, headers=detail_headers)
                                                detail_data = detail_resp.json()
                                            

                                                if detail_data.get("status") == "success":
                                                    price = detail_data["data"].get("price")
                                                    self.ltp_at_order = price
                                                

                                        except requests.exceptions.RequestException as e:
                                            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
                                               
                                        await self.send(text_data=json.dumps({
                                            'message': 'Token sell',
                                            'Token_SELL':self.buy_token ,
                                            'market_value':spot,
                                            'ltp': self.ltp_at_order,           
                                            'order_datetime': order_timestamp,
                                            'pnl_percent' : pnl_percent }))
                                        
                                        
                                        
                                        log_order_event(
                                                self.account_name,
                                                "Sell Order Executed",
                                                {
                                                    'Token_SELL': self.buy_token,
                                                    'Market Value': spot,
                                                    'LTP': self.ltp_at_order,
                                                    'Order Time': order_timestamp,
                                                    'PNL %': pnl_percent
                                                }
                                            )
                                        
                       
                                        if self.toggle and pnl_percent < self.expected_profit_percent: 
                                            self.previous_ltp = None
                                            self.ltp_at_order = None
                                            self.locked_ltp = None
                                            self.step_size = None
                                            self.buy_token = self.reverse_token
                                        
                                            print("Executing reverse trade with token:", self.reverse_token)
                                        
                                            order_data = {
                                                    "quantity": quantity,
                                                    "instrument_token": self.buy_token,
                                                    "product": "I",
                                                    "validity": "DAY",
                                                    "price": 0,
                                                    "tag": "BackendInitiatedOrder",
                                                    "order_type": "MARKET",
                                                    "transaction_type": "BUY",
                                                    "disclosed_quantity": 0,
                                                    "trigger_price": 0,
                                                    "is_amo": False,
                                                    "slice": True
                                                }

                                            url = "https://api-sandbox.upstox.com/v3/order/place"
                                            headers = {
                                                'Content-Type': 'application/json',
                                                'Authorization': f'Bearer {access_token}'
                                            }
                                            
                                            order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                            try:
                                                response = requests.post(url, headers=headers, data=json.dumps(order_data))
                                                order_response = response.json()
                                                
                                               
                                                if order_response.get("status") == "success":
                                                    order_id = order_response["data"]["order_ids"][0]
                                                    
                                                    
                                                    details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"

                                                    detail_headers = {
                                                        'Accept': 'application/json',
                                                        'Authorization': f'Bearer {access_token}'
                                                    }

                                                    detail_resp = requests.get(details_url, headers=detail_headers)
                                                    detail_data = detail_resp.json()
                                                

                                                    if detail_data.get("status") == "success":
                                                        price = detail_data["data"].get("price")
                                                        self.ltp_at_order = price
                                                    

                                            except requests.exceptions.RequestException as e:
                                                await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
                                                
                                            await self.send(text_data=json.dumps({
                                                'message': ' Reverse token ...Order placed successfully...Waiting for square off',
                                                'Token_BUy':self.buy_token ,
                                                'market_value':spot,
                                                'ltp': self.ltp_at_order,           
                                                'order_datetime': order_timestamp}))
                                            
                                            log_order_event(
                                                    self.account_name,
                                                    "Reverse Buy Order",
                                                    {
                                                        'Token_Buy': self.buy_token,
                                                        'Market Value': spot,
                                                        'LTP': self.ltp_at_order,
                                                        'Order Time': order_timestamp
                                                    }
                                                )
                                            
                                            
                                            
                                        
        
                                            self.toggle = False 
                                    self.previous_ltp = current_ltp
                                except Exception as e:
                                        await self.send(text_data=json.dumps({'error': f'Trailing SL error: {str(e)}'}))
            
                            await self.send(text_data=json.dumps(result))
                            now = time.time()
                            if last_sent_time:
                                time_diff = now - last_sent_time
                                
                            last_sent_time = now

        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))
