from django.urls import path
from .views import  *

urlpatterns = [ 
               path('api/optiondata/', OptionChainAPIView.as_view(), name='option-chain'),
               path('api/upstox/trading-balances/', UpstoxMultiAccountFundsFromXLSX.as_view()),
               path('api/upstox/funds/', UpstoxMarginAPIView.as_view(), name='upstox-funds'),
               path('api/upstoxfunds/', UpstoxFundListCreateView.as_view(), name='upstoxfund-list-create'),
               path('api/upstoxfunds/<int:pk>/', UpstoxFundDetailUpdateView.as_view(), name='upstoxfund-detail-update'),
               path('api/upstox/all/', UpstoxFundAllView.as_view(), name='upstox-fund-all'),
               path('upload-csv/', InstrumentCSVReplaceView.as_view(), name='upload_csv'),
               path('fund-instrument/', FundInstrumentView.as_view(), name='create_fund_instrument'),           
               path('fund-instrument/<int:pk>/', FundInstrumentView.as_view(), name='update_fund_instrument'), 
               path('api/upstoxx/fundss/', GetUpstoxFundsAPIView.as_view(), name='get-upstox-funds'),
]