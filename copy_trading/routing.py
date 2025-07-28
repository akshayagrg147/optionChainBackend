from django.urls import re_path
from . import consumers,consumer2 , consumer3

websocket_urlpatterns = [
    re_path(r'ws/option-data/$', consumers.LiveOptionDataConsumer.as_asgi()),
    re_path(r'ws/option-datas/$', consumer2.LiveOptionDataConsumer2.as_asgi()),
    re_path(r'ws/manualtrade/$', consumer3.LiveOptionDataConsumer3.as_asgi()),
]