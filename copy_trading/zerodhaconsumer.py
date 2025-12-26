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
import pandas as pd
import threading
import re
import traceback
import websocket as _websocket_client
from .setup_log import log_order_event, logger
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

# Conditional imports for simulation mode
try:
    from kiteconnect import KiteConnect, KiteTicker
    REAL_KITE_AVAILABLE = True
except ImportError:
    REAL_KITE_AVAILABLE = False
    KiteConnect = None
    KiteTicker = None


# Import hybrid wrapper
from .hybrid_kite import HybridKiteConnect
from .models import TradeSession, TradeTransaction, ZerodhaInstrument, FundInstrument
from channels.db import database_sync_to_async
import uuid

@dataclass
class UserState:
    """Track individual user's trading state"""
    user_id: str  # Unique identifier (api_key + access_token hash)
    api_key: str
    access_token: str
    account_name: str
    
    # Trading parameters
    trading_symbol: str
    trading_symbol_2: Optional[str]
    index_name: str
    target_market_priceCE: float
    target_market_pricePE: float
    quantityCE: int
    quantityPE: int
    step: float
    expected_profit_percent: float
    total_amount: float
    investable_amount: float
    lot: int
    reverse_Trade: str
    
    # Instrument details
    kite: Optional[Any] = None  # Can be KiteConnect or KiteConnectSimulator
    ce_token: Optional[int] = None
    pe_token: Optional[int] = None
    ce_trading_symbol: Optional[str] = None
    pe_trading_symbol: Optional[str] = None
    ce_reverse_token: Optional[int] = None
    pe_reverse_token: Optional[int] = None
    ce_reverse_trading_symbol: Optional[str] = None
    pe_reverse_trading_symbol: Optional[str] = None
    
    # Trading state
    order_placedCE: bool = False
    order_placedPE: bool = False
    sell_order_placed: bool = False
    buy_token: Optional[int] = None
    buy_trading_symbol: Optional[str] = None
    buy_quantity: Optional[int] = None
    buy_in_ltp: Optional[float] = None
    sell_in_ltp: Optional[float] = None
    ltp_at_order: Optional[float] = None
    locked_ltp: Optional[float] = None
    previous_ltp: Optional[float] = None
    step_size: Optional[float] = None
    reverse_token: Optional[int] = None
    reverse_trading_symbol: Optional[str] = None
    
    # Locks for thread safety
    order_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_tick_time: float = 0
    last_buy_check_time: float = 0

class LiveOptionDataConsumerZerodha(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.users: Dict[str, UserState] = {}  # user_id -> UserState
        self.kws = None  # Shared WebSocket connection
        self.loop = None
        self.keep_running = True
        
        self.is_simulation = True
        
        # Simulation mode: Use Hybrid Wrapper
        self.hybrid_kite = None
        
        # Shared market data
        self.latest_spot_price = None
        self.nifty_token = None
        self.index_name = "NIFTY"
        self.exchange_type = "NSE"
        self.instruments_cache = None
        self.current_subscribed_tokens = []
        
        # Rate limiting for shared processing
        self.last_tick_time = 0
        self.tick_interval = 0.1  # Reduced for faster processing
        self.last_buy_check_time = 0
        self.buy_check_interval = 0.1  # Reduced for faster processing
        
    def log_order_event(self, account_name: str, title: str, data: dict):
        log_block = [f"\n{'='*20} {account_name.upper()} | {title} {'='*20}"]
        for key, value in data.items():
            log_block.append(f"{key}: {value}")
        log_block.append('-' * 60)
        logger.info('\n'.join(log_block))



    @database_sync_to_async
    def get_django_user(self, api_key):
        try:
            # Try to find user via ZerodhaInstrument using API key
            ins = ZerodhaInstrument.objects.filter(api_key=api_key).first()
            if ins:
                return ins.user
            
            # Fallback: Try to find user via FundInstrument using API key
            fund_ins = FundInstrument.objects.filter(api_key=api_key).first()
            if fund_ins:
                return fund_ins.user
                
            return None
        except Exception as e:
            print(f"Error fetching user: {e}")
            return None

    @database_sync_to_async
    def create_trade_session(self, django_user, investable_amount):
        try:
            session_id = str(uuid.uuid4())
            session = TradeSession.objects.create(
                user=django_user,
                session_id=session_id,
                initial_capital=investable_amount,
                current_capital=investable_amount
            )
            print(f"✅ Trade Session Created: {session_id}")
            return session
        except Exception as e:
            print(f"❌ Error creating trade session: {e}")
            return None
    
    def fetch_zerodha_user_name(self, api_key, access_token, is_simulation=False):
        try:
            if not REAL_KITE_AVAILABLE:
                raise ImportError("kiteconnect library not available")
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            
            profile = kite.profile()
            return profile.get('user_name', 'Unknown User')
        except Exception as e:
            print(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"
    
    def get_user_id(self, api_key: str, access_token: str) -> str:
        """Generate unique user ID"""
        return f"{api_key}_{hash(access_token)}"
    
    def get_instruments(self, index_name: str, kite: KiteConnect):
        """Get instruments for given index"""
        try:
            nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            bse_indices = ["SENSEX", "BANKEX", "SX50"]
            
            if index_name in nse_indices:
                return kite.instruments("NFO")
            elif index_name in bse_indices:
                return kite.instruments("BFO")
            else:
                print(f"❌ Unsupported index: {index_name}")
                return []
        except Exception as e:
            print(f"❌ Error fetching instruments: {str(e)}")
            return []
    
    def get_instrument_details_by_trading_symbol(self, trading_symbol_input: str, index_name: str, kite: KiteConnect):
        """Get both token and trading symbol details for CE and PE"""
        print("🔍 Raw input symbol:", trading_symbol_input)
        
        if not kite:
            print("❌ KiteConnect not initialized")
            return {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
        
        instruments = self.get_instruments(index_name, kite)
        if not instruments:
            return {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
        
        clean_symbol = trading_symbol_input.replace(" ", "").upper()
        result = {
            "CE": {"token": None, "trading_symbol": None}, 
            "PE": {"token": None, "trading_symbol": None}
        }
        
        for instrument in instruments:
            if instrument['tradingsymbol'].replace(" ", "").upper() == clean_symbol:
                if instrument['instrument_type'] == 'CE':
                    result["CE"]["token"] = instrument['instrument_token']
                    result["CE"]["trading_symbol"] = instrument['tradingsymbol']
                    print(f"✅ CE Exact match found: {instrument['tradingsymbol']}, Token: {result['CE']['token']}")
                elif instrument['instrument_type'] == 'PE':
                    result["PE"]["token"] = instrument['instrument_token']
                    result["PE"]["trading_symbol"] = instrument['tradingsymbol']
                    print(f"✅ PE Exact match found: {instrument['tradingsymbol']}, Token: {result['PE']['token']}")
                break
        
        if result["CE"]["token"] or result["PE"]["token"]:
            found_instrument = None
            for instrument in instruments:
                if instrument['instrument_token'] == (result["CE"]["token"] or result["PE"]["token"]):
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
                            result["CE"]["token"] = instrument['instrument_token']
                            result["CE"]["trading_symbol"] = instrument['tradingsymbol']
                            print(f"✅ CE Opposite match found: {instrument['tradingsymbol']}, Token: {result['CE']['token']}")
                        else:
                            result["PE"]["token"] = instrument['instrument_token']
                            result["PE"]["trading_symbol"] = instrument['tradingsymbol']
                            print(f"✅ PE Opposite match found: {instrument['tradingsymbol']}, Token: {result['PE']['token']}")
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

            # Strict expectation: Payload must be a list of users
            if isinstance(payload, list):
                users_data = payload
                # Check first user for simulation flag
                if users_data and isinstance(users_data[0], dict):
                    self.is_simulation = users_data[0].get('is_simulation', False)
            else:
                print("❌ Invalid payload format. Expected list of users.")
                await self.send(text_data=json.dumps({
                    'error': 'Invalid payload format. Expected list of users.'
                }))
                return

            if self.is_simulation:
                print("🎮 SIMULATION MODE ENABLED - Using Hybrid Simulator")

            print(f"📊 Processing {len(users_data)} user(s)")

            # Validate all users have same trading symbols and targets (for shared WebSocket)
            if len(users_data) > 1:
                first_user = users_data[0]
                for i, user_data in enumerate(users_data[1:], 1):
                    if (user_data.get('trading_symbol') != first_user.get('trading_symbol') or
                        user_data.get('trading_symbol_2') != first_user.get('trading_symbol_2') or
                        user_data.get('target_market_price_CE') != first_user.get('target_market_price_CE') or
                        user_data.get('target_market_price_PE') != first_user.get('target_market_price_PE') or
                        user_data.get('index_name', 'NIFTY') != first_user.get('index_name', 'NIFTY')):
                        await self.send(text_data=json.dumps({
                            'error': f'User {i+1} has different trading parameters. All users must have same symbols and targets for shared execution.'
                        }))
                        return

            # Process all users
            validated_users = []
            for user_data in users_data:
                api_key = user_data.get('api_key')
                access_token = user_data.get('access_token')
                trading_symbol = user_data.get('trading_symbol')
                trading_symbol_2 = user_data.get('trading_symbol_2')
                index_name = user_data.get('index_name', 'NIFTY')
                target_market_priceCE = user_data.get('target_market_price_CE')
                target_market_pricePE = user_data.get('target_market_price_PE')
                quantityCE = user_data.get('quantityCE')
                quantityPE = user_data.get('quantityPE')
                step = user_data.get('step')
                expected_profit_percent = user_data.get('profit_percent')
                total_amount = user_data.get("total_amount")
                investable_amount = user_data.get("investable_amount") 
                lot = user_data.get("lot")
                reverse_Trade = user_data.get("reverseTrade", "OFF")

                if not api_key or not access_token or not trading_symbol:
                    await self.send(text_data=json.dumps({
                        'error': f'Missing required fields for user: api_key, access_token, trading_symbol'
                    }))
                    continue

                if not target_market_priceCE or not target_market_pricePE or not step or not quantityCE or not quantityPE:
                    await self.send(text_data=json.dumps({
                        'error': f'Missing trading parameters for user'
                    }))
                    continue

                try:
                    # Initialize KiteConnect for this user (real or simulator)
                    if self.is_simulation:
                        # Hybrid Mode: Real Data + Simulated Orders
                        if not REAL_KITE_AVAILABLE:
                            raise ImportError("kiteconnect library not available. Real credentials required for Hybrid Simulation.")
                        
                        real_kite = KiteConnect(api_key=api_key)
                        real_kite.set_access_token(access_token)
                        
                        kite = HybridKiteConnect(real_kite)
                        # Use real profile fetch since we have real credentials
                        account_name = self.fetch_zerodha_user_name(api_key, access_token, is_simulation=False)
                    else:
                        if not REAL_KITE_AVAILABLE:
                            raise ImportError("kiteconnect library not available. Install with: pip install kiteconnect")
                        kite = KiteConnect(api_key=api_key)
                        kite.set_access_token(access_token)
                        account_name = self.fetch_zerodha_user_name(api_key, access_token, is_simulation=False)
                    
                    # Verify authentication
                    profile = kite.profile()
                    print(f"✅ Authentication successful for user: {profile.get('user_name', 'Unknown')} {'(SIMULATION)' if self.is_simulation else ''}")

                    user_id = self.get_user_id(api_key, access_token)
                    
                     # Create user state
                    user_state = UserState(
                        user_id=user_id,
                        api_key=api_key,
                        access_token=access_token,
                        account_name=account_name,
                        trading_symbol=trading_symbol,
                        trading_symbol_2=trading_symbol_2,
                        index_name=index_name,
                        target_market_priceCE=float(target_market_priceCE),
                        target_market_pricePE=float(target_market_pricePE),
                        quantityCE=quantityCE,
                        quantityPE=quantityPE,
                        step=step,
                        expected_profit_percent=expected_profit_percent,
                        total_amount=total_amount,
                        investable_amount=investable_amount,
                        lot=lot,
                        reverse_Trade=reverse_Trade,
                        kite=kite
                    )
                    
                    # Link user_state to hybrid kite for DB access
                    if self.is_simulation and isinstance(kite, HybridKiteConnect):
                        kite.user_state = user_state
                        
                        # Create DB Session
                        django_user = await self.get_django_user(api_key)
                        if django_user:
                            session = await self.create_trade_session(django_user, float(investable_amount))
                            if session:
                                kite.trade_session = session  # Attach session to kite wrapper
                        else:
                            print("⚠️ Django user not found for API key, session not saved to DB")
                    
                    self.users[user_id] = user_state
                    validated_users.append(user_state)
                    
                except Exception as e:
                    await self.send(text_data=json.dumps({
                        'error': f'KiteConnect initialization failed for user: {str(e)}'
                    }))
                    continue

            if not validated_users:
                await self.send(text_data=json.dumps({'error': 'No valid users to process'}))
                return

            # Use first user's data for shared setup (all should be same)
            first_user = validated_users[0]
            self.index_name = first_user.index_name
            
            # Setup shared market data stream
            asyncio.create_task(self.fetch_and_stream_data(first_user.trading_symbol, first_user.trading_symbol_2, validated_users))
            
        except Exception as e:
            await self.send(text_data=json.dumps({'error': f'Error processing message: {str(e)}'}))
            print(f"❌ Error in receive: {traceback.format_exc()}")

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

    async def place_zerodha_order(self, user_state: UserState, transaction_type, trading_symbol, quantity, order_type="MARKET", price=0, product=None, validity=None):
        """Place order using Zerodha KiteConnect API with trading symbol"""
        try:
            nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            bse_indices = ["SENSEX", "BANKEX", "SX50"]
            
            if user_state.index_name in nse_indices:
                exchange = user_state.kite.EXCHANGE_NFO
            elif user_state.index_name in bse_indices:
                exchange = user_state.kite.EXCHANGE_BFO
            else:
                exchange = user_state.kite.EXCHANGE_NFO
            
            if product is None:
                product = user_state.kite.PRODUCT_NRML
            if validity is None:
                validity = user_state.kite.VALIDITY_DAY
            
            if order_type.upper() == "MARKET":
                order_id = user_state.kite.place_order(
                    variety=user_state.kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    order_type=user_state.kite.ORDER_TYPE_MARKET,
                    product=product,
                    validity=validity
                )
            else:
                order_id = user_state.kite.place_order(
                    variety=user_state.kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    order_type=user_state.kite.ORDER_TYPE_LIMIT,
                    price=price,
                    product=product,
                    validity=validity
                )
            
            print(f"✅ Order placed successfully for {user_state.account_name}. Order ID: {order_id}")
            return order_id
            
        except Exception as e:
            print(f"❌ Order placement failed for {user_state.account_name}: {str(e)}")
            raise e

    async def fetch_order_status(self, user_state: UserState, order_id):
        """Fetch order status from Zerodha"""
        try:
            orders = user_state.kite.orders()
            for order in orders:
                if order['order_id'] == order_id:
                    return order
            return None
        except Exception as e:
            print(f"❌ Error fetching order status for {user_state.account_name}: {str(e)}")
            return None

    async def fetch_and_stream_data(self, trading_symbol, trading_symbol_2, users: list):
        """Setup shared market data stream for all users"""
        try:
            # Use first user's kite for instrument lookup (all should have same index)
            first_user = users[0]
            kite = first_user.kite
            
            nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            bse_indices = ["SENSEX", "BANKEX", "SX50"]
            
            if self.index_name in nse_indices:
                instruments = kite.instruments("NSE")
                self.exchange_type = "NSE"
            elif self.index_name in bse_indices:
                instruments = kite.instruments("BSE")
                self.exchange_type = "BSE"
            else:
                await self.send(text_data=json.dumps({'error': f'Unsupported index: {self.index_name}'}))
                return
            
            self.nifty_token = None
            
            index_map = {
                "NIFTY": "NIFTY 50",
                "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FIN SERVICE",
                "MIDCPNIFTY": "NIFTY MID SELECT",
                "SENSEX": "SENSEX",
                "BANKEX": "BANKEX",
                "SX50": "S&P BSE SENSEX 50"
            }
            
            index_tradingsymbol = index_map.get(self.index_name)
            if not index_tradingsymbol:
                await self.send(text_data=json.dumps({'error': f'Index {self.index_name} not found in mapping'}))
                return

            for inst in instruments:
                if inst['tradingsymbol'] == index_tradingsymbol:
                    self.nifty_token = inst['instrument_token']
                    break

            if not self.nifty_token:
                await self.send(text_data=json.dumps({'error': f'{self.index_name} token not found'}))
                return
            print(f"✅ {self.index_name} token found: {self.nifty_token}")

            # Get instrument details for all users (they should be same)
            ce_details = self.get_instrument_details_by_trading_symbol(trading_symbol, self.index_name, kite)
            
            if trading_symbol_2:
                pe_details = self.get_instrument_details_by_trading_symbol(trading_symbol_2, self.index_name, kite)
            else:
                pe_details = {"CE": {"token": None, "trading_symbol": None}, "PE": {"token": None, "trading_symbol": None}}
                if ce_details["CE"]["token"]:
                    pe_details["PE"]["token"] = ce_details["PE"]["token"]
                    pe_details["PE"]["trading_symbol"] = ce_details["PE"]["trading_symbol"]
                elif ce_details["PE"]["token"]:
                    pe_details["CE"]["token"] = ce_details["CE"]["token"]
                    pe_details["CE"]["trading_symbol"] = ce_details["CE"]["trading_symbol"]
            
            ce_token = ce_details["CE"]["token"]
            ce_trading_symbol = ce_details["CE"]["trading_symbol"]
            ce_reverse_token = ce_details["PE"]["token"]
            ce_reverse_trading_symbol = ce_details["PE"]["trading_symbol"]
            
            pe_token = pe_details["PE"]["token"]
            pe_trading_symbol = pe_details["PE"]["trading_symbol"]
            pe_reverse_token = pe_details["CE"]["token"]
            pe_reverse_trading_symbol = pe_details["CE"]["trading_symbol"]

            print("🎯 CE Token:", ce_token, "CE Trading Symbol:", ce_trading_symbol)
            print("🎯 CE REVERSE Token:", ce_reverse_token, "CE Reverse Trading Symbol:", ce_reverse_trading_symbol)
            print("🎯 PE Token:", pe_token, "PE Trading Symbol:", pe_trading_symbol)
            print("🎯 PE REVERSE Token:", pe_reverse_token, "PE Reverse Trading Symbol:", pe_reverse_trading_symbol)

            # Store instrument details in all user states
            for user in users:
                user.ce_token = ce_token
                user.ce_trading_symbol = ce_trading_symbol
                user.ce_reverse_token = ce_reverse_token
                user.ce_reverse_trading_symbol = ce_reverse_trading_symbol
                user.pe_token = pe_token
                user.pe_trading_symbol = pe_trading_symbol
                user.pe_reverse_token = pe_reverse_token
                user.pe_reverse_trading_symbol = pe_reverse_trading_symbol

            initial_tokens = [ce_token, pe_token, self.nifty_token]
            initial_tokens = [token for token in initial_tokens if token is not None]

            if not initial_tokens:
                await self.send(text_data=json.dumps({'error': 'No valid tokens found'}))
                return

            print(f"📡 Initially subscribing to tokens: {initial_tokens}")

            _websocket_client.enableTrace(True)

            # Use first user's credentials for WebSocket (all should work)
            # Use first user's credentials for WebSocket (all should work)
            try:
                # Hybrid Simulation uses REAL Market Data
                if not REAL_KITE_AVAILABLE:
                    raise ImportError("kiteconnect library not available")
                
                self.kws = KiteTicker(kite.api_key, kite.access_token)
                print(f"✅ KiteTicker object created ({'Hybrid Simulation' if self.is_simulation else 'Real Trading'})")

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
                    
                    def handle_exception(future):
                        try:
                            future.result()
                        except Exception as e:
                            print(f"❌ Failed to send JSON payload to client: {str(e)}")

                    fut.add_done_callback(handle_exception)

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
                    print(f"✅ Subscribed to {len(initial_tokens)} instruments for {len(users)} users")
                    safe_send_json({'info': f'Subscribed to tokens for {len(users)} users', 'tokens': initial_tokens, 'user_count': len(users)})
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
        """Process ticks with rate limiting - handles all users"""
        current_time = time.time()
        # print(f"📨 Processing {len(ticks)} ticks... Last tick: {self.last_tick_time}, Interval: {self.tick_interval}") 
        if current_time - self.last_tick_time < self.tick_interval:
            return
            
        self.last_tick_time = current_time
        
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
                print(f"📉 NIFTY Spot Updated: {ltp}")
                
                # Send spot price to frontend
                active_users = [u for u in self.users.values() if not u.order_placedCE and not u.order_placedPE]
                if active_users:
                    result = {
                        'type': 'SPOT',
                        'instrument_token': instrument_token,
                        'ltp': ltp,
                        'volume': volume,
                        'timestamp': timestamp,
                        'spot_price': ltp,
                        'index_name': self.index_name,
                        'exchange': self.exchange_type,
                        'change': change
                    }
                    await self.send(text_data=json.dumps(result))
                
                # Check buy conditions for all users in parallel
                await self.check_buy_conditions_all_users(instrument_token, ltp, timestamp)
                continue
            
            # Process bought tokens for all users in parallel
            sell_tasks = []
            for user_id, user_state in self.users.items():
                if (user_state.order_placedCE or user_state.order_placedPE) and instrument_token == user_state.buy_token:
                    sell_tasks.append(self.process_bought_token_tick(user_state, instrument_token, ltp, timestamp, volume, oi, change))
            
            if sell_tasks:
                await asyncio.gather(*sell_tasks, return_exceptions=True)
            
            # Send option data for users waiting to buy
            active_users = [u for u in self.users.values() if not u.order_placedCE and not u.order_placedPE]
            if active_users:
                instrument_type = "UNKNOWN"
                if instrument_token == active_users[0].ce_token:
                    instrument_type = "CE"
                elif instrument_token == active_users[0].pe_token:
                    instrument_type = "PE"
                
                if instrument_type in ["CE", "PE"]:
                    result = {
                        'type': instrument_type,
                        'instrument_token': instrument_token,
                        'ltp': ltp,
                        'volume': volume,
                        'oi': oi,
                        'spot_price': self.latest_spot_price,
                        'timestamp': timestamp,
                        'index_name': self.index_name,
                        'exchange': self.exchange_type,
                        'change': change
                    }
                    await self.send(text_data=json.dumps(result))

    async def check_buy_conditions_all_users(self, instrument_token, ltp, timestamp):
        """Check buy conditions for all users in parallel"""
        current_time = time.time()
        if current_time - self.last_buy_check_time < self.buy_check_interval:
            return
            
        self.last_buy_check_time = current_time
        
        # Get all users who haven't placed orders yet
        users_to_check = [u for u in self.users.values() if not u.order_placedCE and not u.order_placedPE]
        
        if not users_to_check:
            return
        
        # Check conditions for all users
        buy_tasks = []
        for user_state in users_to_check:
            print(f"🔍 Checking {user_state.account_name} | Spot: {self.latest_spot_price} | CE Target: {user_state.target_market_priceCE} | PE Target: {user_state.target_market_pricePE}")
            # CE Buy Condition
            if (self.latest_spot_price is not None and 
                user_state.target_market_priceCE <= float(self.latest_spot_price)):
                
                if not user_state.ce_trading_symbol:
                    print(f"❌ Skipping CE Buy for {user_state.account_name}: Trading Symbol not found")
                    # Disable further checks for this user to prevent log spam
                    user_state.order_placedCE = True 
                    continue

                print(f"✅ CE Buy Condition Met for {user_state.account_name}: {self.latest_spot_price}, Target: {user_state.target_market_priceCE}")
                buy_tasks.append(self.place_buy_order(user_state, user_state.ce_token, user_state.ce_trading_symbol, user_state.quantityCE, "CE", timestamp))
            
            # PE Buy Condition
            elif (self.latest_spot_price is not None and
                  user_state.target_market_pricePE >= float(self.latest_spot_price)):
                
                if not user_state.pe_trading_symbol:
                    print(f"❌ Skipping PE Buy for {user_state.account_name}: Trading Symbol not found")
                    # Disable further checks for this user (using flag to stop loop)
                    user_state.order_placedPE = True
                    continue

                print(f"✅ PE Buy Condition Met for {user_state.account_name}: {self.latest_spot_price}, Target: {user_state.target_market_pricePE}")
                buy_tasks.append(self.place_buy_order(user_state, user_state.pe_token, user_state.pe_trading_symbol, user_state.quantityPE, "PE", timestamp))
        
        # Execute all buy orders in parallel
        if buy_tasks:
            print(f"🚀 Executing {len(buy_tasks)} buy orders in parallel...")
            await asyncio.gather(*buy_tasks, return_exceptions=True)

    async def process_bought_token_tick(self, user_state: UserState, instrument_token, ltp, timestamp, volume, oi, change):
        """Process ticks only for the bought token"""
        try:
            current_ltp = float(ltp)
            
            result = {
                'type': 'BOUGHT_OPTION',
                'user_id': user_state.user_id,
                'account_name': user_state.account_name,
                'instrument_token': instrument_token,
                'ltp': ltp,
                'volume': volume,
                'oi': oi,
                'spot_price': self.latest_spot_price,
                'timestamp': timestamp,
                'index_name': self.index_name,
                'exchange': self.exchange_type,
                'change': change,
                'buy_price': user_state.buy_in_ltp,
                'locked_ltp': user_state.locked_ltp
            }
            await self.send(text_data=json.dumps(result))
            
            # Process for trailing SL
            await self.process_trailing_sl(user_state, instrument_token, current_ltp, timestamp)
            
        except Exception as e:
            print(f"❌ Error processing bought token tick for {user_state.account_name}: {str(e)}")

    async def process_trailing_sl(self, user_state: UserState, instrument_token, current_ltp, timestamp):
        """Process trailing stop loss for bought token"""
        current_time = time.time()
        if current_time - user_state.last_tick_time < self.tick_interval:
            return
            
        user_state.last_tick_time = current_time
            
        try:
            if not user_state.sell_order_placed and user_state.ltp_at_order is not None:
                
                if user_state.locked_ltp is None:
                    user_state.step_size = round(float(user_state.ltp_at_order) * user_state.step / 100, 2)
                    user_state.locked_ltp = round(float(user_state.ltp_at_order) - user_state.step_size, 2)
                    user_state.previous_ltp = float(user_state.ltp_at_order)
                    
                    await self.send(text_data=json.dumps({
                        'init_SL': True,
                        'user_id': user_state.user_id,
                        'account_name': user_state.account_name,
                        'locked_LTP': user_state.locked_ltp,
                        'step_size': user_state.step_size
                    }))
                
                print(f"📈 {user_state.account_name} - Buy: {user_state.ltp_at_order} | Locked SL: {user_state.locked_ltp} | Live LTP: {current_ltp}")
                
                if current_ltp > user_state.previous_ltp:
                    while current_ltp >= user_state.locked_ltp + user_state.step_size:
                        user_state.locked_ltp = round(user_state.locked_ltp + user_state.step_size, 2)
                    
                    if user_state.locked_ltp == user_state.ltp_at_order:
                        user_state.locked_ltp = round(user_state.locked_ltp - user_state.step_size, 2)
                
                pnl_percent = round(((current_ltp - float(user_state.ltp_at_order)) / float(user_state.ltp_at_order)) * 100, 2)
                print(f"📈 {user_state.account_name} - Buy: {user_state.ltp_at_order} | Locked SL: {user_state.locked_ltp} | Live LTP: {current_ltp} | P&L: {pnl_percent}%")

                await self.send(text_data=json.dumps({
                    'pnl_update': True,
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name,
                    'current_ltp': current_ltp,
                    'spot': self.latest_spot_price,
                    'pnl_percent': pnl_percent,
                    'locked_ltp': user_state.locked_ltp
                }))

                # Check sell condition
                if ((current_ltp <= user_state.locked_ltp and current_ltp < user_state.previous_ltp) or 
                    (current_ltp < user_state.locked_ltp)):
                    
                    # Double check flag effectively to prevent multiple triggers
                    if user_state.sell_order_placed:
                         return

                    user_state.sell_order_placed = True
                    print(f'🚨 Sell condition triggered for {user_state.account_name}, token: {user_state.buy_token}')
                    await self.place_sell_order(user_state, current_ltp, force_execution=True)
                
                user_state.previous_ltp = current_ltp
                
        except Exception as e:
            print(f"❌ Error in trailing SL for {user_state.account_name}: {str(e)}")

    async def place_buy_order(self, user_state: UserState, token, trading_symbol, quantity, option_type, timestamp):
        """Place buy order for CE or PE using trading symbol"""
        async with user_state.order_lock:
            try:
                # Double check inside lock
                if user_state.order_placedCE or user_state.order_placedPE:
                    return
                
                print(f'🎯 Placing BUY order for {user_state.account_name} - Token: {token}, Trading Symbol: {trading_symbol}, Type: {option_type}, Qty: {quantity}')
                
                if not trading_symbol:
                    raise ValueError(f"Trading symbol not found for {option_type}")
                
                # Set flags immediately to prevent duplicate orders
                user_state.order_placedCE = True
                user_state.order_placedPE = True
                
                order_id = await self.place_zerodha_order(
                    user_state,
                    transaction_type=user_state.kite.TRANSACTION_TYPE_BUY,
                    trading_symbol=trading_symbol,
                    quantity=quantity,
                    order_type=user_state.kite.ORDER_TYPE_MARKET,
                    product=user_state.kite.PRODUCT_NRML,
                    validity=user_state.kite.VALIDITY_DAY
                )
                
                if order_id:
                    # Reduced delay for faster execution
                    await asyncio.sleep(0.5)
                    
                    order_details = await self.fetch_order_status(user_state, order_id)
                    
                    if order_details and order_details['status'] == 'COMPLETE':
                        user_state.buy_token = token
                        user_state.buy_trading_symbol = trading_symbol
                        user_state.buy_quantity = quantity
                        user_state.buy_in_ltp = float(order_details['average_price'])
                        user_state.ltp_at_order = user_state.buy_in_ltp
                        
                        if option_type == "CE":
                            user_state.reverse_token = user_state.ce_reverse_token
                            user_state.reverse_trading_symbol = user_state.ce_reverse_trading_symbol
                        else:
                            user_state.reverse_token = user_state.pe_reverse_token
                            user_state.reverse_trading_symbol = user_state.pe_reverse_trading_symbol
                        
                        # Update subscription to include bought token
                        new_tokens = list(set(self.current_subscribed_tokens + [user_state.buy_token]))
                        await self.update_subscription(new_tokens)
                        
                        await self.send(text_data=json.dumps({
                            'message': 'Order placed successfully...Waiting for square off',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name,
                            'BUY_LTP': user_state.buy_in_ltp,
                            'Type': option_type,
                            'subscription_updated': True
                        }))
                        
                        self.log_order_event(
                            user_state.account_name,
                            "✅ Buy Order Placed",
                            {
                                'Token_Purchase': user_state.buy_token,
                                'Trading_Symbol': user_state.buy_trading_symbol,
                                'Market Value': self.latest_spot_price,
                                'Quantity': quantity,
                                'BUY LTP': user_state.buy_in_ltp,
                                "Total Amount": user_state.total_amount,
                                "Investable Amount": user_state.investable_amount,
                                "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                        )
                    else:
                        # Reset flags if order failed
                        user_state.order_placedCE = False
                        user_state.order_placedPE = False
                        error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                        self.log_order_event(
                            user_state.account_name,
                            "❌ BUY ORDER FAILED",
                            {
                                "Error": error_msg
                            }
                        )
                        await self.send(text_data=json.dumps({
                            'message': 'Order Failed',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name
                        }))
                    
            except Exception as e:
                # Reset flags on exception
                user_state.order_placedCE = False
                user_state.order_placedPE = False
                print(f"❌ Error placing buy order for {user_state.account_name}: {str(e)}")
                await self.send(text_data=json.dumps({
                    'error': f'Order exception: {str(e)}',
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name
                }))

    async def place_sell_order(self, user_state: UserState, current_ltp, force_execution=False):
        """Place sell order and handle reverse trade if needed"""
        async with user_state.order_lock:
            try:

                print(f'Placing SELL order for {user_state.account_name} - Token: {user_state.buy_token}, Qty: {user_state.buy_quantity}')
                # Double check inside lock
                if user_state.sell_order_placed and not force_execution:
                    print(f"🔄 Sell order already placed for {user_state.account_name}, skipping...")
                    return
                    
                print(f'🎯 Placing SELL order for {user_state.account_name} - Token: {user_state.buy_token}, Trading Symbol: {user_state.buy_trading_symbol}, Qty: {user_state.buy_quantity}')
                
                if not user_state.buy_trading_symbol:
                    raise ValueError("Buy trading symbol not found")
                
                # Set flag immediately
                user_state.sell_order_placed = True
                
                order_id = await self.place_zerodha_order(
                    user_state,
                    transaction_type=user_state.kite.TRANSACTION_TYPE_SELL,
                    trading_symbol=user_state.buy_trading_symbol,
                    quantity=user_state.buy_quantity,
                    order_type=user_state.kite.ORDER_TYPE_MARKET,
                    product=user_state.kite.PRODUCT_NRML,
                    validity=user_state.kite.VALIDITY_DAY
                )
                
                if order_id:
                    # Reduced delay for faster execution
                    await asyncio.sleep(0.5)
                    
                    order_details = await self.fetch_order_status(user_state, order_id)
                    
                    if order_details and order_details['status'] == 'COMPLETE':
                        user_state.sell_in_ltp = float(order_details['average_price'])
                        PnL = round(((user_state.sell_in_ltp - user_state.buy_in_ltp) / user_state.buy_in_ltp) * 100, 2)
                        
                        self.log_order_event(
                            user_state.account_name,
                            "✅ SELL Order Placed",
                            {
                                'Token_Purchase': user_state.buy_token,
                                'Trading_Symbol': user_state.buy_trading_symbol,
                                'Market Value': self.latest_spot_price,
                                'SELL LTP': user_state.sell_in_ltp,
                                'Quantity': user_state.buy_quantity,
                                "Total Amount": user_state.total_amount,
                                "Investable Amount": user_state.investable_amount,
                                "P & L percent": PnL,
                                "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                        )
                        
                        await self.send(text_data=json.dumps({
                            'message': 'SELL Order placed successfully',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name,
                            'SELL_LTP': user_state.sell_in_ltp,
                            "pnl_percentage": PnL,
                        }))
                        
                        if user_state.reverse_Trade == "ON" and PnL < user_state.expected_profit_percent:
                            await self.execute_reverse_trade(user_state, PnL)
                        else:
                            # Reset flags
                            user_state.order_placedCE = False
                            user_state.order_placedPE = False
                            user_state.sell_order_placed = False
                            user_state.buy_token = None
                            user_state.buy_trading_symbol = None
                            user_state.buy_quantity = None
                            user_state.buy_in_ltp = None
                            user_state.ltp_at_order = None
                            user_state.locked_ltp = None
                            user_state.previous_ltp = None
                            
                            await self.send(text_data=json.dumps({
                                'message': 'Trading completed - No reverse trade',
                                'user_id': user_state.user_id,
                                'account_name': user_state.account_name
                            }))
                            
                    else:
                        # Reset sell flag if order failed
                        user_state.sell_order_placed = False
                        error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                        self.log_order_event(
                            user_state.account_name,
                            "❌ SELL ORDER FAILED",
                            {
                                "Error": error_msg
                            }
                        )
                        await self.send(text_data=json.dumps({
                            'message': 'SELL Order Failed',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name
                        }))
                        
            except Exception as e:
                # Reset sell flag on exception
                user_state.sell_order_placed = False
                print(f"❌ Error placing sell order for {user_state.account_name}: {str(e)}")
                await self.send(text_data=json.dumps({
                    'error': f'Sell order error: {str(e)}',
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name
                }))

    async def execute_reverse_trade(self, user_state: UserState, PnL):
        """Execute reverse trade after sell"""
        try:
            print(f"🔄 Executing reverse trade for {user_state.account_name}...")
            
            if not user_state.reverse_trading_symbol:
                print(f"❌ Reverse trading symbol not found for {user_state.account_name}")
                await self.send(text_data=json.dumps({
                    'error': 'Reverse trading symbol not found',
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name
                }))
                return
            
            user_state.previous_ltp = None
            user_state.ltp_at_order = None
            user_state.locked_ltp = None
            user_state.step_size = None
            user_state.buy_token = user_state.reverse_token
            user_state.buy_trading_symbol = user_state.reverse_trading_symbol
            
            instrument_key = f"NFO:{user_state.reverse_trading_symbol}"
            print(f"🔍 Fetching LTP for: {instrument_key}")
            
            try:
                quote = user_state.kite.quote([instrument_key])
                print(f"📊 Quote response: {quote}")
                
                if instrument_key in quote:
                    instrument_data = quote[instrument_key]
                    rest_ltp = instrument_data.get('last_price')
                    if rest_ltp:
                        user_state.ltp_at_order = rest_ltp
                        print(f"✅ LTP fetched successfully: {user_state.ltp_at_order}")
                    else:
                        print("❌ Last price not found in quote data")
                        await self.send(text_data=json.dumps({
                            'error': 'Last price not found in quote data',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name
                        }))
                        return
                else:
                    print(f"❌ Instrument {instrument_key} not found in quote response")
                    await self.send(text_data=json.dumps({
                        'error': f'Instrument {instrument_key} not found in quote',
                        'user_id': user_state.user_id,
                        'account_name': user_state.account_name
                    }))
                    return
                    
            except Exception as e:
                print(f"❌ Error fetching quote for {user_state.account_name}: {str(e)}")
                await self.send(text_data=json.dumps({
                    'error': f'Quote fetch error: {str(e)}',
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name
                }))
                return

            investable_amount = float(user_state.investable_amount)
            if PnL > 0:
                new_investable = investable_amount + (PnL / 100) * investable_amount
            else:
                new_investable = investable_amount - (abs(PnL) / 100) * investable_amount
            
            print(f'💰 New investable amount for {user_state.account_name}: {new_investable}')
            print(f'📊 Current LTP: {user_state.ltp_at_order}')
            
            user_state.rq = user_state.lot * (new_investable // (user_state.ltp_at_order * user_state.lot))
            quantity = int(user_state.rq)
            print(f'📦 Reverse trade quantity for {user_state.account_name}: {quantity}')
            
            if quantity > 0:
                print(f"🎯 Executing reverse trade for {user_state.account_name} with token: {user_state.reverse_token}, Trading Symbol: {user_state.reverse_trading_symbol}")
                
                new_tokens = list(set(self.current_subscribed_tokens + [user_state.reverse_token]))
                await self.update_subscription(new_tokens)
                
                order_id = await self.place_zerodha_order(
                    user_state,
                    transaction_type=user_state.kite.TRANSACTION_TYPE_BUY,
                    trading_symbol=user_state.reverse_trading_symbol,
                    quantity=quantity,
                    order_type=user_state.kite.ORDER_TYPE_MARKET,
                    product=user_state.kite.PRODUCT_NRML,
                    validity=user_state.kite.VALIDITY_DAY
                )
                
                if order_id:
                    await asyncio.sleep(0.5)  # Reduced delay
                    order_details = await self.fetch_order_status(user_state, order_id)
                    
                    if order_details and order_details['status'] == 'COMPLETE':
                        price = float(order_details['average_price'])
                        user_state.ltp_at_order = price
                        user_state.buy_in_ltp = price
                        user_state.buy_quantity = quantity
                        user_state.reverse_Trade = "OFF"
                        user_state.investable_amount = new_investable
                        
                        # Reset sell flag to continue tracking
                        user_state.sell_order_placed = False
                        user_state.locked_ltp = None
                        user_state.previous_ltp = None
                        
                        self.log_order_event(
                            user_state.account_name,
                            "✅ Reverse Buy Order Placed",
                            {
                                'Token_Purchase': user_state.reverse_token,
                                'Trading_Symbol': user_state.reverse_trading_symbol,
                                'Market Value': self.latest_spot_price,
                                'Quantity': quantity,
                                'BUY LTP': price,
                                "Total Amount": user_state.total_amount,
                                "Investable Amount": new_investable,
                                "Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                        )
                        
                        await self.send(text_data=json.dumps({
                            'message': 'Reverse Order placed successfully...Waiting for square off',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name,
                            'BUY_LTP': price,
                            'reverse_trade': True
                        }))
                        
                    else:
                        error_msg = order_details.get('status_message', 'Unknown error') if order_details else 'Order not completed'
                        self.log_order_event(
                            user_state.account_name,
                            "❌ REVERSE BUY ORDER FAILED",
                            {
                                "Error": error_msg
                            }
                        )
                        await self.send(text_data=json.dumps({
                            'message': 'Reverse Order Failed',
                            'user_id': user_state.user_id,
                            'account_name': user_state.account_name
                        }))
            else:
                print(f"❌ Invalid quantity for reverse trade for {user_state.account_name}")
                await self.send(text_data=json.dumps({
                    'message': 'Reverse trade skipped - invalid quantity',
                    'user_id': user_state.user_id,
                    'account_name': user_state.account_name
                }))
                
        except Exception as e:
            print(f"❌ Error in reverse trade for {user_state.account_name}: {str(e)}")
            await self.send(text_data=json.dumps({
                'error': f'Reverse trade error: {str(e)}',
                'user_id': user_state.user_id,
                'account_name': user_state.account_name
            }))
