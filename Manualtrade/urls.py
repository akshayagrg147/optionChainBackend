from django.urls import path
from .views import  *

urlpatterns = [ 
            path('gettoken/',GetTradingSymbolsAndToken.as_view()),
            path('api/place-upstox-order-buy/', PlaceUpstoxBuyOrderAPIView.as_view(), name='place-upstox-order'),
            path('api/place-upstox-order-sell/', PlaceUpstoxSellOrderAPIView.as_view(), name='place-upstox-order'),
            path('download-log/', DownloadUpstoxLogAPIView.as_view(), name='download-log'),
            path('log/', log.as_view()),
           
]
