import json
import logging
import threading
from channels.generic.websocket import AsyncWebsocketConsumer
from kiteconnect import KiteTicker
from asgiref.sync import async_to_sync

logging.basicConfig(level=logging.INFO)

API_KEY = "a44a8d2b1l25cwq4"
ACCESS_TOKEN = "Xh2z6iHPSs2Oh8cTvDND7jjNHiMhFk1s"
TOKENS = [738561]  # RELIANCE example

# ----------------- KiteTicker Setup -----------------
def start_kite_stream():
    """
    This function runs KiteTicker in a separate thread.
    It should only be called once per server start!
    """
    kws = KiteTicker(API_KEY, ACCESS_TOKEN)

    def on_ticks(ws, ticks):
        if ticks:
            logging.info(f"📈 Tick received: {ticks[0]}")
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "market_data_group",
                {
                    "type": "send_market_data",
                    "data": ticks[0],  # broadcast first tick
                },
            )

    def on_connect(ws, response):
        logging.info("✅ Connected to Kite WebSocket")
        ws.subscribe(TOKENS)
        ws.set_mode(ws.MODE_FULL, TOKENS)

    def on_close(ws, code, reason):
        logging.warning(f"❌ Connection closed: {code} - {reason}")

    def on_error(ws, code, reason):
        logging.error(f"⚠️ Error: {code} - {reason}")

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.on_error = on_error

    # Run KiteTicker in its own thread safely
    kws.connect(threaded=True)

# ----------------- WebSocket Consumer -----------------
class MarketDataConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer that streams Zerodha market data"""

    async def connect(self):
        # Add client to group
        await self.channel_layer.group_add("market_data_group", self.channel_name)
        await self.accept()
        logging.info("✅ Client connected to WebSocket")

        # Start KiteTicker only once
        if not hasattr(threading, "_kite_started"):
            threading.Thread(target=start_kite_stream, daemon=True).start()
            threading._kite_started = True
            logging.info("🚀 KiteTicker background thread started")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("market_data_group", self.channel_name)
        logging.info("❌ Client disconnected")

    async def receive(self, text_data):
        # Optional: handle messages from client
        data = json.loads(text_data)
        logging.info(f"📩 Message from client: {data}")

    async def send_market_data(self, event):
        """Send tick data to WebSocket client"""
        data = event["data"]
        await self.send(text_data=json.dumps({"tick": data}))
