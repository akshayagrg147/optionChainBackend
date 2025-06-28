import json
import asyncio
import contextlib
from channels.generic.websocket import AsyncWebsocketConsumer
from redis import asyncio as aioredis

class OptionDataConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        print("✅ WebSocket connection accepted")

        self.redis = await aioredis.from_url("redis://localhost")
        self.pubsub = self.redis.pubsub()

        await self.pubsub.subscribe("live_option_data")
        print("Subscribed to Redis channel: live_option_data")

        # Start listening for Redis messages
        self.listen_task = asyncio.create_task(self.listen_to_redis())

    async def listen_to_redis(self):
        try:
            while True:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    print("📩 Message from Redis:", message["data"])
                    await self.send(text_data=message["data"].decode())
                await asyncio.sleep(0.01)  
        except asyncio.CancelledError:
            print("🛑 listen_to_redis task was cancelled")

    async def disconnect(self, close_code):
        print(f"WebSocket disconnected (code {close_code})")

        await self.pubsub.unsubscribe("live_option_data")
        if hasattr(self, 'listen_task'):
            self.listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.listen_task

        await self.redis.close()
        print("🔒 Redis connection closed")
