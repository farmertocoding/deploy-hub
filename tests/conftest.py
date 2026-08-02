import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
django.setup()
