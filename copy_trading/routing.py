from django.urls import re_path
from . import consumers,consumer2 , consumer3 , zerodhaconsumer , zerodha2 , optionchain , zerodhaconsumer2, manual_zerodha_consumer

websocket_urlpatterns = [
    re_path(r'ws/option-data/$', consumers.LiveOptionDataConsumer.as_asgi()),
    re_path(r'ws/option-datas/$', consumer2.LiveOptionDataConsumer2.as_asgi()),
    re_path(r'ws/manualtrade/$', consumer3.LiveOptionDataConsumer3.as_asgi()),
    re_path(r'ws/zerodha/$', zerodhaconsumer.LiveOptionDataConsumerZerodha.as_asgi()),
    re_path(r'ws/zerodhas/$', zerodha2.MarketDataConsumer.as_asgi()),
    re_path(r'ws/optiondata/$', optionchain.LiveOptionData.as_asgi()),
    re_path(r'ws/manual_zerodha/$', zerodhaconsumer2.LiveOptionDataConsumerZerodha.as_asgi()),
    re_path(r'ws/manual-zerodha-trade/$', manual_zerodha_consumer.ManualZerodhaTradeConsumer.as_asgi()),

]