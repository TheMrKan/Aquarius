from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path('/controller', consumers.ControllerConsumer.as_asgi()),
]
