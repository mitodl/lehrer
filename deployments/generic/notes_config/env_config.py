# ruff: noqa: INP001
"""
Django settings module for edx-notes-api — generic Open edX deployment.

Loads all configuration from environment variables, following the same
pattern as the Kubernetes-ready env_config.py used in operator deployments.
"""

import json
import os

from django.core.exceptions import ImproperlyConfigured
from notesserver.settings.common import *  # noqa: F403

DEBUG = False
TEMPLATE_DEBUG = False
DISABLE_TOKEN_CHECK = False

REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DJANGO_SECRET_KEY",
    "OAUTH_CLIENT_ID",
    "OAUTH_CLIENT_SECRET",
    "ELASTICSEARCH_DSL_HOST",
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
if missing_vars:
    missing_vars_str = ", ".join(missing_vars)
    msg = f"Missing required environment variables: {missing_vars_str}"
    raise ImproperlyConfigured(msg)

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

CLIENT_ID = os.environ["OAUTH_CLIENT_ID"]
CLIENT_SECRET = os.environ["OAUTH_CLIENT_SECRET"]

DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE", "django.db.backends.mysql"),
        "HOST": os.environ["DB_HOST"],
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "PORT": int(os.environ.get("DB_PORT", "3306")),
        "OPTIONS": {
            "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
        },
    }
}

ES_DISABLED = os.environ.get("ELASTICSEARCH_DSL_DISABLED", "false").lower() == "true"

if not ES_DISABLED:
    ELASTICSEARCH_DSL = {
        "default": {
            "hosts": os.environ["ELASTICSEARCH_DSL_HOST"],
            "port": int(os.environ.get("ELASTICSEARCH_DSL_PORT", "9200")),
            "use_ssl": os.environ.get("ELASTICSEARCH_DSL_USE_SSL", "false").lower()
            == "true",
            "verify_certs": os.environ.get(
                "ELASTICSEARCH_DSL_VERIFY_CERTS", "true"
            ).lower()
            == "true",
        }
    }
else:
    ELASTICSEARCH_DSL = {}

STORAGES = {
    "default": {
        "BACKEND": os.environ.get(
            "DEFAULT_FILE_STORAGE", "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": os.environ.get(
            "STATICFILES_STORAGE",
            "django.contrib.staticfiles.storage.StaticFilesStorage",
        ),
    },
}

_jwt_issuer_raw = os.environ.get("JWT_ISSUER", "[]")
try:
    _jwt_issuer = json.loads(_jwt_issuer_raw)
    if isinstance(_jwt_issuer, str):
        _jwt_issuer = [_jwt_issuer]
except json.JSONDecodeError:
    _jwt_issuer = [_jwt_issuer_raw]

JWT_AUTH = {
    "JWT_AUTH_HEADER_PREFIX": "JWT",
    "JWT_ISSUER": _jwt_issuer,
    "JWT_PUBLIC_SIGNING_JWK_SET": os.environ.get("JWT_PUBLIC_SIGNING_JWK_SET"),
    "JWT_AUTH_COOKIE_HEADER_PAYLOAD": "edx-jwt-cookie-header-payload",
    "JWT_AUTH_COOKIE_SIGNATURE": "edx-jwt-cookie-signature",
    "JWT_ALGORITHM": "HS256",
}

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = (
    os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if os.environ.get("CSRF_TRUSTED_ORIGINS")
    else []
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
}
