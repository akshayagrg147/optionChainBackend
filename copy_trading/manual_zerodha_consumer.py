import os
import json
import asyncio
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
import logging
import traceback
from typing import Dict, Optional, Any
from channels.db import database_sync_to_async
import uuid

# Conditional imports for simulation mode
try:
    from kiteconnect import KiteConnect
    REAL_KITE_AVAILABLE = True
except ImportError:
    REAL_KITE_AVAILABLE = False
    KiteConnect = None

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
