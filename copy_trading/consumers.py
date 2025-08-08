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
from .setup_log import log_order_event ,logger
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
        quantity = payload.get('quantity')
        step = payload.get('step')
        expected_profit_percent = payload.get('profit_percent')
        self.step = step
        self.expected_profit_percent = expected_profit_percent
        total_amount = payload.get("total_amount")
        investable_amount = payload.get("investable_amount") 
        lot = payload.get("lot")
        reverse_Trade = payload.get("reverseTrade")
        
        if not instrument_key or not expiry_date or not access_token or not target_market_priceCE or not target_market_pricePE or not step or not quantity or not total_amount or not investable_amount or not lot or not reverse_Trade:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return
        try:
            self.target_market_priceCE = float(target_market_priceCE)  
            self.target_market_pricePE= float(target_market_pricePE)  
        except ValueError:
            await self.send(text_data=json.dumps({'error': 'Invalid target_market_price'}))
            return  
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2,quantity,total_amount,investable_amount,lot,reverse_Trade))
      



    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token, trading_symbol,trading_symbol_2,quantity,total_amount,investable_amounnt,lot,reverse_Trade):
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
                        message = await asyncio.wait_for(ws.recv(), timeout=300)
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
                                        self.latest_spot_price = ltp_data['indexFF']['ltpc']['ltp']
                                    
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
                        #print('socket timing',ltt_str)
                        
                        
                        current_dt = datetime.fromtimestamp(current_ts / 1000.0)
                       
                        
                        current_str = current_dt.strftime("%H:%M:%S.%f")[:-3]
                        
                        #print('current timing',current_str)
                        
                        
                        # print("📡 Upstox sent LTT at: ", ltt_dt.strftime("%H:%M:%S.%f")[:-3])
                        # print("🖥️ My system received at:", current_dt.strftime("%H:%M:%S.%f")[:-3])
                        # print(f"⏱️ Delay from Upstox to me: {latency} ms | LTP: {ws_ltp}")
    

                        
                        log_line = f"WebSocket LTT (ms): {ltt_int} | Human: {ltt_str} | LTP: {ws_ltp} | Latency: {latency}ms | Socket Timing :{ltt_str} | Current Timing :{current_str}\n"
                        #print(log_line.strip()) 
                        
                        with open("websocket_latency_lognew2new.txt", "a") as logfile:
                            logfile.write(log_line)
                        
                        rest_ltp = ws_ltp
                       
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
                            
                            
                            self.account_name = self.fetch_upstox_user_name(access_token)
                            
                            if ik == ce_token and not self.order_placedCE and self.latest_spot_price is not None:   
                                try:
                                    #print("inside ce ")
                                    if self.target_market_priceCE <= float(self.latest_spot_price):
                                        print("inside ce2")
                                        
                                       
                                        print(f'✅ In PlaceOrder Execution Block CE condition : {self.latest_spot_price}, Target: {self.target_market_priceCE}')

                                        self.ltp_at_order = rest_ltp
                                        print(self.ltp_at_order)
                                        self.order_placedCE  = True
                                        self.order_placedPE  = True
                                        self.buy_token = ce_token
                                        self.reverse_token = ce_reverse_token
                                        
                                                
                                                
                                        
                                        
                                        
                                        order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        print('BUY TOKEN ',ce_token)
                                        data = {
                                                        "quantity": quantity,
                                                        "product": "D",
                                                        "validity": "DAY",
                                                        "price": 0,
                                                        "tag": "string",
                                                        "instrument_token": ce_token,
                                                        "order_type": "MARKET",
                                                        "transaction_type": "BUY",
                                                        "disclosed_quantity": 0,
                                                        "trigger_price": 0,
                                                        "is_amo": False  
                                                    }
                                        

                                        print(data)
  
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
                                                    'Account_name': self.account_name,
                                                    'Token_BUy': self.buy_token,
                                                    'market_value': self.latest_spot_price,
                                                    'ltp': self.ltp_at_order,
                                                    'order_datetime': order_timestamp
                                                }))
                                        
                                        
                                        log_order_event(
                                                            self.account_name,
                                                            "Buy Order Placed",
                                                            {
                                                                'Token_BUy': self.buy_token,
                                                                'Market Value': self.latest_spot_price,
                                                                'LTP': self.ltp_at_order,
                                                                "Total Amount" : total_amount,
                                                                "Investable Amount": investable_amounnt,
                                                                'Order Time': order_timestamp
                                                            }
                                                        )
                                        
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                                                                                          
                            if not self.order_placedPE and self.latest_spot_price is not None:
                                #print(info['type'])
                                try:
                                    
                                    if self.target_market_pricePE >= float(self.latest_spot_price):
                                        if ik == pe_token:
                                        
                                            print(f'✅ In PlaceOrder Execution Block PE: SPOT: {self.latest_spot_price}, Target: {self.target_market_pricePE}')
                                            self.ltp_at_order = rest_ltp 
                                            
                                            print('live ltp at purchase',self.ltp_at_order) 
                                            self.order_placedPE  = True
                                            self.order_placedCE  = True
                                            self.buy_token = pe_token
                                            self.reverse_token = pe_reverse_token
                                            
                                                
                                            
                                            order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            print('BUY TOKEN ',pe_token)
                                            data = {
                                                        "quantity": quantity,
                                                        "product": "D",
                                                        "validity": "DAY",
                                                        "price": 0,
                                                        "tag": "string",
                                                        "instrument_token": pe_token,
                                                        "order_type": "MARKET",
                                                        "transaction_type": "BUY",
                                                        "disclosed_quantity": 0,
                                                        "trigger_price": 0,
                                                        "is_amo": False  
                                                    }
                                            print(data)
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
                                                    'Account_name': self.account_name,
                                                    'Token_BUy': self.buy_token,
                                                    'market_value': self.latest_spot_price,
                                                    'ltp': self.ltp_at_order,
                                                    'order_datetime': order_timestamp
                                                }))
                                        
                                        
                                        log_order_event(
                                                            self.account_name,
                                                            "Buy Order Placed",
                                                            {
                                                                'Token_BUy': self.buy_token,
                                                                'Market Value': self.latest_spot_price,
                                                                'LTP': self.ltp_at_order,
                                                                "Total Amount" : total_amount,
                                                                "Investable Amount": investable_amounnt,
                                                                'Order Time': order_timestamp
                                                            }
                                                        )
                                except Exception as e:
                                    await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))
                            
                            
                            if (self.order_placedPE or self.order_placedCE) and not self.sell_order_placed and self.ltp_at_order is not None and ik == self.buy_token:
                                try:
                                              
                                    current_ltp = float(rest_ltp)

                                    if self.locked_ltp is None:
                                        self.step_size = round(float(self.ltp_at_order) * self.step / 100, 2) # gap 
                                        self.locked_ltp = round(float(self.ltp_at_order) - self.step_size, 2) # 150 - 0.75
                                        self.previous_ltp = float(self.ltp_at_order)
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
                                        data = {
                                                        "quantity": quantity,
                                                        "product": "I",
                                                        "validity": "DAY",
                                                        "price": 0,
                                                        "tag": "string",
                                                        "instrument_token": self.buy_token,
                                                        "order_type": "MARKET",
                                                        "transaction_type": "BUY",
                                                        "disclosed_quantity": 0,
                                                        "trigger_price": 0,
                                                        "is_amo": False  
                                                    }
                                        print(data)
                                        ltp_response = requests.get(
                                                        "https://api.upstox.com/v2/market-quote/ltp",
                                                        headers={"Authorization": f"Bearer {access_token}"},
                                                        params={"symbol":self.buy_token}
                                                                                    )
                                        order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        if ltp_response.status_code == 200:
                                            ltp_data = ltp_response.json()
                                            key = list(ltp_data['data'].keys())[0]
                                            rest_ltp = ltp_data['data'][key].get('last_price')
                                        self.ltp_at_order = rest_ltp
                                        
                                        
                                
                                        
                                        await self.send(text_data=json.dumps({
                                            'message': 'Token sell',
                                            'Token_SELL':self.buy_token ,
                                            'market_value':self.latest_spot_price,
                                            'ltp': self.ltp_at_order,           
                                            'order_datetime': order_timestamp,
                                            'pnl_percent' : pnl_percent }))
                                        
                                        
                                        
                                        log_order_event(
                                                self.account_name,
                                                "Sell Order Executed",
                                                {
                                                    'Token_SELL': self.buy_token,
                                                    'Market Value': self.latest_spot_price,
                                                    'LTP': self.ltp_at_order,
                                                    'Order Time': order_timestamp,
                                                    'PNL %': pnl_percent
                                                }
                                            )
                                        
                                        if reverse_Trade == "ON" and pnl_percent < self.expected_profit_percent: 
                                            self.previous_ltp = None
                                            self.ltp_at_order = None
                                            self.locked_ltp = None
                                            self.step_size = None
                                            self.buy_token = self.reverse_token
                                            
                                            if not self.ltp_at_order:
                                            
                                                ltp_response = requests.get(
                                                        "https://api.upstox.com/v2/market-quote/ltp",
                                                        headers={"Authorization": f"Bearer {access_token}"},
                                                        params={"symbol":self.buy_token}
                                                                                    )
                                                if ltp_response.status_code == 200:
                                                    ltp_data = ltp_response.json()
                                                    key = list(ltp_data['data'].keys())[0]
                                                    rest_ltp = ltp_data['data'][key].get('last_price')
                                            self.ltp_at_order = rest_ltp
                                            
                                            print('total_amount',total_amount)
                                            print('innvestable_anouut',investable_amounnt)
                                            if pnl_percent > 0 :
                                                 new_investable = investable_amounnt + (pnl_percent / 100) * investable_amounnt
                                            else:
                                                new_investable = investable_amounnt - (abs(pnl_percent) / 100) * investable_amounnt
                                            
                                            print('new investable',new_investable)
                                            print(self.ltp_at_order)
                                            self.rq = lot * (new_investable // (self.ltp_at_order * lot))
                                            quantity = self.rq
                                            

                                            print("Executing reverse trade with token:", self.reverse_token)
                                        
                                            data = {
                                                        "quantity": quantity,
                                                        "product": "I",
                                                        "validity": "DAY",
                                                        "price": 0,
                                                        "tag": "string",
                                                        "instrument_token": self.reverse_token,
                                                        "order_type": "SELL",
                                                        "transaction_type": "BUY",
                                                        "disclosed_quantity": 0,
                                                        "trigger_price": 0,
                                                        "is_amo": False  
                                                    }
                                            print(data)
                                            
                                            reverse_Trade = "OFF"
                                            
                                            self.toggle = False 
                                            
                                            
                                            order_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            
                                            await self.send(text_data=json.dumps({
                                                'message': ' Reverse token ...Order placed successfully...Waiting for square off',
                                                'Token_BUy':self.buy_token ,
                                                'market_value':self.latest_spot_price,
                                                'ltp': self.ltp_at_order,           
                                                'order_datetime': order_timestamp}))
                                            
                                            log_order_event(
                                                    self.account_name,
                                                    "Reverse Buy Order",
                                                    {
                                                        'Token_Buy': self.buy_token,
                                                        'Market Value': self.latest_spot_price,
                                                        'LTP': self.ltp_at_order,
                                                        'Order Time': order_timestamp
                                                    }
                                                )
    
                                            
                                            self.reset_trade_flags()
                                    
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
