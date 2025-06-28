import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application
import copy_trading.routing   # ✅ import your app's routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading.settings')  # ✅ project name
django.setup()

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            copy_trading.routing.websocket_urlpatterns  # ✅ WebSocket routes
        )
    ),
})