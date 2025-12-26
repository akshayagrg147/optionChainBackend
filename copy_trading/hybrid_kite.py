from datetime import datetime
import uuid
import logging
import threading
from .models import TradeSession, TradeTransaction
try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = object  # Fallback for environments without kiteconnect

logger = logging.getLogger(__name__)

class HybridKiteConnect:
    """
    A wrapper around the real KiteConnect class.
    - READ operations (quote, instruments, ltp) -> Delegated to REAL KiteConnect.
    - WRITE operations (place_order) -> Intercepted and executed locally (Paper Trading).
    """

    # Mimic KiteConnect constants
    EXCHANGE_NSE = "NSE"
    EXCHANGE_BSE = "BSE"
    EXCHANGE_NFO = "NFO"
    EXCHANGE_BFO = "BFO"
    
    PRODUCT_MIS = "MIS"
    PRODUCT_CNC = "CNC"
    PRODUCT_NRML = "NRML"
    
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_LIMIT = "LIMIT"
    ORDER_TYPE_SL = "SL"
    ORDER_TYPE_SL_M = "SL-M"
    
    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"
    
    VALIDITY_DAY = "DAY"
    VALIDITY_IOC = "IOC"
    
    VARIETY_REGULAR = "regular"

    def __init__(self, real_kite_instance, user_state=None):
        self.real_kite = real_kite_instance
        self.user_state = user_state
        self.api_key = real_kite_instance.api_key
        self.access_token = getattr(real_kite_instance, "access_token", None)
        
        # Session to track DB persistence
        self.trade_session = None
        
        # In-memory order storage for the session
        self.local_orders = []
        self.positions = {}  # symbol -> qty

    def set_access_token(self, access_token):
        self.access_token = access_token
        if self.real_kite:
            self.real_kite.set_access_token(access_token)

    # --- DELEGATED READ METHODS (REAL DATA) ---

    def instruments(self, exchange=None):
        """Fetch real instruments from Zerodha"""
        return self.real_kite.instruments(exchange)

    def quote(self, instruments):
        """Fetch real quotes"""
        return self.real_kite.quote(instruments)

    def ltp(self, instruments):
        """Fetch real LTP"""
        return self.real_kite.ltp(instruments)
        
    def profile(self):
        """Fetch real profile"""
        return self.real_kite.profile()

    # --- INTERCEPTED WRITE METHODS (SIMULATED EXECUTION) ---

    def place_order(self, variety, exchange, tradingsymbol, transaction_type, quantity, 
                    order_type="MARKET", price=0.0, product="NRML", validity="DAY", **kwargs):
        """
        Simulate order placement.
        1. Get current real price (LTP) for realism.
        2. Create a local order record.
        3. Save to DB.
        """
        print(f"🎮 [PAPER TRADE] Intercepting {transaction_type} order for {tradingsymbol}")
        
        # 1. Fetch real price for execution
        try:
            instrument_token = f"{exchange}:{tradingsymbol}"
            quote = self.real_kite.quote([instrument_token])
            if instrument_token in quote:
                last_price = quote[instrument_token]['last_price']
            else:
                last_price = price if price > 0 else 100.0  # Fallback if quote fails
        except Exception as e:
            print(f"⚠️ Could not fetch live price for simulation: {e}")
            last_price = price if price > 0 else 100.0

        # 2. Generate Order ID
        order_id = f"HYBRID_{uuid.uuid4().hex[:8].upper()}"
        
        # 3. Create Order Object
        timestamp = datetime.now()
        
        order_data = {
            "order_id": order_id,
            "parent_order_id": None,
            "exchange_order_id": None,
            "placed_by": self.user_state.user_id if self.user_state else "SIM_USER",
            "variety": variety,
            "status": "COMPLETE",  # Auto-fill for simulation
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "instrument_token": None,
            "transaction_type": transaction_type,
            "order_type": order_type,
            "product": product,
            "validity": validity,
            "price": 0,
            "quantity": quantity,
            "trigger_price": 0,
            "average_price": last_price,
            "pending_quantity": 0,
            "filled_quantity": quantity,
            "disclosed_quantity": 0,
            "market_protection": 0,
            "order_timestamp": timestamp,
            "exchange_timestamp": timestamp,
            "status_message": "Simulated Order Filled"
        }
        
        self.local_orders.append(order_data)
        
        self.local_orders.append(order_data)
        
        # 4. Save to DB
        # 4. Save to DB (Run in separate thread to avoid async context issues)
        def _save_transaction_sync():
            try:
                if self.trade_session:
                    print(f"💾 Saving transaction to DB for Session: {self.trade_session.session_id}")
                    TradeTransaction.objects.create(
                        session=self.trade_session,
                        order_id=order_id,
                        trading_symbol=tradingsymbol,
                        transaction_type=transaction_type,
                        quantity=quantity,
                        price=last_price,
                        product=product,
                        status="COMPLETE",
                        status_message="Simulated Order Filled"
                    )
                    print(f"✅ Transaction saved successfully for Order {order_id}")
            except Exception as e:
                print(f"❌ Failed to save transaction to DB: {e}")

        # specific thread for DB operation
        db_thread = threading.Thread(target=_save_transaction_sync)
        db_thread.start()
        db_thread.join() # Wait for save to complete to ensure data integrity before proceeding
        
        print(f"✅ [PAPER TRADE] Order {order_id} executed @ {last_price}")
        return order_id

    def orders(self):
        """Return local simulated orders"""
        return self.local_orders

    def order_history(self, order_id):
        """Return history for a specific local order"""
        for order in self.local_orders:
            if order['order_id'] == order_id:
                return [order]
        return []

    # --- POSITIONS (Optional / Local Tracking) ---
    def positions(self):
        """Return net/day positions based on local orders"""
        # Simplification: Just return empty or calculate from orders if needed
        return {"net": [], "day": []}
