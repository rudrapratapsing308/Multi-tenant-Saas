"""
WSGI entry point for the JSON API.

Served by gunicorn/uwsgi in production, by ``manage.py runserver`` in dev:

    gunicorn config.wsgi:application
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_wsgi_application()
