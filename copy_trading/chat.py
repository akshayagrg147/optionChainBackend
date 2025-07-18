import asyncio
import json
import ssl
import time
import requests
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from google.protobuf.json_format import MessageToDict
from . import MarketDataFeedV3_pb2 as pb
import os
import csv
import logging

logger = logging.getLogger(__name__)

class TradeState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.order_placedCE = False
        self.order_placedPE = False
        self.sell_order_placed = False
        self.ltp_at_order = None
        self.locked_ltp = None
        self.previous_ltp = None
        self.toggle = True
        self.buy_token = None
        self.reverse_token = None

    def should_buy_ce(self, spot_price, target_ce):
        return not self.order_placedCE and spot_price is not None and spot_price >= target_ce

    def should_buy_pe(self, spot_price, target_pe):
        return not self.order_placedPE and spot_price is not None and spot_price <= target_pe

    def should_sell(self, current_ltp):
        return not self.sell_order_placed and self.ltp_at_order is not None and current_ltp < self.locked_ltp

    def update_trailing_sl(self, current_ltp, step):
        step_size = round(self.ltp_at_order * step / 100, 2)
        if self.locked_ltp is None:
            self.locked_ltp = round(self.ltp_at_order - step_size, 2)
            self.previous_ltp = self.ltp_at_order
        if current_ltp > self.previous_ltp:
            while current_ltp >= self.locked_ltp + step_size:
                self.locked_ltp += step_size
            if self.locked_ltp == self.ltp_at_order:
                self.locked_ltp -= step_size
        self.previous_ltp = current_ltp
        return step_size

    def calculate_pnl_percent(self, current_ltp):
        if not self.ltp_at_order:
            return 0.0
        return round(((current_ltp - self.ltp_at_order) / self.ltp_at_order) * 100, 2)


class LiveOptionDataConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.keep_running = True
        self.state = TradeState()
        self.latest_spot_price = None

    async def disconnect(self, close_code):
        self.keep_running = False

    async def receive(self, text_data):
        payload = json.loads(text_data)
        self.target_ce = float(payload.get('target_market_price_CE', 0))
        self.target_pe = float(payload.get('target_market_price_PE', 0))
        self.step = float(payload.get('step', 0.5))
        self.expected_profit = float(payload.get('profit_percent', 0.5))
        self.access_token = payload.get('access_token')
        self.buy_token = payload.get('trading_symbol')
        self.reverse_token = payload.get('trading_symbol_2')

        asyncio.create_task(self.stream_data())

    async def stream_data(self):
        while self.keep_running:
            try:
                current_ltp = self.get_ltp(self.buy_token)
                self.latest_spot_price = current_ltp

                if self.state.should_buy_ce(current_ltp, self.target_ce):
                    await self.handle_buy('CE', current_ltp, self.buy_token, self.reverse_token)
                elif self.state.should_buy_pe(current_ltp, self.target_pe):
                    await self.handle_buy('PE', current_ltp, self.buy_token, self.reverse_token)

                if (self.state.order_placedCE or self.state.order_placedPE):
                    self.state.update_trailing_sl(current_ltp, self.step)
                    if self.state.should_sell(current_ltp):
                        await self.handle_sell(current_ltp)

                await asyncio.sleep(1)
            except Exception as e:
                await self.send(json.dumps({'error': str(e)}))
                logger.error("Error in stream_data", exc_info=True)

    async def handle_buy(self, option_type, ltp, buy_token, reverse_token):
        self.state.ltp_at_order = ltp
        self.state.buy_token = buy_token
        self.state.reverse_token = reverse_token
        if option_type == 'CE':
            self.state.order_placedCE = True
        else:
            self.state.order_placedPE = True
        await self.send(json.dumps({
            'message': f'{option_type} Buy Order Placed',
            'ltp': ltp,
            'timestamp': time.strftime('%H:%M:%S')
        }))

    async def handle_sell(self, current_ltp):
        self.state.sell_order_placed = True
        pnl_percent = self.state.calculate_pnl_percent(current_ltp)
        await self.send(json.dumps({
            'message': 'Sell Executed',
            'ltp': current_ltp,
            'pnl_percent': pnl_percent
        }))

        if self.state.toggle and pnl_percent < self.expected_profit:
            await self.execute_reverse_trade()

    async def execute_reverse_trade(self):
        self.state.toggle = False
        await self.send(json.dumps({
            'info': f'Reverse Trade Initiated on {self.state.reverse_token}'
        }))
        self.state.reset()

    def get_ltp(self, token):
        # Replace with actual API call if needed
        return float(requests.get(
            "https://api.upstox.com/v2/market-quote/ltp",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params={"symbol": token}
        ).json()['data'][token]['last_price'])
