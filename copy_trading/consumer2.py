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
from .setup_log import log_order_event, logger

class LiveOptionDataConsumer2(AsyncWebsocketConsumer):
    def __init__(self):
        super().__init__()
        self.reset_trade_flags()
        
    def reset_trade_flags(self):
        self.sell_order_placed = False
        self.locked_ltp = None
        self.previous_ltp = None
        self.last_spot_write = 0
        self.spot_latency = 0
        self.option_latency = 0
        
    def log_order_event(self, account_name: str, title: str, data: dict):
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
                print(data['data']['user_name'])
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
        self.order_placedCE = False
        self.order_placedPE = False
        self.ltp_at_order = None 
        self.locked_ltp = None
        self.sell_order_placed = False
        self.rever_trade = None
        self.toggle = True
        self.buy_token = None
        self.buy_quantity = None
        self.buy_in_ltp = None
        self.sell_in_ltp = None
        self.new_invest_amount = None

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
        quantityCE = payload.get('quantityCE')
        quantityPE = payload.get('quantityPE')
        step = payload.get('step')
        expected_profit_percent = payload.get('profit_percent')
        self.step = step
        self.expected_profit_percent = expected_profit_percent
        total_amount = payload.get("total_amount")
        investable_amount = payload.get("investable_amount") 
        lot = payload.get("lot")
        reverse_Trade = payload.get("reverseTrade")
        
        if not instrument_key or not expiry_date or not access_token or not target_market_priceCE or not target_market_pricePE or not step or not quantityCE or not quantityPE or not total_amount or not investable_amount or not lot or not reverse_Trade:
            await self.send(text_data=json.dumps({'error': 'Missing required fields'}))
            return
        
        try:
            self.target_market_priceCE = float(target_market_priceCE)  
            self.target_market_pricePE = float(target_market_pricePE)  
        except ValueError:
            await self.send(text_data=json.dumps({'error': 'Invalid target_market_price'}))
            return  
        
        asyncio.create_task(self.fetch_and_stream_data(instrument_key, expiry_date, access_token, trading_symbol, trading_symbol_2, quantityCE, quantityPE, total_amount, investable_amount, lot, reverse_Trade))

    async def process_spot_price(self, data_dict, instrument_key):
        """Fast spot price extraction with minimal processing"""
        try:
            if 'feeds' in data_dict:
                feed_data = data_dict['feeds'].get(instrument_key)
                if feed_data and 'fullFeed' in feed_data:
                    ltp_data = feed_data['fullFeed']
                    if 'indexFF' in ltp_data:
                        self.latest_spot_price = ltp_data['indexFF']['ltpc']['ltp']
                        return True
        except Exception as e:
            print(f"❌ Spot price error: {e}")
        return False

    async def measure_latency(self, data_dict, instrument_key):
        """Measure latency for different instrument types"""
        if 'feeds' not in data_dict:
            return
        
        for ik, details in data_dict['feeds'].items():
            market_data = details.get("fullFeed", {}).get("marketFF", {})
            ltp_info = market_data.get("ltpc", {})
            ltt = ltp_info.get("ltt")
            
            if ltt:
                current_ts = int(time.time() * 1000)
                latency = current_ts - int(ltt)
                
                # Track spot vs option latency separately
                if ik == instrument_key:
                    self.spot_latency = latency
                else:
                    self.option_latency = latency
                
                # Log high latency
                if latency > 100:
                    print(f"⚠️ High latency {latency}ms for {ik}")

    async def fetch_and_stream_data(self, instrument_key, expiry_date, access_token, trading_symbol, trading_symbol_2, quantityCE, quantityPE, total_amount, investable_amount, lot, reverse_Trade):
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
        
        file_path = os.path.join(settings.BASE_DIR, 'nse.csv')
        a = trading_symbol
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
        last_spot_time = 0
        spot_update_interval = 0.1  # 100ms

        try:
            async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                self.upstox_ws = ws

                # Subscribe to spot price separately with higher priority
                spot_sub_msg = {
                    "guid": "spot-guid",
                    "method": "sub", 
                    "data": {
                        "mode": "full",
                        "instrumentKeys": [instrument_key]  # Just the spot instrument
                    }
                }
                await ws.send(json.dumps(spot_sub_msg).encode("utf-8"))
                
                # Small delay to prioritize spot data
               
                
                # Then subscribe to options
                option_sub_msg = {
                    "guid": "option-guid", 
                    "method": "sub",
                    "data": {
                        "mode": "full",
                        "instrumentKeys": [ce_token, pe_token, ce_reverse_token, pe_reverse_token]
                    }
                }
                await ws.send(json.dumps(option_sub_msg).encode("utf-8"))

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
                    
                    current_time = time.time()
                    
                    # Process spot price with throttling
                    if current_time - last_spot_time >= spot_update_interval:
                        spot_updated = await self.process_spot_price(data_dict, instrument_key)
                        if spot_updated:
                            last_spot_time = current_time
                    
                    # Measure latency for monitoring
                    await self.measure_latency(data_dict, instrument_key)

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
                        
                        # Optimized file writing - only write significant changes or at intervals
                        spot_file_path = os.path.join(settings.BASE_DIR, 'spot_prices.txt')
                        if current_time - self.last_spot_write > 1.0:  # 1 second interval
                            try:
                                with open(spot_file_path, 'a') as f:
                                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {self.latest_spot_price}\n")
                                self.last_spot_write = current_time
                            except Exception as e:
                                print(f"⚠️ Error writing spot price to file: {e}")

                        rest_ltp = ws_ltp
                       
                        info = instrument_type_map.get(ik)
                        if info:
                            result = {
                                'type': info['type'],
                                'strike': info['strike'],
                                'ltp': rest_ltp,
                                'latency_ms': latency,
                                'spot_price': self.latest_spot_price,
                                'timestamp': time.strftime('%H:%M:%S'),
                                'spot_latency': self.spot_latency,
                                'option_latency': self.option_latency,
                                'instrument_key': ik
                            }
                            
                            # Trading condition monitoring without order placement
                            if ik == ce_token and not self.order_placedCE and self.latest_spot_price is not None:
                                try:
                                    if self.target_market_priceCE <= float(self.latest_spot_price):
                                        print(f'✅ CE Buy Condition Met: {self.latest_spot_price}, Target: {self.target_market_priceCE}')
                                        result['trading_signal'] = 'CE_BUY_CONDITION_MET'
                                        result['signal_type'] = 'CE'
                                        self.order_placedCE = True
                                        self.order_placedPE = True
                                except Exception as e:
                                    print(f'CE condition error: {str(e)}')
                            
                            if ik == pe_token and not self.order_placedPE and self.latest_spot_price is not None:
                                try:
                                    if self.target_market_pricePE >= float(self.latest_spot_price):
                                        print(f'✅ PE Buy Condition Met: {self.latest_spot_price}, Target: {self.target_market_pricePE}')
                                        result['trading_signal'] = 'PE_BUY_CONDITION_MET'
                                        result['signal_type'] = 'PE'
                                        self.order_placedPE = True
                                        self.order_placedCE = True
                                except Exception as e:
                                    print(f'PE condition error: {str(e)}')
                            
                            # Trailing stop loss monitoring
                            if (self.order_placedPE or self.order_placedCE) and not self.sell_order_placed and self.ltp_at_order is not None and ik == self.buy_token:
                                try:
                                    current_ltp = float(rest_ltp)
                                    
                                    if self.locked_ltp is None:
                                        self.step_size = round(float(self.ltp_at_order) * self.step / 100, 2)
                                        self.locked_ltp = round(float(self.ltp_at_order) - self.step_size, 2)
                                        self.previous_ltp = float(self.ltp_at_order)
                                        result['trailing_sl_initialized'] = True
                                        result['locked_ltp'] = self.locked_ltp
                                        result['step_size'] = self.step_size
                                    
                                    pnl_percent = round(((current_ltp - float(self.ltp_at_order)) / float(self.ltp_at_order)) * 100, 2)
                                    result['pnl_percent'] = pnl_percent
                                    result['trailing_sl_level'] = self.locked_ltp
                                    
                                    print(f"📈 Buy: {self.ltp_at_order} | Locked SL: {self.locked_ltp} | Live LTP: {current_ltp} | P&L: {pnl_percent}%")
                                    
                                    if (current_ltp <= self.locked_ltp and current_ltp < self.previous_ltp) or (current_ltp < self.locked_ltp):
                                        print(f'✅ Sell Condition Met for token: {self.buy_token}')
                                        result['trading_signal'] = 'SELL_CONDITION_MET'
                                        result['signal_type'] = 'SELL'
                                        self.sell_order_placed = True
                                    
                                    self.previous_ltp = current_ltp
                                    
                                except Exception as e:
                                    print(f'Trailing SL monitoring error: {str(e)}')
                            
                            await self.send(text_data=json.dumps(result))
                            
                            now = time.time()
                            if last_sent_time:
                                time_diff = now - last_sent_time
                                # Optional: Log if time between messages is too high
                                if time_diff > 0.5:
                                    print(f"⚠️ High message interval: {time_diff:.3f}s")
                            last_sent_time = now

        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'WebSocket error: {str(e)}'}))