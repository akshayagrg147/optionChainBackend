from django.urls import path
from .views import  *

urlpatterns = [
   # path("api/live-option-chain/", get_live_option_chain),
    path('api/option-chain/', get_option_chain),
]