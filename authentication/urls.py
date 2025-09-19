from django.urls import path
from .views import  *

urlpatterns = [ 
            path('register/', RegisterViewSet.as_view(), name='register'),
            path('login/', LoginViewSet.as_view(), name='login'),
            path('logout/', LogoutViewSet.as_view(), name='logout'),
            path('logout-all/', LogoutAllViewSet.as_view(), name='logout-all'),
               
]