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
import websocket as _websocket_client   # for debug trace


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
        self.latest_spot_price = None
        self.keep_running = True
        self.nifty_token = None
        self.ce_token = None
        self.pe_token = None
        self.ce_reverse_token = None
        self.pe_reverse_token = None
        self.index_name = "NIFTY"  # Default index
        self.instruments_cache = None
        
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
        """Cache instruments to avoid multiple API calls"""
        if not self.instruments_cache:
            try:
                self.instruments_cache = self.kite.instruments("NFO")
                print(f"✅ Loaded {len(self.instruments_cache)} NFO instruments")
            except Exception as e:
                print(f"❌ Error fetching instruments: {str(e)}")
                return []
        return self.instruments_cache
    
    def get_instrument_tokens_by_trading_symbol(self, trading_symbol_input, index_name="NIFTY"):
        print("🔍 Raw input symbol:", trading_symbol_input)
        
        if not self.kite:
            print("❌ KiteConnect not initialized")
            return {"CE": None, "PE": None}
        
        instruments = self.get_instruments()
        if not instruments:
            return {"CE": None, "PE": None}
        
        clean_symbol = trading_symbol_input.replace(" ", "").upper()
        result = {"CE": None, "PE": None}
        
        for instrument in instruments:
            if instrument['tradingsymbol'].replace(" ", "").upper() == clean_symbol:
                if instrument['instrument_type'] == 'CE':
                    result["CE"] = instrument['instrument_token']
                    print(f"✅ CE Exact match found: {instrument['tradingsymbol']}, Token: {result['CE']}")
                elif instrument['instrument_type'] == 'PE':
                    result["PE"] = instrument['instrument_token']
                    print(f"✅ PE Exact match found: {instrument['tradingsymbol']}, Token: {result['PE']}")
                break
        
        if result["CE"] or result["PE"]:
            found_instrument = None
            for instrument in instruments:
                if instrument['instrument_token'] == (result["CE"] or result["PE"]):
                    found_instrument = instrument
                    break
            
            if found_instrument:
                opposite_type = "PE" if found_instrument['instrument_type'] == "CE" else "CE"
                for instrument in instruments:
                    if (instrument['strike'] == found_instrument['strike'] and
                        instrument['expiry'] == found_instrument['expiry'] and
                        instrument['instrument_type'] == opposite_type and
                        instrument['name'] == found_instrument['name']):
                        
                        if opposite_type == 'CE':
                            result["CE"] = instrument['instrument_token']
                            print(f"✅ CE Opposite match found: {instrument['tradingsymbol']}, Token: {result['CE']}")
                        else:
                            result["PE"] = instrument['instrument_token']
                            print(f"✅ PE Opposite match found: {instrument['tradingsymbol']}, Token: {result['PE']}")
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
            self.step = step
            self.expected_profit_percent = expected_profit_percent
            self.target_market_priceCE = float(target_market_priceCE) if target_market_priceCE else None
            self.target_market_pricePE = float(target_market_pricePE) if target_market_pricePE else None
            self.quantityCE = quantityCE
            self.quantityPE = quantityPE
            self.total_amount = total_amount
            self.investable_amount = investable_amount
            self.lot = lot
            self.reverse_Trade = reverse_Trade
            if not api_key or not access_token or not trading_symbol:
                await self.send(text_data=json.dumps({'error': 'Missing required fields: api_key, access_token, trading_symbol'}))
                return
                
            if not target_market_priceCE or not target_market_pricePE or not step or not quantityCE or not quantityPE:
                await self.send(text_data=json.dumps({'error': 'Missing trading parameters'}))
                return
            


            
            if not api_key or not access_token or not trading_symbol:
                await self.send(text_data=json.dumps({'error': 'Missing required fields: api_key, access_token, trading_symbol'}))
                return
                
            try:
                self.kite = KiteConnect(api_key=api_key)
                self.kite.set_access_token(access_token)
                print("✅ KiteConnect initialized successfully")
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

            ce_tokens = self.get_instrument_tokens_by_trading_symbol(trading_symbol, self.index_name)
            
            if trading_symbol_2:
                pe_tokens = self.get_instrument_tokens_by_trading_symbol(trading_symbol_2, self.index_name)
            else:
                pe_tokens = {"CE": None, "PE": None}
                if ce_tokens["CE"]:
                    pe_tokens["PE"] = ce_tokens["PE"]
                elif ce_tokens["PE"]:
                    pe_tokens["CE"] = ce_tokens["CE"]
            
            self.ce_token = ce_tokens.get("CE")
            self.ce_reverse_token = ce_tokens.get("PE")
            self.pe_token = pe_tokens.get("PE")
            self.pe_reverse_token = pe_tokens.get("CE")

            print("🎯 CE Token:", self.ce_token)
            print("🎯 CE REVERSE Token:", self.ce_reverse_token)
            print("🎯 PE Token:", self.pe_token)
            print("🎯 PE REVERSE Token:", self.pe_reverse_token)

            tokens = [self.ce_token, self.pe_token, self.ce_reverse_token, self.pe_reverse_token, self.nifty_token]
            tokens = [token for token in tokens if token is not None]

            if not tokens:
                await self.send(text_data=json.dumps({'error': 'No valid tokens found'}))
                return

            print(f"📡 Subscribing to tokens: {tokens}")

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
                    ws.subscribe(tokens)
                    ws.set_mode(ws.MODE_FULL, tokens)
                    print(f"✅ Subscribed to {len(tokens)} instruments")
                    safe_send_json({'info': 'Subscribed to tokens', 'tokens': tokens})
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
                await asyncio.sleep(1)

        except Exception as e:
            error_msg = f'Stream setup failed: {str(e)}'
            print(error_msg)
            print(traceback.format_exc())
            await self.send(text_data=json.dumps({'error': error_msg}))

    async def process_ticks(self, ticks):
        current_ts = int(time.time() * 1000)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        for tick in ticks:
            instrument_token = tick['instrument_token']
            ltp = tick.get('last_price', 0)
            volume = tick.get('volume', 0)
            oi = tick.get('oi', 0)
            change = tick.get('change', 0)
            
            if instrument_token == self.nifty_token:
                self.latest_spot_price = ltp
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
                continue
            
            instrument_type = "UNKNOWN"
            if instrument_token == self.ce_token:
                instrument_type = "CE"
            elif instrument_token == self.pe_token:
                instrument_type = "PE"
            elif instrument_token == self.ce_reverse_token:
                instrument_type = "CE_REVERSE"
            elif instrument_token == self.pe_reverse_token:
                instrument_type = "PE_REVERSE"
                
            result = {
                'type': instrument_type,
                'instrument_token': instrument_token,
                'ltp': ltp,
                'volume': volume,
                'oi': oi,
                'spot_price': self.latest_spot_price,
                'timestamp': timestamp,
                'index_name': self.index_name,
                'change': change
            }
            await self.send(text_data=json.dumps(result))


            
