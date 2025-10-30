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
        self.keep_running = True
        self.trading_symbol = None
        self.instrument_token = None
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
    
    def get_instrument_token_by_trading_symbol(self, trading_symbol_input):
        """Get instrument token for a single trading symbol"""
        print("🔍 Raw input symbol:", trading_symbol_input)
        
        if not self.kite:
            print("❌ KiteConnect not initialized")
            return None
        
        instruments = self.get_instruments()
        if not instruments:
            return None
        
        clean_symbol = trading_symbol_input.replace(" ", "").upper()
        
        for instrument in instruments:
            if instrument['tradingsymbol'].replace(" ", "").upper() == clean_symbol:
                token = instrument['instrument_token']
                print(f"✅ Exact match found: {instrument['tradingsymbol']}, Token: {token}")
                return token
        
        print(f"❌ No instrument found for symbol: {trading_symbol_input}")
        return None

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

            # Store the trading symbol
            self.trading_symbol = trading_symbol
            
            # Start streaming data
            asyncio.create_task(self.fetch_and_stream_data(trading_symbol))
            
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'Error processing message: {str(e)}'}))

    async def fetch_and_stream_data(self, trading_symbol):
        try:
            # Get instrument token for the provided trading symbol
            self.instrument_token = self.get_instrument_token_by_trading_symbol(trading_symbol)
            
            if not self.instrument_token:
                await self.send(text_data=json.dumps({'error': f'Instrument token not found for symbol: {trading_symbol}'}))
                return

            print(f"🎯 Trading Symbol: {trading_symbol}")
            print(f"🎯 Instrument Token: {self.instrument_token}")

            # Prepare tokens list - only the instrument token
            tokens = [self.instrument_token]

            print(f"📡 Subscribing to token: {tokens}")

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
                    safe_send_json({
                        'info': 'Subscribed to token', 
                        'token': self.instrument_token, 
                        'trading_symbol': trading_symbol
                    })
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
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        for tick in ticks:
            instrument_token = tick['instrument_token']
            
            # Only process our target instrument
            if instrument_token == self.instrument_token:
                ltp = tick.get('last_price', 0)
                volume = tick.get('volume', 0)
                oi = tick.get('oi', 0)
                change = tick.get('change', 0)
                
                result = {
                    'type': 'LTP_DATA',
                    'instrument_token': instrument_token,
                    'trading_symbol': self.trading_symbol,
                    'ltp': ltp,
                    'volume': volume,
                    'oi': oi,
                    'timestamp': timestamp,
                    'change': change
                }
                await self.send(text_data=json.dumps(result))