from django.urls import path
from .views import  *

urlpatterns = [ 
               path('api/optiondata/', OptionChainAPIView.as_view(), name='option-chain'),
]