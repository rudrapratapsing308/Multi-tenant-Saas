"""
ASGI entry point - keeps the door open for async endpoints / WebSockets
(order updates, live stock) without changing the project layout later.

    daphne config.asgi:application
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_asgi_application()
