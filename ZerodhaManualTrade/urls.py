from django.urls import path
from .views import  *

urlpatterns = [ 
            path('getzerodhatoken/',GetZerodhaTradingSymbol.as_view()),
            path('buyorderapi/',ZerodhaBuyOrderAPIView.as_view()),
            path('sellorderapi/',ZerodhaSellOrderAPIView.as_view()),
           
]
