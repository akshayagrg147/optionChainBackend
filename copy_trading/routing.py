from django.urls import re_path
from . import consumers,consumer2 

websocket_urlpatterns = [
    re_path(r'ws/option-data/$', consumers.LiveOptionDataConsumer.as_asgi()),
    re_path(r'ws/option-datas/$', consumer2.LiveOptionData.as_asgi()),
]