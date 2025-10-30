from django.urls import path
from .views import  *

urlpatterns = [ 
            path('gettoken/',GetTradingSymbolsAndToken.as_view()),
            path('api/place-upstox-order-buy/', PlaceUpstoxBuyOrderAPIView.as_view(), name='place-upstox-order'),
            path('api/place-upstox-order-sell/', PlaceUpstoxSellOrderAPIView.as_view(), name='place-upstox-order'),
            path('download-log/', DownloadUpstoxLogAPIView.as_view(), name='download-log'),
            path('download-logs/', DownloadUpstoxCSVAPIView.as_view(), name='download-log'),
            path('log/', log.as_view()),
            path('api/place-upstox-order-buy/testing/', PlaceUpstoxBuyOrderAPIViewTesting.as_view(), name='place-upstox-order'),
            path('api/place-upstox-order-sell/testing/', PlaceUpstoxSellOrderAPIViewTesting.as_view(), name='place-upstox-order'),
            path('zerodha/get_tokens/', GetTradingSymbolsAndTokenZerodha.as_view(), name='zerodha-get-tokens'),
            path('zerodha/buy/', PlaceZerodhaBuyOrderAPIView.as_view(), name='zerodha-buy-order'),
            path('zerodha/sell/', PlaceZerodhaSellOrderAPIView.as_view(), name='zerodha-sell-order'),
            path('download-log-zerodha/', DownloadUpstoxLogAPIView.as_view(), name='download-log'),
            
           
]
