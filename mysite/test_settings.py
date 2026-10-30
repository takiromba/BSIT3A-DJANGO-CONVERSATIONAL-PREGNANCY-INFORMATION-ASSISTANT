from .settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Automated tests must never make live requests to an AI provider.
AI_PROVIDER = "openai"
OPENAI_API_KEY = ""
