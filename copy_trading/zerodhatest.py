import logging
from kiteconnect import KiteConnect

# Setup logging
logging.basicConfig(level=logging.DEBUG)

# Initialize KiteConnect with your API key
kite = KiteConnect(api_key="e74wrp5cse4shibt")

# If you already have access_token, just set it directly
kite.set_access_token("lDyil7AfF5REmitgtDWzAeqKGPlWfUAI")

# Example: Place an order
try:
    order_id = kite.place_order(
        tradingsymbol="NIFTY25O2022850CE",
        exchange=kite.EXCHANGE_NFO,
        transaction_type=kite.TRANSACTION_TYPE_BUY,
        quantity=1,
        variety=kite.VARIETY_REGULAR,  
        order_type=kite.ORDER_TYPE_MARKET,
        product=kite.PRODUCT_NRML,
        validity=kite.VALIDITY_DAY
    )

    logging.info(f"✅ Order placed successfully. ID: {order_id}")

except Exception as e:
    logging.error(f"❌ Order placement failed: {e}")

# Fetch all orders
orders = kite.orders()
print("All Orders:", orders)
