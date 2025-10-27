import os
import json
import asyncio
import csv
import time
import ssl
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
import websockets
import requests
from google.protobuf.json_format import MessageToDict
import logging
from kiteconnect import KiteConnect, KiteTicker
import pandas as pd
import threading
import re
import traceback
import websocket as _websocket_client
from .setup_log import log_order_event, logger

class LiveOptionDataConsumerZerodha(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kite = None
        self.kws = None
        self.loop = None
        self.reset_trade_flags()
        
    def reset_trade_flags(self):
        self.sell_order_placed = False
        self.locked_ltp = None
        self.previous_ltp = None
        self.order_placedCE = False
        self.order_placedPE = False
        self.ltp_at_order = None
        self.reverse_trade = None
        self.toggle = True
        self.buy_token = None
        self.buy_trading_symbol = None  
        self.buy_quantity = None
        self.buy_in_ltp = None
        self.sell_in_ltp = None
        self.new_invest_amount = None
        self.latest_spot_price = None
        self.keep_running = True
        self.nifty_token = None
        self.ce_token = None
        self.pe_token = None
        self.ce_trading_symbol = None 
        self.pe_trading_symbol = None
        self.ce_reverse_token = None
        self.pe_reverse_token = None
        self.ce_reverse_trading_symbol = None
        self.pe_reverse_trading_symbol = None  
        self.index_name = "NIFTY"
        self.instruments_cache = None
        self.account_name = None
        self.step = None
        self.expected_profit_percent = None
        self.target_market_priceCE = None
        self.target_market_pricePE = None
        self.current_subscribed_tokens = [] 
        self.spot_price_only_mode = False  
        self.lot = 75 
        self.reverse_token = None
        self.reverse_trading_symbol = None
        self.spot_price_initialized = False  # NEW: Track if spot price is available
        self.pending_option_ticks = []  # NEW: Buffer for early option ticks
        
    def log_order_event(self, account_name: str, title: str, data: dict):
        log_block = [f"\n{'='*20} {account_name.upper()} | {title} {'='*20}"]
        for key, value in data.items():
            log_block.append(f"{key}: {value}")
        log_block.append('-' * 60)
        logger.info('\n'.join(log_block))
    
    def fetch_zerodha_user_name(self, api_key, access_token):
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            profile = kite.profile()
            return profile.get('user_name', 'Unknown User')
        except Exception as e:
            print(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"
    
    def get_instruments(self):
        if not self.instruments_cache:
            try:
                self.instruments_cache = self.kite.instruments("NFO")
                print(f"✅ Loaded {len(self.instruments_cache)} NFO instruments")
            except Exception as e:
                print(f"❌ Error fetching instruments: {str(e)}")
                return []
        return self.instruments_cache
    
    def get_instrument_details_by_trading_symbol(self, trading_symbol_input, index_name="NIFTY"):
        print("🔍 Raw input symbol:", trading_symbol_input)
        
        if not self.kite:
            print("❌ KiteConnect not initialized")
            return {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
        
        instruments = self.get_instruments()
        if not instruments:
            return {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
        
        clean_symbol = trading_symbol_input.replace(" ", "").upper()
        result = {
            "CE": {"token": None, "trading_symbol": None}, 
            "PE": {"token": None, "trading_symbol": None}
        }
        
        # First, find the exact instrument that was provided
        provided_instrument = None
        for instrument in instruments:
            if instrument['tradingsymbol'].replace(" ", "").upper() == clean_symbol:
                provided_instrument = instrument
                break
        
        if not provided_instrument:
            print(f"❌ No instrument found for: {clean_symbol}")
            return result
        
        # Store the provided instrument in the correct type
        if provided_instrument['instrument_type'] == 'CE':
            result["CE"]["token"] = provided_instrument['instrument_token']
            result["CE"]["trading_symbol"] = provided_instrument['tradingsymbol']
            print(f"✅ Provided CE: {result['CE']['trading_symbol']}, Token: {result['CE']['token']}")
        elif provided_instrument['instrument_type'] == 'PE':
            result["PE"]["token"] = provided_instrument['instrument_token']
            result["PE"]["trading_symbol"] = provided_instrument['tradingsymbol']
            print(f"✅ Provided PE: {result['PE']['trading_symbol']}, Token: {result['PE']['token']}")
        
        # Now find the opposite instrument
        opposite_type = "PE" if provided_instrument['instrument_type'] == "CE" else "CE"
        for instrument in instruments:
            if (instrument['strike'] == provided_instrument['strike'] and
                instrument['expiry'] == provided_instrument['expiry'] and
                instrument['instrument_type'] == opposite_type and
                instrument['name'] == provided_instrument['name']):
                
                if opposite_type == 'CE':
                    result["CE"]["token"] = instrument['instrument_token']
                    result["CE"]["trading_symbol"] = instrument['tradingsymbol']
                    print(f"✅ Found matching CE: {result['CE']['trading_symbol']}, Token: {result['CE']['token']}")
                else:
                    result["PE"]["token"] = instrument['instrument_token']
                    result["PE"]["trading_symbol"] = instrument['tradingsymbol']
                    print(f"✅ Found matching PE: {result['PE']['trading_symbol']}, Token: {result['PE']['token']}")
                break
        
        return result

    async def connect(self):
        await self.accept()
        self.keep_running = True
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()
        print("✅ WebSocket connection established (consumer loop stored)")

    async def disconnect(self, close_code):
        self.keep_running = False
        if self.kws:
            try:
                self.kws.close()
            except Exception as e:
                print("Error closing kws:", e)
        print("🔌 WebSocket connection closed")

    async def receive(self, text_data):
        try:
            payload = json.loads(text_data)
            print("📨 Received message:", payload)

            api_key = payload.get('api_key')
            access_token = payload.get('access_token')
            trading_symbol = payload.get('trading_symbol')
            trading_symbol_2 = payload.get('trading_symbol_2')
            self.index_name = payload.get('index_name', 'NIFTY')
            target_market_priceCE = payload.get('target_market_price_CE')
            target_market_pricePE = payload.get('target_market_price_PE')
            quantityCE = payload.get('quantityCE')
            quantityPE = payload.get('quantityPE')
            step = payload.get('step')
            expected_profit_percent = payload.get('profit_percent')
            total_amount = payload.get("total_amount")
            investable_amount = payload.get("investable_amount") 
            lot = payload.get("lot")
            reverse_Trade = payload.get("reverseTrade")
            
            self.step = float(step) if step else 0.5
            self.expected_profit_percent = float(expected_profit_percent) if expected_profit_percent else 10.0
            self.target_market_priceCE = float(target_market_priceCE) if target_market_priceCE else None
            self.target_market_pricePE = float(target_market_pricePE) if target_market_pricePE else None
            self.quantityCE = int(quantityCE) if quantityCE else 75
            self.quantityPE = int(quantityPE) if quantityPE else 75
            self.total_amount = float(total_amount) if total_amount else 100.0
            self.investable_amount = float(investable_amount) if investable_amount else 40.0
            self.lot = int(lot) if lot else 75
            self.reverse_Trade = reverse_Trade if reverse_Trade else "OFF"

            print(f"📊 Trading Parameters: Lot={self.lot}, Investable Amount={self.investable_amount}")

            if not api_key or not access_token or not trading_symbol:
                await self.send(text_data=json.dumps({'error': 'Missing required fields: api_key, access_token, trading_symbol'}))
                return
                
            if not target_market_priceCE or not target_market_pricePE:
                await self.send(text_data=json.dumps({'error': 'Missing trading parameters'}))
                return

            try:
                self.kite = KiteConnect(api_key=api_key)
                self.kite.set_access_token(access_token)
                print("✅ KiteConnect initialized successfully")
                
                # Fetch user name for logging
                self.account_name = self.fetch_zerodha_user_name(api_key, access_token)
                
            except Exception as e:
                await self.send(text_data=json.dumps({'error': f'KiteConnect initialization failed: {str(e)}'}))
                return

            try:
                profile = self.kite.profile()
                print(f"✅ Authentication successful for user: {profile.get('user_name', 'Unknown')}")
            except Exception as e:
                await self.send(text_data=json.dumps({'error': f'Authentication failed: {str(e)}'}))
                return

            asyncio.create_task(self.fetch_and_stream_data(trading_symbol, trading_symbol_2))
            
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'Error processing message: {str(e)}'}))

    async def update_subscription(self, new_tokens):
        """Update WebSocket subscription to only necessary tokens"""
        if self.kws and self.kws.is_connected():
            try:
                if self.current_subscribed_tokens:
                    self.kws.unsubscribe(self.current_subscribed_tokens)
                
                self.kws.subscribe(new_tokens)
                self.kws.set_mode(self.kws.MODE_FULL, new_tokens)
                self.current_subscribed_tokens = new_tokens
                
                print(f"🔄 Subscription updated: {new_tokens}")
                await self.send(text_data=json.dumps({
                    'info': f'Subscription updated to {len(new_tokens)} tokens',
                    'tokens': new_tokens
                }))
            except Exception as e:
                print(f"❌ Error updating subscription: {str(e)}")

    async def place_zerodha_order(self, transaction_type, trading_symbol, quantity, order_type="MARKET", price=0, exchange=None, product=None, validity=None):
        """Place order using Zerodha KiteConnect API with trading symbol"""
        try:
            if not exchange:
                exchange = self.kite.EXCHANGE_NFO
            
            if not product:
                product = self.kite.PRODUCT_NRML
            if not validity:
                validity = self.kite.VALIDITY_DAY
                
            if order_type.upper() == "MARKET":
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    product=product,
                    validity=validity
                )
            else:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    order_type=self.kite.ORDER_TYPE_LIMIT,
                    price=price,
                    product=product,
                    validity=validity
                )
            
            print(f"✅ Order placed successfully. Order ID: {order_id}")
            return order_id
            
        except Exception as e:
            print(f"❌ Order placement failed: {str(e)}")
            raise e

    async def fetch_order_status(self, order_id):
        try:
            orders = self.kite.orders()
            for order in orders:
                if order['order_id'] == order_id:
                    return order
            return None
        except Exception as e:
            print(f"❌ Error fetching order status: {str(e)}")
            return None

    async def fetch_and_stream_data(self, trading_symbol, trading_symbol_2):
        try:
            nse_instruments = self.kite.instruments("NSE")
            self.nifty_token = None
            
            index_map = {
                "NIFTY": "NIFTY 50",
                "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FIN SERVICE",
                "MIDCPNIFTY": "NIFTY MID SELECT"
            }
            
            index_tradingsymbol = index_map.get(self.index_name, "NIFTY 50")
            
            for inst in nse_instruments:
                if inst['tradingsymbol'] == index_tradingsymbol:
                    self.nifty_token = inst['instrument_token']
                    break

            if not self.nifty_token:
                await self.send(text_data=json.dumps({'error': f'{self.index_name} token not found'}))
                return
            print(f"✅ {self.index_name} token found: {self.nifty_token}")

            # NEW: Fetch initial spot price BEFORE starting WebSocket
            try:
                nifty_quote = self.kite.quote([self.nifty_token])
                if self.nifty_token in nifty_quote:
                    self.latest_spot_price = nifty_quote[self.nifty_token]['last_price']
                    self.spot_price_initialized = True
                    print(f"✅ Initial spot price fetched: {self.latest_spot_price}")
                    
                    # Send initial spot price to client
                    await self.send(text_data=json.dumps({
                        'type': 'SPOT_INITIAL',
                        'instrument_token': self.nifty_token,
                        'ltp': self.latest_spot_price,
                        'spot_price': self.latest_spot_price,
                        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                        'index_name': self.index_name,
                        'message': 'Initial spot price loaded'
                    }))
            except Exception as e:
                print(f"⚠️ Could not fetch initial spot price: {e}")

            ce_details = self.get_instrument_details_by_trading_symbol(trading_symbol, self.index_name)
            
            if trading_symbol_2:
                pe_details = self.get_instrument_details_by_trading_symbol(trading_symbol_2, self.index_name)
            else:
                pe_details = {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
                if ce_details["CE"]["token"]:
                    pe_details["PE"]["token"] = ce_details["PE"]["token"]
                    pe_details["PE"]["trading_symbol"] = ce_details["PE"]["trading_symbol"]
                elif ce_details["PE"]["token"]:
                    pe_details["CE"]["token"] = ce_details["CE"]["token"]
                    pe_details["CE"]["trading_symbol"] = ce_details["CE"]["trading_symbol"]
            
            self.ce_token = ce_details["CE"]["token"]
            self.ce_trading_symbol = ce_details["CE"]["trading_symbol"]
            self.ce_reverse_token = ce_details["PE"]["token"]
            self.ce_reverse_trading_symbol = ce_details["PE"]["trading_symbol"]
            
            self.pe_token = pe_details["PE"]["token"]
            self.pe_trading_symbol = pe_details["PE"]["trading_symbol"]
            self.pe_reverse_token = pe_details["CE"]["token"]
            self.pe_reverse_trading_symbol = pe_details["CE"]["trading_symbol"]

            print("🎯 CE Token:", self.ce_token, "CE Trading Symbol:", self.ce_trading_symbol)
            print("🎯 CE REVERSE Token:", self.ce_reverse_token, "CE Reverse Trading Symbol:", self.ce_reverse_trading_symbol)
            print("🎯 PE Token:", self.pe_token, "PE Trading Symbol:", self.pe_trading_symbol)
            print("🎯 PE REVERSE Token:", self.pe_reverse_token, "PE Reverse Trading Symbol:", self.pe_reverse_trading_symbol)

            initial_tokens = [self.ce_token, self.pe_token, self.nifty_token]
            initial_tokens = [token for token in initial_tokens if token is not None]

            if not initial_tokens:
                await self.send(text_data=json.dumps({'error': 'No valid tokens found'}))
                return

            print(f"📡 Initially subscribing to tokens: {initial_tokens}")

            _websocket_client.enableTrace(True)

            try:
                self.kws = KiteTicker(self.kite.api_key, self.kite.access_token)
                print("✅ KiteTicker object created")
            except Exception as e:
                error_msg = f"❌ KiteTicker object creation failed: {str(e)}"
                print(error_msg)
                await self.send(text_data=json.dumps({'error': error_msg}))
                return

            def safe_send_json(payload):
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.send(text_data=json.dumps(payload)), self.loop
                    )
                    try:
                        fut.result(timeout=3)
                    except Exception:
                        print("❌ Failed to send JSON payload to client")

            def on_ticks(ws, ticks):
                try:
                    asyncio.run_coroutine_threadsafe(self.process_ticks(ticks), self.loop)
                except Exception:
                    print("❌ Error scheduling process_ticks:", traceback.format_exc())

            def on_connect(ws, response):
                print("✅ Connected to Zerodha WebSocket")
                try:
                    ws.subscribe(initial_tokens)
                    ws.set_mode(ws.MODE_FULL, initial_tokens)
                    self.current_subscribed_tokens = initial_tokens
                    print(f"✅ Subscribed to {len(initial_tokens)} instruments")
                    safe_send_json({'info': 'Subscribed to tokens', 'tokens': initial_tokens})
                except Exception:
                    print("❌ Subscribe failure:", traceback.format_exc())
                    safe_send_json({'error': 'Subscribe failed'})

            def on_error(ws, code, reason):
                msg = f"❌ WebSocket Error: {code} - {reason}"
                print(msg)
                print(traceback.format_exc())
                safe_send_json({'error': msg})

            def on_close(ws, code, reason):
                msg = f"🔌 WebSocket Closed: {code} - {reason}"
                print(msg)
                safe_send_json({'info': msg})

            def on_reconnect(ws, attempts_count):
                msg = f"🔁 Reconnecting to WebSocket, attempt {attempts_count}"
                print(msg)
                safe_send_json({'info': msg})

            self.kws.on_ticks = on_ticks
            self.kws.on_connect = on_connect
            self.kws.on_error = on_error
            self.kws.on_close = on_close
            self.kws.on_reconnect = on_reconnect

            def run_websocket_thread():
                try:
                    self.kws.connect(threaded=True)
                except Exception as e:
                    print("❌ WebSocket thread connect exception:", str(e))
                    print(traceback.format_exc())
                    try:
                        print("Attempting fallback non-threaded connect...")
                        self.kws.connect(threaded=False)
                    except Exception as e2:
                        print("❌ Fallback connect failed:", str(e2))
                        safe_send_json({'error': f'WS connect failed: {str(e)} / {str(e2)}'})

            ws_thread = threading.Thread(target=run_websocket_thread, name="KiteTickerThread")
            ws_thread.daemon = True
            ws_thread.start()

            while self.keep_running:
                await asyncio.sleep(0)

        except Exception as e:
            error_msg = f'Stream setup failed: {str(e)}'
            print(error_msg)
            print(traceback.format_exc())
            await self.send(text_data=json.dumps({'error': error_msg}))

    async def process_ticks(self, ticks):
        """NEW: Improved tick processing that ensures spot price is always available"""
        current_ts = int(time.time() * 1000)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        # NEW: Process NIFTY ticks first to update spot price immediately
        nifty_ticks = [tick for tick in ticks if tick['instrument_token'] == self.nifty_token]
        option_ticks = [tick for tick in ticks if tick['instrument_token'] in [self.ce_token, self.pe_token]]
        
        # Process NIFTY ticks first
        for tick in nifty_ticks:
            await self.process_nifty_tick(tick, timestamp)
        
        # Process option ticks with guaranteed spot price
        for tick in option_ticks:
            await self.process_option_tick(tick, timestamp)
        
        # NEW: Process any pending option ticks now that spot price might be available
        await self.process_pending_option_ticks(timestamp)

    async def process_nifty_tick(self, tick, timestamp):
        """Process NIFTY tick and update spot price"""
        instrument_token = tick['instrument_token']
        ltp = tick.get('last_price', 0)
        volume = tick.get('volume', 0)
        change = tick.get('change', 0)
        
        self.latest_spot_price = ltp
        self.spot_price_initialized = True
        
        # Always send spot price update
        result = {
            'type': 'SPOT',
            'instrument_token': instrument_token,
            'ltp': ltp,
            'volume': volume,
            'timestamp': timestamp,
            'spot_price': ltp,
            'index_name': self.index_name,
            'change': change
        }
        await self.send(text_data=json.dumps(result))
        
        # Check buy conditions with fresh spot price
        if not self.order_placedCE and not self.order_placedPE:
            await self.check_buy_conditions(instrument_token, ltp, timestamp)

    async def process_option_tick(self, tick, timestamp):
        """Process CE/PE tick with guaranteed spot price handling"""
        instrument_token = tick['instrument_token']
        ltp = tick.get('last_price', 0)
        volume = tick.get('volume', 0)
        oi = tick.get('oi', 0)
        change = tick.get('change', 0)
        
        # If we already have an order placed, process bought token
        if self.order_placedCE or self.order_placedPE:
            if instrument_token == self.buy_token:
                await self.process_bought_token_tick(instrument_token, ltp, timestamp, volume, oi, change)
            return
        
        # For option ticks without orders, ensure spot price is available
        if not self.spot_price_initialized or self.latest_spot_price is None:
            # NEW: Buffer the option tick until spot price is available
            self.pending_option_ticks.append((tick, timestamp))
            print(f"⏳ Buffering option tick - waiting for spot price. Current buffer: {len(self.pending_option_ticks)}")
            return
        
        # Spot price is available - process the option tick
        instrument_type = "CE" if instrument_token == self.ce_token else "PE"
        
        result = {
            'type': instrument_type,
            'instrument_token': instrument_token,
            'ltp': ltp,
            'volume': volume,
            'oi': oi,
            'spot_price': self.latest_spot_price,  # Guaranteed non-null
            'timestamp': timestamp,
            'index_name': self.index_name,
            'change': change
        }
        await self.send(text_data=json.dumps(result))

    async def process_pending_option_ticks(self, timestamp):
        """Process any buffered option ticks now that spot price is available"""
        if not self.spot_price_initialized or self.latest_spot_price is None:
            return
            
        if self.pending_option_ticks:
            print(f"🔄 Processing {len(self.pending_option_ticks)} buffered option ticks")
            
        processed_ticks = []
        for tick, tick_timestamp in self.pending_option_ticks:
            instrument_token = tick['instrument_token']
            ltp = tick.get('last_price', 0)
            volume = tick.get('volume', 0)
            oi = tick.get('oi', 0)
            change = tick.get('change', 0)
            
            instrument_type = "CE" if instrument_token == self.ce_token else "PE"
            
            result = {
                'type': instrument_type,
                'instrument_token': instrument_token,
                'ltp': ltp,
                'volume': volume,
                'oi': oi,
                'spot_price': self.latest_spot_price,
                'timestamp': tick_timestamp,  # Use original timestamp
                'index_name': self.index_name,
                'change': change,
                'buffered': True  # Flag to indicate this was buffered
            }
            await self.send(text_data=json.dumps(result))
            processed_ticks.append((tick, tick_timestamp))
        
        # Remove processed ticks from buffer
        for tick_data in processed_ticks:
            if tick_data in self.pending_option_ticks:
                self.pending_option_ticks.remove(tick_data)

    async def process_bought_token_tick(self, instrument_token, ltp, timestamp, volume, oi, change):
        try:
            current_ltp = float(ltp)
            
            result = {
                'type': 'BOUGHT_OPTION',
                'instrument_token': instrument_token,
                'ltp': ltp,
                'spot_price': self.latest_spot_price,
                'timestamp': timestamp,
                'index_name': self.index_name,
                'change': change,
                'buy_price': self.buy_in_ltp,
                'locked_ltp': self.locked_ltp
            }
            await self.send(text_data=json.dumps(result))
            
            await self.process_trailing_sl(instrument_token, current_ltp, timestamp)
            
        except Exception as e:
            print(f"❌ Error processing bought token tick: {str(e)}")

    async def process_trailing_sl(self, instrument_token, current_ltp, timestamp):
        try:
            if not self.sell_order_placed and self.ltp_at_order is not None:
                
                # Initialize trailing SL
                if self.locked_ltp is None:
                    self.step_size = round(float(self.ltp_at_order) * self.step / 100, 2)
                    self.locked_ltp = round(float(self.ltp_at_order) - self.step_size, 2)
                    self.previous_ltp = float(self.ltp_at_order)
                    
                    await self.send(text_data=json.dumps({
                        'spot_price': self.latest_spot_price,
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

                await self.send(text_data=json.dumps({
                    'pnl_update': True,
                    'current_ltp': current_ltp,
                    'pnl_percent': pnl_percent,
                    'locked_ltp': self.locked_ltp
                }))

                if ((current_ltp <= self.locked_ltp and current_ltp < self.previous_ltp) or 
                    (current_ltp < self.locked_ltp)):
                    
                    print(f'🚨 Sell condition triggered for token: {self.buy_token}')
                    await self.place_sell_order(current_ltp)
                
                self.previous_ltp = current_ltp
                
        except Exception as e:
            print(f"❌ Error in trailing SL: {str(e)}")

    async def check_buy_conditions(self, instrument_token, ltp, timestamp):
        """Check conditions for placing buy orders"""
        try:
            # NEW: Use fresh API call for critical trading decisions
            try:
                nifty_quote = self.kite.quote([self.nifty_token])
                current_spot = nifty_quote[self.nifty_token]['last_price']
                print(f"🎯 Fresh spot price for trading decision: {current_spot}")
            except Exception as e:
                print(f"⚠️ Using cached spot price for trading: {self.latest_spot_price}")
                current_spot = self.latest_spot_price
          
            if (not self.order_placedCE and not self.order_placedPE and 
                current_spot is not None and 
                self.target_market_priceCE <= float(current_spot)):
                
                print(f"✅ CE Buy Condition Met: {current_spot}, Target: {self.target_market_priceCE}")
                await self.place_buy_order(self.ce_token, self.ce_trading_symbol, self.quantityCE, "CE", timestamp)
                return
            
            if (not self.order_placedPE and not self.order_placedCE and
                current_spot is not None and
                self.target_market_pricePE >= float(current_spot)):
                
                print(f"✅ PE Buy Condition Met: {current_spot}, Target: {self.target_market_pricePE}")
                await self.place_buy_order(self.pe_token, self.pe_trading_symbol, self.quantityPE, "PE", timestamp)
                
        except Exception as e:
            print(f"❌ Error in check_buy_conditions: {str(e)}")

    async def place_buy_order(self, token, trading_symbol, quantity, option_type, timestamp):
        """Place buy order for CE or PE using trading symbol"""
        try:
            print(f'🎯 Placing BUY order - Token: {token}, Trading Symbol: {trading_symbol}, Type: {option_type}, Qty: {quantity}')
            
            if not trading_symbol:
                raise ValueError(f"Trading symbol not found for {option_type}")
            
            order_id = await self.place_zerodha_order(
                transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                trading_symbol=trading_symbol,
                quantity=quantity,
                order_type=self.kite.ORDER_TYPE_MARKET,
                exchange=self.kite.EXCHANGE_NFO,
                product=self.kite.PRODUCT_NRML,
                validity=self.kite.VALIDITY_DAY
            )
            
            if order_id:
                await asyncio.sleep(0)
                
                order_details = await self.fetch_order_status(order_id)
                
                if order_details and order_details['status'] == 'COMPLETE':
                    self.order_placedCE = True
                    self.order_placedPE = True
                    self.buy_token = token
                    self.buy_trading_symbol = trading_symbol
                    self.buy_quantity = quantity
                    self.buy_in_ltp = float(order_details['average_price'])
                    self.ltp_at_order = self.buy_in_ltp
                    
                    if option_type == "CE":
                        self.reverse_token = self.ce_reverse_token
                        self.reverse_trading_symbol = self.ce_reverse_trading_symbol
                    else:
                        self.reverse_token = self.pe_reverse_token
                        self.reverse_trading_symbol = self.pe_reverse_trading_symbol
                    
                    new_tokens = [self.buy_token, self.nifty_token]
                    await self.update_subscription(new_tokens)
                    
                    await self.send(text_data=json.dumps({
                        'message': 'Order placed successfully...Waiting for square off',
                        'BUY_LTP': self.buy_in_ltp,
                        'Type': option_type,
                        'subscription_updated': True
                    }))
                    
                    self.log_order_event(
                        self.account_name,
                        "✅ Buy Order Placed",
                        {
                            'Token_Purchase': self.buy_token,
                            'Trading_Symbol': self.buy_trading_symbol,
                            'Market Value': self.latest_spot_price,
                            'Quantity': quantity,
                            'BUY LTP': self.buy_in_ltp,
                            "Total Amount": self.total_amount,
                            "Investable Amount": self.investable_amount,
                            "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                    )
                else:
                    error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                    self.log_order_event(
                        self.account_name,
                        "❌ BUY ORDER FAILED",
                        {
                            "Error": error_msg
                        }
                    )
                    await self.send(text_data=json.dumps({
                        'message': 'Order Failed'    
                    }))
                    
        except Exception as e:
            print(f"❌ Error placing buy order: {str(e)}")
            await self.send(text_data=json.dumps({'error': f'Order exception: {str(e)}'}))

    async def place_sell_order(self, current_ltp):
        """Place sell order and handle reverse trade if needed"""
        try:
            print(f'🎯 Placing SELL order - Token: {self.buy_token}, Trading Symbol: {self.buy_trading_symbol}, Qty: {self.buy_quantity}')
            
            if not self.buy_trading_symbol:
                raise ValueError("Buy trading symbol not found")
            
            order_id = await self.place_zerodha_order(
                transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                trading_symbol=self.buy_trading_symbol,
                quantity=self.buy_quantity,
                order_type=self.kite.ORDER_TYPE_MARKET,
                exchange=self.kite.EXCHANGE_NFO,
                product=self.kite.PRODUCT_NRML,
                validity=self.kite.VALIDITY_DAY
            )
            
            if order_id:
                await asyncio.sleep(0)
                
                order_details = await self.fetch_order_status(order_id)
                
                if order_details and order_details['status'] == 'COMPLETE':
                    self.sell_in_ltp = float(order_details['average_price'])
                    PnL = round(((self.sell_in_ltp - self.buy_in_ltp) / self.buy_in_ltp) * 100, 2)
                    self.sell_order_placed = True
                    
                    self.log_order_event(
                        self.account_name,
                        "✅ SELL Order Placed",
                        {
                            'Token_Purchase': self.buy_token,
                            'Trading_Symbol': self.buy_trading_symbol,
                            'Market Value': self.latest_spot_price,
                            'SELL LTP': self.sell_in_ltp,
                            'Quantity': self.buy_quantity,
                            "Total Amount": self.total_amount,
                            "Investable Amount": self.investable_amount,
                            "P & L percent": PnL,
                            "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                    )
                    
                    await self.send(text_data=json.dumps({
                        'message': 'SELL Order placed successfully',
                        'SELL_LTP': self.sell_in_ltp,
                        "pnl_percentage": PnL,
                    }))
                    
                    if self.reverse_Trade == "ON" and PnL < self.expected_profit_percent:
                        await self.execute_reverse_trade(PnL)
                    else:
                        self.reset_trade_flags()
                        await self.send(text_data=json.dumps({
                            'message': 'Trading completed - No reverse trade'
                        }))
                        
                else:
                    error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                    self.log_order_event(
                        self.account_name,
                        "❌ SELL ORDER FAILED",
                        {
                            "Error": error_msg
                        }
                    )
                    await self.send(text_data=json.dumps({
                        'message': 'SELL Order Failed'
                    }))
                    
        except Exception as e:
            print(f"❌ Error placing sell order: {str(e)}")
            await self.send(text_data=json.dumps({'error': f'Sell order error: {str(e)}'}))

    async def execute_reverse_trade(self, PnL):
        try:
            print("🔄 Executing reverse trade...")
            
            if not self.reverse_trading_symbol:
                print("❌ Reverse trading symbol not found")
                await self.send(text_data=json.dumps({'error': 'Reverse trading symbol not found'}))
                return
            
            if self.lot is None:
                print("⚠️ Lot size is None, using default value 75")
                
            if self.investable_amount is None:
                print("⚠️ Investable amount is None, using default value 40")
                
            self.previous_ltp = None
            self.ltp_at_order = None
            self.locked_ltp = None
            self.step_size = None
            self.buy_token = self.reverse_token
            self.buy_trading_symbol = self.reverse_trading_symbol
            
            if not self.reverse_trading_symbol:
                print("❌ Reverse trading symbol is None")
                await self.send(text_data=json.dumps({'error': 'Reverse trading symbol is None'}))
                return
            
            instrument_key = f"NFO:{self.reverse_trading_symbol}"
            print(f"🔍 Fetching LTP for: {instrument_key}")
            
            try:
                quote = self.kite.quote([instrument_key])
                print(f"📊 Quote response: {quote}")
                
                if instrument_key in quote:
                    instrument_data = quote[instrument_key]
                    rest_ltp = instrument_data.get('last_price')
                    if rest_ltp:
                        self.ltp_at_order = rest_ltp
                        print(f"✅ LTP fetched successfully: {self.ltp_at_order}")
                    else:
                        print("❌ Last price not found in quote data")
                        await self.send(text_data=json.dumps({'error': 'Last price not found in quote data'}))
                        return
                else:
                    print(f"❌ Instrument {instrument_key} not found in quote response")
                    await self.send(text_data=json.dumps({'error': f'Instrument {instrument_key} not found in quote'}))
                    return
                    
            except Exception as e:
                print(f"❌ Error fetching quote: {str(e)}")
                await self.send(text_data=json.dumps({'error': f'Quote fetch error: {str(e)}'}))
                return
            
            investable_amount = float(self.investable_amount)
            if PnL > 0:
                new_investable = investable_amount + (PnL / 100) * investable_amount
            else:
                new_investable = investable_amount - (abs(PnL) / 100) * investable_amount
            
            print(f'💰 New investable amount: {new_investable}')
            print(f'📊 Current LTP: {self.ltp_at_order}')
            print(f'📦 Lot size: {self.lot}')
            
            if self.ltp_at_order and self.ltp_at_order > 0:
                try:
                    lots_affordable = new_investable // (self.ltp_at_order * self.lot)
                    quantity = int(lots_affordable * self.lot)
                    print(f'📦 Reverse trade quantity: {quantity} (lots: {lots_affordable})')
                except Exception as e:
                    print(f"❌ Error calculating quantity: {str(e)}")
                    await self.send(text_data=json.dumps({'error': f'Quantity calculation error: {str(e)}'}))
                    return
            else:
                print("❌ Invalid LTP for quantity calculation")
                await self.send(text_data=json.dumps({'error': 'Invalid LTP for quantity calculation'}))
                return
            
            if quantity > 0:
                print(f"🎯 Executing reverse trade with token: {self.reverse_token}, Trading Symbol: {self.reverse_trading_symbol}")
                
                new_tokens = [self.reverse_token, self.nifty_token]
                await self.update_subscription(new_tokens)
                
                order_id = await self.place_zerodha_order(
                    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                    trading_symbol=self.reverse_trading_symbol,
                    quantity=quantity,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    exchange=self.kite.EXCHANGE_NFO,    
                    product=self.kite.PRODUCT_NRML,
                    validity=self.kite.VALIDITY_DAY
                )
                
                if order_id:
                    await asyncio.sleep(0)
                    order_details = await self.fetch_order_status(order_id)
                    
                    if order_details and order_details['status'] == 'COMPLETE':
                        price = float(order_details['average_price'])
                        self.ltp_at_order = price
                        self.buy_in_ltp = price
                        self.buy_quantity = quantity
                        self.reverse_Trade = "OFF"
                        self.toggle = False
                        self.investable_amount = new_investable
                        
                        self.sell_order_placed = False
                        self.locked_ltp = None
                        self.previous_ltp = None
                        
                        self.log_order_event(
                            self.account_name,
                            "✅ Reverse Buy Order Placed",
                            {
                                'Token_Purchase': self.reverse_token,
                                'Trading_Symbol': self.reverse_trading_symbol,
                                'Market Value': self.latest_spot_price,
                                'Quantity': quantity,
                                'BUY LTP': price,
                                "Total Amount": self.total_amount,
                                "Investable Amount": new_investable,
                                "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                        )
                        
                        await self.send(text_data=json.dumps({
                            'message': 'Reverse Order placed successfully...Waiting for square off',
                            'BUY_LTP': price,
                            'reverse_trade': True
                        }))
                        
                    else:
                        error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                        self.log_order_event(
                            self.account_name,
                            "❌ REVERSE BUY ORDER FAILED",
                            {
                                "Error": error_msg
                            }
                        )
                        await self.send(text_data=json.dumps({
                            'message': 'Reverse Order Failed'
                        }))
            else:
                print("❌ Invalid quantity for reverse trade")
                await self.send(text_data=json.dumps({
                    'message': 'Reverse trade skipped - invalid quantity'
                }))
                
        except Exception as e:
            print(f"❌ Error in reverse trade: {str(e)}")
            await self.send(text_data=json.dumps({'error': f'Reverse trade error: {str(e)}'}))