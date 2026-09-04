# ruff: noqa: INP001
"""
Django settings module for edx-notes-api that loads configuration from
environment variables. This replaces the yaml_config.py settings module
when running in Kubernetes.
"""

import json
import os

from django.core.exceptions import ImproperlyConfigured
from notesserver.settings.common import *  # noqa: F403

# Explicitly declare security settings
DEBUG = False
TEMPLATE_DEBUG = False
DISABLE_TOKEN_CHECK = False

# Required environment variables
REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DJANGO_SECRET_KEY",
    "OAUTH_CLIENT_ID",
    "OAUTH_CLIENT_SECRET",
]

# Search backend selection. notesapi/v1/views/__init__.py resolves the search
# view from these two flags: Elasticsearch when ES_DISABLED is false,
# Meilisearch when it is true and MEILISEARCH_ENABLED is true, otherwise a
# LIKE query over the Note model in the application database.
ES_DISABLED = os.environ.get("ELASTICSEARCH_DSL_DISABLED", "false").lower() == "true"
MEILISEARCH_ENABLED = os.environ.get("MEILISEARCH_ENABLED", "false").lower() == "true"

if MEILISEARCH_ENABLED and not ES_DISABLED:
    # views/__init__.py only consults MEILISEARCH_ENABLED inside its
    # ES_DISABLED branch, so this combination silently keeps serving
    # Elasticsearch. Refuse it rather than let the deployment believe it
    # switched.
    msg = (
        "MEILISEARCH_ENABLED requires ELASTICSEARCH_DSL_DISABLED=true; "
        "Meilisearch is only consulted when Elasticsearch is disabled."
    )
    raise ImproperlyConfigured(msg)

if not ES_DISABLED:
    REQUIRED_ENV_VARS.append("ELASTICSEARCH_DSL_HOST")
if MEILISEARCH_ENABLED:
    REQUIRED_ENV_VARS.append("MEILISEARCH_API_KEY")

# Validate required environment variables
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
if missing_vars:
    missing_vars_str = ", ".join(missing_vars)
    msg = f"Missing required environment variables: {missing_vars_str}"
    raise ImproperlyConfigured(msg)

# Django Secret Key
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# OAuth Configuration
CLIENT_ID = os.environ["OAUTH_CLIENT_ID"]
CLIENT_SECRET = os.environ["OAUTH_CLIENT_SECRET"]

# Database Configuration
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE", "django.db.backends.mysql"),
        "HOST": os.environ["DB_HOST"],
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "PORT": int(os.environ.get("DB_PORT", "3306")),
        "OPTIONS": {
            "ssl_mode": "REQUIRED",
            "ssl": {"cipher": "TLSv1.2"},
            "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
        },
    }
}

# Support environment overrides for migrations
DB_OVERRIDES = {
    "PASSWORD": os.environ.get("DB_MIGRATION_PASS", DATABASES["default"]["PASSWORD"]),
    "ENGINE": os.environ.get("DB_MIGRATION_ENGINE", DATABASES["default"]["ENGINE"]),
    "USER": os.environ.get("DB_MIGRATION_USER", DATABASES["default"]["USER"]),
    "NAME": os.environ.get("DB_MIGRATION_NAME", DATABASES["default"]["NAME"]),
    "HOST": os.environ.get("DB_MIGRATION_HOST", DATABASES["default"]["HOST"]),
    "PORT": os.environ.get("DB_MIGRATION_PORT", DATABASES["default"]["PORT"]),
}

for override, value in DB_OVERRIDES.items():
    DATABASES["default"][override] = value

# Elasticsearch Configuration
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
    # notesserver.settings.common sets its own ES_DISABLED = False at import
    # time, so the star-import above has already put ES_APPS into
    # INSTALLED_APPS regardless of what this module decides. Left there,
    # django_elasticsearch_dsl's AppConfig.ready() installs RealTimeSignalProcessor
    # on Note save/delete. That is inert today only because NoteDocument is
    # reachable solely through views/elasticsearch.py, which is not imported
    # when ES is off -- an accident of import order, not a guarantee. Drop the
    # apps so no signal handler is registered in the first place.
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in ES_APPS]  # noqa: F405

# Meilisearch Configuration
if MEILISEARCH_ENABLED:
    MEILISEARCH_URL = os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700")
    MEILISEARCH_API_KEY = os.environ["MEILISEARCH_API_KEY"]
    MEILISEARCH_INDEX = os.environ.get("MEILISEARCH_INDEX", "student_notes")

# Storage Configuration
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

# JWT Configuration
JWT_AUTH = {
    "JWT_AUTH_HEADER_PREFIX": "JWT",
    "JWT_ISSUER": json.loads(os.environ.get("JWT_ISSUER", "[]")),
    "JWT_PUBLIC_SIGNING_JWK_SET": os.environ.get("JWT_PUBLIC_SIGNING_JWK_SET"),
    "JWT_AUTH_COOKIE_HEADER_PAYLOAD": "edx-jwt-cookie-header-payload",
    "JWT_AUTH_COOKIE_SIGNATURE": "edx-jwt-cookie-signature",
    "JWT_ALGORITHM": "HS256",
}

# Additional optional configuration from environment
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = (
    os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if os.environ.get("CSRF_TRUSTED_ORIGINS")
    else []
)

# Logging configuration
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
