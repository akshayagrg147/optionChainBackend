import os
import json
import asyncio
import time
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
import logging
import traceback
from typing import Dict, Optional, Any
from channels.db import database_sync_to_async
import uuid
import threading

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

# Import logger from Manualtrade app
try:
    from Manualtrade.logger2 import write_log_to_txt2
except ImportError:
    # Fallback if logger not available
    def write_log_to_txt2(message):
        logger.info(message)

logger = logging.getLogger(__name__)


class ManualZerodhaTradeConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for manual Zerodha trading.
    - Accepts order placement messages and executes immediately
    - Supports Hybrid simulator mode
    - Handles connection close and reestablish logic
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.users: Dict[str, Dict[str, Any]] = {}  # user_id -> user_data
        self.loop = None
        self.keep_running = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 3  # seconds
        # Market data subscription tracking
        self.market_data_subscriptions: Dict[str, Dict[str, Any]] = {}  # connection_id -> subscription_data
        self.kws_instances: Dict[str, Any] = {}  # connection_id -> KiteTicker instance
        self.positions: Dict[str, Dict[str, Any]] = {}  # connection_id -> positions (CE/PE bought at prices)
        
    @database_sync_to_async
    def get_django_user(self, api_key):
        """Get Django user from API key"""
        try:
            ins = ZerodhaInstrument.objects.filter(api_key=api_key).first()
            if ins:
                return ins.user
            
            fund_ins = FundInstrument.objects.filter(api_key=api_key).first()
            if fund_ins:
                return fund_ins.user
                
            return None
        except Exception as e:
            logger.error(f"Error fetching user: {e}")
            return None

    @database_sync_to_async
    def create_trade_session(self, django_user, investable_amount):
        """Create trade session for tracking"""
        try:
            session_id = str(uuid.uuid4())
            session = TradeSession.objects.create(
                user=django_user,
                session_id=session_id,
                initial_capital=investable_amount,
                current_capital=investable_amount
            )
            logger.info(f"✅ Trade Session Created: {session_id}")
            return session
        except Exception as e:
            logger.error(f"❌ Error creating trade session: {e}")
            return None

    def fetch_zerodha_user_name(self, api_key, access_token):
        """Fetch user name from Zerodha API"""
        try:
            if not REAL_KITE_AVAILABLE:
                return "Unknown User"
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            profile = kite.profile()
            return profile.get('user_name', 'Unknown User')
        except Exception as e:
            logger.error(f"Error fetching user name: {str(e)}")
            return "Unknown User"

    def get_user_id(self, api_key: str, access_token: str) -> str:
        """Generate unique user ID"""
        return f"{api_key}_{hash(access_token)}"

    async def connect(self):
        """Handle WebSocket connection"""
        await self.accept()
        self.keep_running = True
        self.reconnect_attempts = 0
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()
        logger.info("✅ Manual Trade WebSocket connection established")
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'status': 'connected',
            'message': 'WebSocket connected successfully'
        }))

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        self.keep_running = False
        logger.info(f"🔌 Manual Trade WebSocket connection closed (code: {close_code})")
        
        # Clean up market data subscriptions
        connection_id = id(self)
        if connection_id in self.kws_instances:
            try:
                kws = self.kws_instances[connection_id]
                # Set keep_running to False to stop processing ticks
                if hasattr(self, '_last_tick_time') and connection_id in self._last_tick_time:
                    del self._last_tick_time[connection_id]
                kws.close()
                logger.info(f"✅ Closed KiteTicker for connection {connection_id}")
            except Exception as e:
                logger.error(f"Error closing KiteTicker: {e}", exc_info=True)
            finally:
                if connection_id in self.kws_instances:
                    del self.kws_instances[connection_id]
        
        if connection_id in self.market_data_subscriptions:
            del self.market_data_subscriptions[connection_id]
        
        if connection_id in self.positions:
            del self.positions[connection_id]
        
        # Clean up user sessions
        for user_id in list(self.users.keys()):
            user_data = self.users[user_id]
            if user_data.get('kite'):
                try:
                    if isinstance(user_data['kite'], HybridKiteConnect):
                        # Hybrid kite cleanup if needed
                        pass
                except Exception as e:
                    logger.error(f"Error cleaning up kite for {user_id}: {e}")
        
        self.users.clear()

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            payload = json.loads(text_data)
            message_type = payload.get('type', 'order')
            
            logger.info(f"📨 Received message type: {message_type}")
            
            if message_type == 'order':
                await self.handle_order_message(payload)
            elif message_type == 'subscribe_market_data':
                await self.handle_subscribe_market_data(payload)
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                }))
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}")
            logger.error(traceback.format_exc())
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error processing message: {str(e)}'
            }))

    async def handle_order_message(self, payload):
        """Handle order placement message"""
        try:
            # Extract order parameters
            api_key = payload.get('api_key')
            access_token = payload.get('access_token')
            tradingsymbol = payload.get('tradingsymbol')
            exchange = payload.get('exchange', 'NFO')
            transaction_type = payload.get('transaction_type', 'BUY')
            order_type = payload.get('order_type', 'MARKET')
            quantity = payload.get('quantity')
            product = payload.get('product', 'MIS')
            validity = payload.get('validity', 'DAY')
            variety = payload.get('variety', 'regular')
            price = payload.get('price')
            trigger_price = payload.get('trigger_price')
            tag = payload.get('tag', 'manual_trade')
            is_simulation = payload.get('is_simulation', False)
            investable_amount = payload.get('investable_amount', 0)
            total_amount = payload.get('total_amount', 0)
            
            # Validation
            if not all([api_key, access_token, tradingsymbol, quantity]):
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Missing required fields: api_key, access_token, tradingsymbol, quantity'
                }))
                return
            
            # Get or create user session
            user_id = self.get_user_id(api_key, access_token)
            
            if user_id not in self.users:
                # Initialize user session
                user_name = await asyncio.to_thread(
                    self.fetch_zerodha_user_name, api_key, access_token
                )
                
                # Initialize KiteConnect
                if not REAL_KITE_AVAILABLE:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'KiteConnect library not available'
                    }))
                    return
                
                real_kite = KiteConnect(api_key=api_key)
                real_kite.set_access_token(access_token)
                
                # Use Hybrid wrapper if simulation mode
                if is_simulation:
                    django_user = await self.get_django_user(api_key)
                    trade_session = None
                    if django_user and investable_amount:
                        trade_session = await self.create_trade_session(django_user, investable_amount)
                    
                    kite = HybridKiteConnect(real_kite, user_state=None)
                    if trade_session:
                        kite.trade_session = trade_session
                    logger.info(f"🎮 Using Hybrid Simulator for {user_name}")
                else:
                    kite = real_kite
                    logger.info(f"✅ Using Real KiteConnect for {user_name}")
                
                self.users[user_id] = {
                    'kite': kite,
                    'api_key': api_key,
                    'access_token': access_token,
                    'user_name': user_name,
                    'is_simulation': is_simulation
                }
            
            user_data = self.users[user_id]
            kite = user_data['kite']
            
            # Place order
            await self.send(text_data=json.dumps({
                'type': 'order_status',
                'status': 'processing',
                'message': f'Placing {transaction_type} order for {tradingsymbol}...'
            }))
            
            # Execute order
            order_result = await self.place_order(
                kite=kite,
                variety=variety,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                order_type=order_type,
                quantity=int(quantity),
                product=product,
                validity=validity,
                price=float(price) if price else None,
                trigger_price=float(trigger_price) if trigger_price else None,
                tag=tag,
                user_name=user_data['user_name'],
                is_simulation=user_data['is_simulation'],
                total_amount=total_amount,
                investable_amount=investable_amount
            )
            
            # Update position if order was successful
            if order_result.get('status') == 'success' and order_result.get('average_price'):
                connection_id = id(self)
                # Determine option type from symbol (CE or PE)
                option_type = 'CE' if 'CE' in tradingsymbol.upper() else 'PE' if 'PE' in tradingsymbol.upper() else None
                
                if option_type and connection_id in self.positions:
                    current_pos = self.positions[connection_id][option_type]
                    if transaction_type == 'BUY':
                        # Update bought_at as weighted average if position exists
                        if current_pos['bought_at'] and current_pos['quantity'] > 0:
                            total_cost = (current_pos['bought_at'] * current_pos['quantity']) + (order_result['average_price'] * int(quantity))
                            total_quantity = current_pos['quantity'] + int(quantity)
                            current_pos['bought_at'] = total_cost / total_quantity
                            current_pos['quantity'] = total_quantity
                        else:
                            current_pos['bought_at'] = order_result['average_price']
                            current_pos['quantity'] = int(quantity)
                    elif transaction_type == 'SELL':
                        # Reduce position
                        if current_pos['quantity'] > 0:
                            current_pos['quantity'] = max(0, current_pos['quantity'] - int(quantity))
                            if current_pos['quantity'] == 0:
                                current_pos['bought_at'] = None
            
            # Send result
            await self.send(text_data=json.dumps(order_result))
            
        except Exception as e:
            logger.error(f"❌ Error handling order message: {e}")
            logger.error(traceback.format_exc())
            await self.send(text_data=json.dumps({
                'type': 'error',
                'status': 'failed',
                'message': f'Order placement failed: {str(e)}'
            }))

    async def place_order(self, kite, variety, exchange, tradingsymbol, transaction_type,
                         order_type, quantity, product, validity, price=None, trigger_price=None,
                         tag=None, user_name="Unknown", is_simulation=False, total_amount=0,
                         investable_amount=0):
        """Place order using KiteConnect or Hybrid wrapper"""
        try:
            # Prepare order parameters
            order_params = {
                'variety': variety,
                'exchange': exchange,
                'tradingsymbol': tradingsymbol,
                'transaction_type': transaction_type,
                'quantity': quantity,
                'order_type': order_type,
                'product': product,
                'validity': validity,
                'tag': tag
            }
            
            # Add optional parameters
            if price and order_type in ['LIMIT', 'SL']:
                order_params['price'] = price
            if trigger_price and order_type in ['SL', 'SL-M']:
                order_params['trigger_price'] = trigger_price
            
            # Place order (run in thread to avoid blocking event loop)
            order_id = await asyncio.to_thread(kite.place_order, **order_params)
            
            logger.info(f"📤 Order placed - ID: {order_id}, Symbol: {tradingsymbol}, Type: {transaction_type}")
            
            # Get order details (run in thread to avoid blocking event loop)
            order_details = await asyncio.to_thread(kite.order_history, order_id)
            if order_details:
                final_order = order_details[-1]
                order_status = final_order.get('status', 'UNKNOWN')
                average_price = final_order.get('average_price', 0.0)
                
                # Log order
                log_message = (
                    f"✅ ORDER PLACED | User: {user_name} | Symbol: {tradingsymbol} | "
                    f"Type: {transaction_type} | Qty: {quantity} | Price: ₹{average_price} | "
                    f"Status: {order_status} | Total: {total_amount} | Investable: {investable_amount} | "
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                write_log_to_txt2(log_message)
                
                return {
                    'type': 'order_result',
                    'status': 'success' if order_status.lower() == 'complete' else 'pending',
                    'order_id': order_id,
                    'tradingsymbol': tradingsymbol,
                    'transaction_type': transaction_type,
                    'quantity': quantity,
                    'average_price': average_price,
                    'order_status': order_status,
                    'is_simulation': is_simulation,
                    'message': f'Order placed successfully. Status: {order_status}'
                }
            else:
                return {
                    'type': 'order_result',
                    'status': 'pending',
                    'order_id': order_id,
                    'tradingsymbol': tradingsymbol,
                    'message': 'Order placed, awaiting confirmation'
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Order placement failed: {error_msg}")
            logger.error(traceback.format_exc())
            
            # Log error
            log_message = (
                f"❌ ORDER FAILED | User: {user_name} | Symbol: {tradingsymbol} | "
                f"Type: {transaction_type} | Error: {error_msg} | "
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            write_log_to_txt2(log_message)
            
            return {
                'type': 'order_result',
                'status': 'failed',
                'message': f'Order placement failed: {error_msg}',
                'error': error_msg
            }

    async def handle_subscribe_market_data(self, payload):
        """Handle market data subscription request"""
        try:
            api_key = payload.get('api_key')
            access_token = payload.get('access_token')
            ce_symbol = payload.get('ce_symbol')  # Call option symbol
            pe_symbol = payload.get('pe_symbol')  # Put option symbol
            instrument_name = payload.get('instrument_name')  # Underlying index name (NIFTY, BANKNIFTY, etc.)
            
            if not all([api_key, access_token]):
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Missing required fields: api_key, access_token'
                }))
                return
            
            connection_id = id(self)
            
            # Initialize KiteConnect to get instrument tokens
            if not REAL_KITE_AVAILABLE:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'KiteConnect library not available'
                }))
                return
            
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            
            # Get instrument tokens for CE and PE
            tokens_to_subscribe = []
            symbol_to_token = {}
            index_token = None
            
            # Get index token if instrument name is provided
            if instrument_name:
                index_token = await asyncio.to_thread(self.get_index_token, kite, instrument_name)
                if index_token:
                    tokens_to_subscribe.append(index_token)
                    symbol_to_token[f'INDEX_{instrument_name}'] = index_token
                    logger.info(f"✅ Index Token for {instrument_name}: {index_token}")
                else:
                    logger.warning(f"⚠️ Could not find index token for: {instrument_name}")
            
            if ce_symbol:
                ce_token = await asyncio.to_thread(self.get_instrument_token, kite, ce_symbol)
                if ce_token:
                    tokens_to_subscribe.append(ce_token)
                    symbol_to_token[ce_symbol] = ce_token
                    logger.info(f"✅ CE Symbol: {ce_symbol}, Token: {ce_token}")
                else:
                    logger.warning(f"⚠️ Could not find instrument token for CE symbol: {ce_symbol}")
            
            if pe_symbol:
                pe_token = await asyncio.to_thread(self.get_instrument_token, kite, pe_symbol)
                if pe_token:
                    tokens_to_subscribe.append(pe_token)
                    symbol_to_token[pe_symbol] = pe_token
                    logger.info(f"✅ PE Symbol: {pe_symbol}, Token: {pe_token}")
                else:
                    logger.warning(f"⚠️ Could not find instrument token for PE symbol: {pe_symbol}")
            
            if not tokens_to_subscribe:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'No valid symbols provided for subscription'
                }))
                return
            
            # Store subscription data
            self.market_data_subscriptions[connection_id] = {
                'api_key': api_key,
                'access_token': access_token,
                'ce_symbol': ce_symbol,
                'pe_symbol': pe_symbol,
                'instrument_name': instrument_name,
                'index_token': index_token,
                'symbol_to_token': symbol_to_token,
                'tokens': tokens_to_subscribe
            }
            
            # Initialize positions tracking
            if connection_id not in self.positions:
                self.positions[connection_id] = {
                    'CE': {'bought_at': None, 'quantity': 0},
                    'PE': {'bought_at': None, 'quantity': 0}
                }
            
            # Fetch existing positions from Zerodha to sync PnL
            try:
                positions_response = await asyncio.to_thread(kite.positions)
                net_positions = positions_response.get('net', [])
                
                logger.info(f"📊 Fetching initial positions for connection {connection_id}")
                
                for pos in net_positions:
                    tsym = pos.get('tradingsymbol')
                    qty = pos.get('quantity', 0)
                    avg_price = pos.get('average_price', 0)
                    
                    # Check if this position matches our subscribed symbols
                    if tsym == ce_symbol:
                        # It's a CE position
                        self.positions[connection_id]['CE']['quantity'] = qty
                        self.positions[connection_id]['CE']['bought_at'] = avg_price
                        logger.info(f"✅ Found existing CE position: {qty} @ {avg_price}")
                    
                    elif tsym == pe_symbol:
                        # It's a PE position
                        self.positions[connection_id]['PE']['quantity'] = qty
                        self.positions[connection_id]['PE']['bought_at'] = avg_price
                        logger.info(f"✅ Found existing PE position: {qty} @ {avg_price}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to fetch initial positions: {e}")
                # Don't fail the whole subscription, just log error
            
            # Start KiteTicker streaming
            await self.start_market_data_stream(connection_id, api_key, access_token, tokens_to_subscribe, symbol_to_token)
            
        except Exception as e:
            logger.error(f"❌ Error handling market data subscription: {e}")
            logger.error(traceback.format_exc())
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Market data subscription failed: {str(e)}'
            }))

    def get_instrument_token(self, kite, trading_symbol):
        """Get instrument token for a trading symbol"""
        try:
            instruments = kite.instruments("NFO")
            clean_symbol = trading_symbol.replace(" ", "").upper()
            
            for instrument in instruments:
                if instrument['tradingsymbol'].replace(" ", "").upper() == clean_symbol:
                    return instrument['instrument_token']
            
            logger.error(f"❌ No instrument found for symbol: {trading_symbol}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching instrument token: {e}")
            return None

    def get_index_token(self, kite, instrument_name):
        """Get index token for underlying index (NIFTY, BANKNIFTY, etc.)"""
        try:
            # Map instrument names to their index trading symbols
            index_map = {
                "NIFTY": "NIFTY 50",
                "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FIN SERVICE",
                "MIDCPNIFTY": "NIFTY MID SELECT",
                "SENSEX": "SENSEX",
                "BANKEX": "BANKEX"
            }
            
            # Determine exchange based on instrument
            nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            bse_indices = ["SENSEX", "BANKEX"]
            
            if instrument_name in nse_indices:
                exchange = "NSE"
            elif instrument_name in bse_indices:
                exchange = "BSE"
            else:
                logger.warning(f"⚠️ Unknown instrument: {instrument_name}, defaulting to NSE")
                exchange = "NSE"
            
            instruments = kite.instruments(exchange)
            index_tradingsymbol = index_map.get(instrument_name)
            
            if not index_tradingsymbol:
                logger.error(f"❌ No mapping found for instrument: {instrument_name}")
                return None
            
            for instrument in instruments:
                if instrument['tradingsymbol'] == index_tradingsymbol:
                    logger.info(f"✅ Found {instrument_name} index token: {instrument['instrument_token']}")
                    return instrument['instrument_token']
            
            logger.error(f"❌ No index token found for: {instrument_name} ({index_tradingsymbol})")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching index token: {e}")
            return None

    async def start_market_data_stream(self, connection_id, api_key, access_token, tokens, symbol_to_token):
        """Start KiteTicker streaming for market data"""
        try:
            if not REAL_KITE_AVAILABLE or KiteTicker is None:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'KiteTicker not available'
                }))
                return
            
            # Close existing KiteTicker if any
            if connection_id in self.kws_instances:
                try:
                    old_kws = self.kws_instances[connection_id]
                    old_kws.close()
                    logger.info(f"🔄 Closed existing KiteTicker for connection {connection_id}")
                    # Wait a bit for cleanup
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"⚠️ Error closing existing KiteTicker: {e}")
                finally:
                    if connection_id in self.kws_instances:
                        del self.kws_instances[connection_id]
            
            kws = KiteTicker(api_key, access_token)
            self.kws_instances[connection_id] = kws
            
            def safe_send_json(payload):
                if not self.loop:
                    logger.warning("⚠️ No event loop available for sending message")
                    return
                
                try:
                    # Check if connection is still open by checking if we can get the channel layer
                    fut = asyncio.run_coroutine_threadsafe(
                        self.send(text_data=json.dumps(payload)), self.loop
                    )
                    fut.result(timeout=3)
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Timeout sending JSON payload: {payload.get('type', 'unknown')}")
                except RuntimeError as e:
                    if "Event loop is closed" in str(e):
                        logger.warning("⚠️ Event loop closed, cannot send message")
                    else:
                        logger.error(f"❌ Runtime error sending JSON payload: {e}")
                except Exception as e:
                    logger.error(f"❌ Failed to send JSON payload: {e}", exc_info=True)
                    logger.error(f"Payload was: {payload}")
            
            def on_ticks(ws, ticks):
                try:
                    if ticks and len(ticks) > 0:
                        logger.debug(f"📊 Received {len(ticks)} ticks for connection {connection_id}")
                        asyncio.run_coroutine_threadsafe(
                            self.process_market_ticks(connection_id, ticks, symbol_to_token), 
                            self.loop
                        )
                    else:
                        logger.debug("⚠️ Received empty ticks array")
                except Exception as e:
                    logger.error(f"❌ Error scheduling process_market_ticks: {e}", exc_info=True)
            
            def on_connect(ws, response):
                logger.info(f"✅ Connected to Zerodha WebSocket for market data")
                try:
                    ws.subscribe(tokens)
                    ws.set_mode(ws.MODE_FULL, tokens)
                    logger.info(f"✅ Subscribed to {len(tokens)} instruments")
                    safe_send_json({
                        'type': 'market_data_subscribed',
                        'message': f'Subscribed to {len(tokens)} instruments',
                        'tokens': tokens
                    })
                except Exception as e:
                    logger.error(f"❌ Subscribe failure: {e}")
                    safe_send_json({
                        'type': 'error',
                        'message': f'Subscribe failed: {str(e)}'
                    })
            
            def on_error(ws, code, reason):
                msg = f"❌ WebSocket Error: {code} - {reason}"
                logger.error(msg)
                safe_send_json({
                    'type': 'error',
                    'message': msg
                })
            
            def on_close(ws, code, reason):
                msg = f"🔌 KiteTicker WebSocket Closed: {code} - {reason}"
                logger.warning(msg)
                # Don't try to send message on close as the connection might already be closed
                # The frontend will detect the disconnection through other means
            
            def on_reconnect(ws, attempts_count):
                msg = f"🔁 Reconnecting to WebSocket, attempt {attempts_count}"
                logger.info(msg)
                safe_send_json({
                    'type': 'info',
                    'message': msg
                })
            
            kws.on_ticks = on_ticks
            kws.on_connect = on_connect
            kws.on_error = on_error
            kws.on_close = on_close
            kws.on_reconnect = on_reconnect
            
            def run_websocket_thread():
                try:
                    kws.connect(threaded=True)
                except Exception as e:
                    logger.error(f"❌ WebSocket thread connect exception: {e}")
                    try:
                        kws.connect(threaded=False)
                    except Exception as e2:
                        logger.error(f"❌ Fallback connect failed: {e2}")
                        safe_send_json({
                            'type': 'error',
                            'message': f'WS connect failed: {str(e)} / {str(e2)}'
                        })
            
            ws_thread = threading.Thread(target=run_websocket_thread, name=f"KiteTickerThread-{connection_id}")
            ws_thread.daemon = True
            ws_thread.start()
            
        except Exception as e:
            logger.error(f"❌ Error starting market data stream: {e}")
            logger.error(traceback.format_exc())
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to start market data stream: {str(e)}'
            }))

    async def process_market_ticks(self, connection_id, ticks, symbol_to_token):
        """Process market data ticks and send updates to frontend"""
        try:
            if not ticks or len(ticks) == 0:
                return
                
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            token_to_symbol = {v: k for k, v in symbol_to_token.items()}
            
            positions = self.positions.get(connection_id, {
                'CE': {'bought_at': None, 'quantity': 0},
                'PE': {'bought_at': None, 'quantity': 0}
            })
            
            # Get subscription data to access instrument_name
            subscription_data = self.market_data_subscriptions.get(connection_id, {})
            instrument_name = subscription_data.get('instrument_name')
            
            # Rate limiting: only process ticks every 200ms to avoid overwhelming the connection
            current_time = time.time()
            if not hasattr(self, '_last_tick_time'):
                self._last_tick_time = {}
            if connection_id not in self._last_tick_time:
                self._last_tick_time[connection_id] = 0
            
            if current_time - self._last_tick_time[connection_id] < 0.2:  # 200ms throttle
                return
            
            self._last_tick_time[connection_id] = current_time
            logger.debug(f"📊 Processing {len(ticks)} ticks for connection {connection_id}. Time since last: {current_time - (self._last_tick_time.get(connection_id, 0) if connection_id in self._last_tick_time else 0):.3f}s")
            
            # Start timer for processing latency
            proc_start_time = time.time()

            
            for tick in ticks:
                instrument_token = tick.get('instrument_token')
                ltp = tick.get('last_price', 0)
                volume = tick.get('volume', 0)
                oi = tick.get('oi', 0)
                change = tick.get('change', 0)
                
                if instrument_token in token_to_symbol:
                    symbol = token_to_symbol[instrument_token]
                    
                    # Check if this is an index token
                    if symbol.startswith('INDEX_'):
                        # This is an index update
                        index_name = symbol.replace('INDEX_', '')
                        try:
                            if not self.keep_running:
                                logger.warning("⚠️ Connection closed, skipping index update")
                                break
                                
                            message_data = {
                                'type': 'live_index_update',
                                'instrument_name': index_name,
                                'spot_price': float(ltp) if ltp else 0.0,
                                'volume': int(volume) if volume else 0,
                                'oi': int(oi) if oi else 0,
                                'change': float(change) if change else 0.0,
                                'timestamp': timestamp
                            }
                            
                            await self.send(text_data=json.dumps(message_data))
                            logger.debug(f"📊 Sent index update: {index_name} = {ltp}")
                        except Exception as send_error:
                            error_msg = str(send_error)
                            if "WebSocket is closed" in error_msg or "Connection closed" in error_msg:
                                logger.warning(f"⚠️ WebSocket closed, stopping tick processing")
                                self.keep_running = False
                                break
                            else:
                                logger.error(f"❌ Error sending index update: {send_error}", exc_info=True)
                            continue
                    else:
                        # This is an option update (CE or PE)
                        # Determine option type from symbol (CE or PE)
                        option_type = 'CE' if 'CE' in symbol.upper() else 'PE' if 'PE' in symbol.upper() else None
                        
                        if not option_type:
                            continue
                        
                        # Calculate PNL if position exists
                        pnl = None
                        pnl_percent = None
                        if positions[option_type]['bought_at'] and positions[option_type]['quantity'] > 0:
                            bought_at = positions[option_type]['bought_at']
                            quantity = positions[option_type]['quantity']
                            pnl = (ltp - bought_at) * quantity
                            pnl_percent = ((ltp - bought_at) / bought_at * 100) if bought_at > 0 else 0
                        
                        # Send live LTP update
                        try:
                            # Check if connection is still active
                            if not self.keep_running:
                                logger.warning("⚠️ Connection closed, skipping LTP update")
                                break
                                
                            message_data = {
                                'type': 'live_ltp',
                                'option_type': option_type,
                                'symbol': symbol,
                                'ltp': float(ltp) if ltp else 0.0,
                                'bought_at': float(positions[option_type]['bought_at']) if positions[option_type]['bought_at'] else None,
                                'quantity': int(positions[option_type]['quantity']) if positions[option_type]['quantity'] else 0,
                                'pnl': float(pnl) if pnl is not None else None,
                                'pnl_percent': float(pnl_percent) if pnl_percent is not None else None,
                                'timestamp': timestamp
                            }
                            
                            await self.send(text_data=json.dumps(message_data))
                            logger.debug(f"📊 Sent LTP update: {option_type} = {ltp}")
                        except Exception as send_error:
                            error_msg = str(send_error)
                            if "WebSocket is closed" in error_msg or "Connection closed" in error_msg:
                                logger.warning(f"⚠️ WebSocket closed, stopping tick processing")
                                self.keep_running = False
                                break
                            else:
                                logger.error(f"❌ Error sending LTP update: {send_error}", exc_info=True)
                            # Don't break the loop, continue processing other ticks
                            continue
                    
                    
            proc_duration = time.time() - proc_start_time
            if proc_duration > 0.1: # Log if processing takes more than 100ms
                logger.warning(f"⚠️ Slow tick processing: {proc_duration:.3f}s for {len(ticks)} ticks")
            else:
                logger.debug(f"✅ Tick processing completed in {proc_duration:.3f}s")

        except Exception as e:
            logger.error(f"❌ Error processing market ticks: {e}")
            logger.error(traceback.format_exc())

    def update_position(self, connection_id, option_type, bought_at, quantity):
        """Update position when order is placed"""
        if connection_id not in self.positions:
            self.positions[connection_id] = {
                'CE': {'bought_at': None, 'quantity': 0},
                'PE': {'bought_at': None, 'quantity': 0}
            }
        
        # For now, we'll update this when order is placed successfully
        # This will be called from handle_order_message when order succeeds
        pass
