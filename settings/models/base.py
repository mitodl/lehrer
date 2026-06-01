"""Shared production settings base for both LMS and CMS.

Injected by the lehrer Dagger build into both:
  /openedx/edx-platform/lms/envs/models/base.py
  /openedx/edx-platform/cms/envs/models/base.py

Each service's ``aqueduct.py`` imports from this module using a relative
import (``from .models.base import BaseProductionSettings``), so the
single source file works correctly in both namespaces without cross-service
imports.

Settings loading strategy
-------------------------
pydantic-settings sources are ordered highest-to-lowest priority:

1. **Environment variables** — flat scalar settings injected via K8s
   ``envFrom: configMapRef`` (non-secret) and ``envFrom: secretRef``
   (Vault-rendered secrets).  This is the preferred mechanism for any
   setting whose value is a primitive: string, int, bool, or float.

2. **YAML files** (``OL_SETTINGS_DIR``, sorted 00 → 82) — used only for
   settings whose value is a complex type: list, nested dict, etc.
   (``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``, ``MODULESTORE``,
   ``ALLOWED_HOSTS``, …).  Omitted entirely when no YAML files are present
   (e.g. during local development without a K8s config directory).

3. **AqueductSettings field defaults** — typed snapshot of common.py
   defaults captured by ``manage.py generate_aqueduct_settings``.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource
from path import Path

# ---------------------------------------------------------------------------
# Config-sources directory
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS_DIR = "/openedx/config-sources"
_SETTINGS_DIR = os.environ.get("OL_SETTINGS_DIR", _DEFAULT_SETTINGS_DIR)


def _sorted_yaml_files(settings_dir: str) -> list[Path]:
    """Return complex-type YAML files from *settings_dir*, sorted lexicographically.

    Flat scalar settings arrive via environment variables (envFrom ConfigMaps /
    Secrets); these YAML files hold only the structured values that don't map
    cleanly to individual env vars (dicts, lists, etc.).

    Supports two directory layouts:

    Nested (K8s default)::

        <settings_dir>/<name>/<name>.yaml   ← one sub-dir per ConfigMap/Secret

    Flat (local testing)::

        <settings_dir>/*.yaml
    """
    base = Path(settings_dir)
    if not base.is_dir():
        return []
    nested = sorted(base.glob("*/*.yaml"))
    return nested if nested else sorted(base.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Shared base settings model
# ---------------------------------------------------------------------------


class BaseProductionSettings(BaseSettings):
    """Shared OL production settings — inherit alongside the app AqueductSettings.

    Do *not* use this class directly as ``DJANGO_SETTINGS_MODULE``.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="allow",
        arbitrary_types_allowed=True,
    )

    # ------------------------------------------------------------------
    # Type corrections
    # The generated AqueductSettings types these too narrowly; declaring
    # them here takes precedence in the MRO.
    # ------------------------------------------------------------------

    # In production CELERY_BROKER_USE_SSL carries SSL *options* as a dict,
    # e.g. {"ssl_cert_reqs": "optional"}, rather than a plain bool.
    CELERY_BROKER_USE_SSL: bool | dict[str, Any] = Field(default=False)  # type: ignore[assignment]
    BROKER_USE_SSL: bool | dict[str, Any] | None = Field(default=None)  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # YAML alias fields — YAML keys that differ from the Django setting name.
    # These are complex types (lists/dicts) so they arrive via YAML files,
    # not env vars.
    # ------------------------------------------------------------------

    # "LANGUAGE_COOKIE" is the edx-platform YAML convention;
    # Django's setting is LANGUAGE_COOKIE_NAME.
    LANGUAGE_COOKIE: str | None = Field(default=None)

    # STATIC_ROOT / STATIC_URL derived from these base variants when set.
    STATIC_ROOT_BASE: str | None = Field(default=None)
    STATIC_URL_BASE: str | None = Field(default=None)

    # 60-interpolated-config sets ELASTIC_SEARCH_CONFIG_ES7; production.py
    # always used the ES7 key as the authoritative source.
    ELASTIC_SEARCH_CONFIG_ES7: list[dict[str, Any]] | None = Field(default=None)

    # ------------------------------------------------------------------
    # Env-var fields — scalars injected from flat ConfigMaps.
    # Declared here so validators can reference them by name.
    # ------------------------------------------------------------------

    LOG_DIR: str = Field(default="/openedx/data/var/log/edx")
    LOGGING_ENV: str = Field(default="sandbox")
    LOCAL_LOGLEVEL: str = Field(default="INFO")

    # ------------------------------------------------------------------
    # Source customisation
    # ------------------------------------------------------------------

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Two-tier loading: env vars for flat scalars, YAML for complex types.

        Priority (first wins):

        1. Environment variables — K8s injects flat scalars from ConfigMap and
           Secret ``envFrom`` refs directly into the process environment.
        2. YAML files (sorted) — complex settings (lists, nested dicts) that
           cannot be represented cleanly as individual env vars.  Files are
           deep-merged so ``FEATURES`` from a service-specific ConfigMap is
           merged into, not replaced by, the base ``FEATURES`` dict.
           Omitted entirely when no YAML files are found so that an absent
           ``OL_SETTINGS_DIR`` does not cause a runtime validation error.
        """
        sources: list = [env_settings]
        yaml_files = _sorted_yaml_files(_SETTINGS_DIR)
        if yaml_files:
            sources.append(
                YamlConfigSettingsSource(
                    settings_cls,
                    yaml_file=yaml_files,
                    deep_merge=True,
                )
            )
        return tuple(sources)

    # ------------------------------------------------------------------
    # Shared derived-setting validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _derive_celery_queue_names(self) -> BaseProductionSettings:
        """Build CELERY_DEFAULT_* queue names from SERVICE_VARIANT."""
        if getattr(self, "CELERY_DEFAULT_QUEUE", None) is None:
            service_variant = getattr(self, "SERVICE_VARIANT", None)
            if service_variant:
                queue = f"edx.{service_variant}.core.default"
                self.CELERY_DEFAULT_QUEUE = queue  # type: ignore[attr-defined]
                self.CELERY_DEFAULT_ROUTING_KEY = queue  # type: ignore[attr-defined]
                self.CELERY_DEFAULT_EXCHANGE = queue  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_broker_url(self) -> BaseProductionSettings:
        """Build BROKER_URL from CELERY_BROKER_* components.

        CELERY_BROKER_HOSTNAME and CELERY_BROKER_PASSWORD arrive as flat env
        vars (hostname from a ConfigMap, password from a Secret).
        """
        if self.CELERY_BROKER_TRANSPORT and not getattr(self, "BROKER_URL", None):
            self.BROKER_URL = (  # type: ignore[attr-defined]
                f"{self.CELERY_BROKER_TRANSPORT}://"
                f"{self.CELERY_BROKER_USER}:{self.CELERY_BROKER_PASSWORD}"
                f"@{self.CELERY_BROKER_HOSTNAME}/{self.CELERY_BROKER_VHOST}"
            )
        if isinstance(self.CELERY_BROKER_USE_SSL, dict):
            self.BROKER_USE_SSL = self.CELERY_BROKER_USE_SSL
        return self

    @model_validator(mode="after")
    def _derive_static_paths(self) -> BaseProductionSettings:
        """Override STATIC_ROOT / STATIC_URL from *_BASE env-var variants."""
        if self.STATIC_ROOT_BASE:
            self.STATIC_ROOT = self.STATIC_ROOT_BASE  # type: ignore[assignment]
        if self.STATIC_URL_BASE:
            url = self.STATIC_URL_BASE
            if not url.endswith("/"):
                url += "/"
            self.STATIC_URL = url  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_mako_module_dir(self) -> BaseProductionSettings:
        """MAKO_MODULE_DIR lives in the system temp dir, keyed by service variant."""
        if getattr(self, "MAKO_MODULE_DIR", None) is None:
            service_variant = getattr(self, "SERVICE_VARIANT", None)
            if service_variant:
                self.MAKO_MODULE_DIR = os.path.join(  # type: ignore[attr-defined]
                    tempfile.gettempdir(), f"edx_mako_{service_variant}"
                )
        return self

    @model_validator(mode="after")
    def _derive_statici18n_root(self) -> BaseProductionSettings:
        """STATICI18N_ROOT mirrors STATIC_ROOT."""
        if getattr(self, "STATICI18N_ROOT", None) is None:
            static_root = getattr(self, "STATIC_ROOT", None)
            if static_root:
                self.STATICI18N_ROOT = static_root  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_language_settings(self) -> BaseProductionSettings:
        """Populate LANGUAGE_COOKIE_NAME (from YAML alias) and LANGUAGE_DICT."""
        if self.LANGUAGE_COOKIE:
            self.LANGUAGE_COOKIE_NAME = self.LANGUAGE_COOKIE  # type: ignore[attr-defined]
        languages = getattr(self, "LANGUAGES", None)
        if languages:
            self.LANGUAGE_DICT = dict(languages)  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_elastic_search_config(self) -> BaseProductionSettings:
        """Use ELASTIC_SEARCH_CONFIG_ES7 as the authoritative search config."""
        if self.ELASTIC_SEARCH_CONFIG_ES7:
            self.ELASTIC_SEARCH_CONFIG = self.ELASTIC_SEARCH_CONFIG_ES7  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_timezone(self) -> BaseProductionSettings:
        """Align Django TIME_ZONE with Celery's timezone."""
        celery_timezone = getattr(self, "CELERY_TIMEZONE", None)
        if celery_timezone:
            self.TIME_ZONE = celery_timezone  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_logging(self) -> BaseProductionSettings:
        """Build LOGGING from log-dir / environment / loglevel.

        All three inputs are flat scalars arriving as env vars; they are
        declared as explicit fields so pydantic populates them before this
        validator runs.
        """
        from openedx.core.lib.logsettings import get_logger_config  # noqa: PLC0415

        service_variant = getattr(self, "SERVICE_VARIANT", None)
        self.LOGGING = get_logger_config(  # type: ignore[attr-defined]
            self.LOG_DIR,
            logging_env=self.LOGGING_ENV,
            local_loglevel=self.LOCAL_LOGLEVEL,
            service_variant=service_variant,
        )
        return self


class SharedAqueductSettings(BaseSettings):
    """Settings shared between LMS and CMS.

    Generated by ``dagger call regenerate-aqueduct-settings``.
    Manual edits here apply to both services automatically.
    Service-specific settings (and shared settings whose defaults
    differ between services) live in the per-service model files:
      settings/lms/models/aqueduct.py
      settings/cms/models/aqueduct.py
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="allow",
    )

    ACCOUNT_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    ACE_CHANNEL_DEFAULT_EMAIL: str = Field(default="django_email")
    ACE_CHANNEL_DEFAULT_PUSH: str = Field(default="push_notification")
    ACE_CHANNEL_SAILTHRU_API_KEY: Any = Field(default=None)  # TODO: refine type
    ACE_CHANNEL_SAILTHRU_API_SECRET: Any = Field(default=None)  # TODO: refine type
    ACE_CHANNEL_SAILTHRU_DEBUG: bool = Field(default=True)
    ACE_CHANNEL_SAILTHRU_TEMPLATE_NAME: str = Field(
        default="Automated Communication Engine Email"
    )
    ACE_CHANNEL_TRANSACTIONAL_EMAIL: str = Field(default="django_email")
    ACE_ENABLED_CHANNELS: list[Any] = Field(default_factory=lambda: ["django_email"])
    ACE_ENABLED_POLICIES: list[Any] = Field(
        default_factory=lambda: ["bulk_email_optout"]
    )
    ACE_ROUTING_KEY: str = Field(default="edx.lms.core.default")
    ACTIVATION_EMAIL_SUPPORT_LINK: str = Field(default="")
    ADMINS: list[Any] = Field(default_factory=lambda: [])
    ADMIN_CONSOLE_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    AFFILIATE_COOKIE_NAME: str = Field(default="dev_affiliate_id")
    AI_TRANSLATIONS_API_URL: str = Field(default="http://localhost:18760/api/v1")
    ALLOWED_HOSTS: list[Any] = Field(default_factory=lambda: ["*"])
    ALLOW_HIDING_DISCUSSION_TAB: bool = Field(default=False)
    ALLOW_PUBLIC_ACCOUNT_CREATION: bool = Field(default=True)
    ALL_LANGUAGES: list[Any] = Field(
        default_factory=lambda: [
            ["aa", "Afar"],
            ["ab", "Abkhazian"],
            ["af", "Afrikaans"],
            ["ak", "Akan"],
            ["sq", "Albanian"],
            ["am", "Amharic"],
            ["ar", "Arabic"],
            ["an", "Aragonese"],
            ["hy", "Armenian"],
            ["as", "Assamese"],
            ["av", "Avaric"],
            ["ae", "Avestan"],
            ["ay", "Aymara"],
            ["az", "Azerbaijani"],
            ["ba", "Bashkir"],
            ["bm", "Bambara"],
            ["eu", "Basque"],
            ["be", "Belarusian"],
            ["bn", "Bengali"],
            ["bh", "Bihari languages"],
            ["bi", "Bislama"],
            ["bs", "Bosnian"],
            ["br", "Breton"],
            ["bg", "Bulgarian"],
            ["my", "Burmese"],
            ["ca", "Catalan"],
            ["ch", "Chamorro"],
            ["ce", "Chechen"],
            ["zh", "Chinese"],
            ["zh_HANS", "Simplified Chinese"],
            ["zh_HANT", "Traditional Chinese"],
            ["cu", "Church Slavic"],
            ["cv", "Chuvash"],
            ["kw", "Cornish"],
            ["co", "Corsican"],
            ["cr", "Cree"],
            ["cs", "Czech"],
            ["da", "Danish"],
            ["dv", "Divehi"],
            ["nl", "Dutch"],
            ["dz", "Dzongkha"],
            ["en", "English"],
            ["eo", "Esperanto"],
            ["et", "Estonian"],
            ["ee", "Ewe"],
            ["fo", "Faroese"],
            ["fj", "Fijian"],
            ["fi", "Finnish"],
            ["fr", "French"],
            ["fy", "Western Frisian"],
            ["ff", "Fulah"],
            ["ka", "Georgian"],
            ["de", "German"],
            ["gd", "Gaelic"],
            ["ga", "Irish"],
            ["gl", "Galician"],
            ["gv", "Manx"],
            ["el", "Greek"],
            ["gn", "Guarani"],
            ["gu", "Gujarati"],
            ["ht", "Haitian"],
            ["ha", "Hausa"],
            ["he", "Hebrew"],
            ["hz", "Herero"],
            ["hi", "Hindi"],
            ["ho", "Hiri Motu"],
            ["hr", "Croatian"],
            ["hu", "Hungarian"],
            ["ig", "Igbo"],
            ["is", "Icelandic"],
            ["io", "Ido"],
            ["ii", "Sichuan Yi"],
            ["iu", "Inuktitut"],
            ["ie", "Interlingue"],
            ["ia", "Interlingua"],
            ["id", "Indonesian"],
            ["ik", "Inupiaq"],
            ["it", "Italian"],
            ["jv", "Javanese"],
            ["ja", "Japanese"],
            ["kl", "Kalaallisut"],
            ["kn", "Kannada"],
            ["ks", "Kashmiri"],
            ["kr", "Kanuri"],
            ["kk", "Kazakh"],
            ["km", "Central Khmer"],
            ["ki", "Kikuyu"],
            ["rw", "Kinyarwanda"],
            ["ky", "Kirghiz"],
            ["kv", "Komi"],
            ["kg", "Kongo"],
            ["ko", "Korean"],
            ["kj", "Kuanyama"],
            ["ku", "Kurdish"],
            ["lo", "Lao"],
            ["la", "Latin"],
            ["lv", "Latvian"],
            ["li", "Limburgan"],
            ["ln", "Lingala"],
            ["lt", "Lithuanian"],
            ["lb", "Luxembourgish"],
            ["lu", "Luba-Katanga"],
            ["lg", "Ganda"],
            ["mk", "Macedonian"],
            ["mh", "Marshallese"],
            ["ml", "Malayalam"],
            ["mi", "Maori"],
            ["mr", "Marathi"],
            ["ms", "Malay"],
            ["mg", "Malagasy"],
            ["mt", "Maltese"],
            ["mn", "Mongolian"],
            ["na", "Nauru"],
            ["nv", "Navajo"],
            ["nr", "Ndebele, South"],
            ["nd", "Ndebele, North"],
            ["ng", "Ndonga"],
            ["ne", "Nepali"],
            ["nn", "Norwegian Nynorsk"],
            ["nb", "Bokmål, Norwegian"],
            ["no", "Norwegian"],
            ["ny", "Chichewa"],
            ["oc", "Occitan"],
            ["oj", "Ojibwa"],
            ["or", "Oriya"],
            ["om", "Oromo"],
            ["os", "Ossetian"],
            ["pa", "Panjabi"],
            ["fa", "Persian"],
            ["pi", "Pali"],
            ["pl", "Polish"],
            ["pt", "Portuguese"],
            ["ps", "Pushto"],
            ["qu", "Quechua"],
            ["rm", "Romansh"],
            ["ro", "Romanian"],
            ["rn", "Rundi"],
            ["ru", "Russian"],
            ["sg", "Sango"],
            ["sa", "Sanskrit"],
            ["si", "Sinhala"],
            ["sk", "Slovak"],
            ["sl", "Slovenian"],
            ["se", "Northern Sami"],
            ["sm", "Samoan"],
            ["sn", "Shona"],
            ["sd", "Sindhi"],
            ["so", "Somali"],
            ["st", "Sotho, Southern"],
            ["es", "Spanish"],
            ["sc", "Sardinian"],
            ["sr", "Serbian"],
            ["ss", "Swati"],
            ["su", "Sundanese"],
            ["sw", "Swahili"],
            ["sv", "Swedish"],
            ["ty", "Tahitian"],
            ["ta", "Tamil"],
            ["tt", "Tatar"],
            ["te", "Telugu"],
            ["tg", "Tajik"],
            ["tl", "Tagalog"],
            ["th", "Thai"],
            ["bo", "Tibetan"],
            ["ti", "Tigrinya"],
            ["to", "Tonga (Tonga Islands)"],
            ["tn", "Tswana"],
            ["ts", "Tsonga"],
            ["tk", "Turkmen"],
            ["tr", "Turkish"],
            ["tw", "Twi"],
            ["ug", "Uighur"],
            ["uk", "Ukrainian"],
            ["ur", "Urdu"],
            ["uz", "Uzbek"],
            ["ve", "Venda"],
            ["vi", "Vietnamese"],
            ["vo", "Volapük"],
            ["cy", "Welsh"],
            ["wa", "Walloon"],
            ["wo", "Wolof"],
            ["xh", "Xhosa"],
            ["yi", "Yiddish"],
            ["yo", "Yoruba"],
            ["za", "Zhuang"],
            ["zu", "Zulu"],
        ]
    )
    API_ACCESS_FROM_EMAIL: str = Field(default="api-requests@example.com")
    API_ACCESS_MANAGER_EMAIL: str = Field(default="api-access@example.com")
    API_DOCUMENTATION_URL: str = Field(
        default="https://course-catalog-api-guide.readthedocs.io/en/latest/"
    )
    ASSET_IGNORE_REGEX: str = Field(default="(^\\._.*$)|(^\\.DS_Store$)|(^.*~$)")
    ASSET_KEY_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    AUTH_DOCUMENTATION_URL: str = Field(
        default="https://course-catalog-api-guide.readthedocs.io/en/latest/authentication/index.html"
    )
    AUTH_PASSWORD_VALIDATORS: list[Any] = Field(
        default_factory=lambda: [
            {
                "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
            },
            {
                "NAME": "common.djangoapps.util.password_policy_validators.MinimumLengthValidator",
                "OPTIONS": {"min_length": 8},
            },
            {
                "NAME": "common.djangoapps.util.password_policy_validators.MaximumLengthValidator",
                "OPTIONS": {"max_length": 75},
            },
        ]
    )
    AUTOMATIC_AUTH_FOR_TESTING: bool = Field(default=False)
    AUTOPLAY_VIDEOS: bool = Field(default=False)
    AUTO_GENERATED_USERNAME_RANDOM_STRING_LENGTH: int = Field(default=4)
    AUTO_LANGUAGE_SELECTION_EXEMPT_PATHS: list[Any] = Field(
        default_factory=lambda: ["admin", "sysadmin", "instructor"]
    )
    AWS_ACCESS_KEY_ID: Any = Field(default=None)  # TODO: refine type
    AWS_QUERYSTRING_AUTH: bool = Field(default=True)
    AWS_S3_CUSTOM_DOMAIN: str = Field(default="edxuploads.s3.amazonaws.com")
    AWS_SECRET_ACCESS_KEY: Any = Field(default=None)  # TODO: refine type
    AWS_SES_REGION_ENDPOINT: str = Field(default="email.us-east-1.amazonaws.com")
    AWS_SES_REGION_NAME: str = Field(default="us-east-1")
    AWS_STORAGE_BUCKET_NAME: str = Field(default="edxuploads")
    BADGES_ENABLED: bool = Field(default=False)
    BASE_COOKIE_DOMAIN: str = Field(default="localhost")
    BEAMER_PRODUCT_ID: str = Field(default="")
    BLOCK_STRUCTURES_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "COURSE_PUBLISH_TASK_DELAY": 30,
            "TASK_DEFAULT_RETRY_DELAY": 30,
            "TASK_MAX_RETRIES": 5,
        }
    )
    BROKER_HEARTBEAT: float = Field(default=60.0)
    BROKER_HEARTBEAT_CHECKRATE: int = Field(default=2)
    BROKER_USE_SSL: bool = Field(default=False)
    BUGS_EMAIL: str = Field(default="bugs@example.com")
    BULK_EMAIL_DEFAULT_FROM_EMAIL: str = Field(default="no-reply@example.com")
    BULK_EMAIL_EMAILS_PER_TASK: int = Field(default=500)
    BULK_EMAIL_LOG_SENT_EMAILS: bool = Field(default=False)
    CACHES: dict[str, Any] = Field(
        default_factory=lambda: {
            "course_structure_cache": {
                "KEY_PREFIX": "course_structure",
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "TIMEOUT": "604800",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "celery": {
                "KEY_PREFIX": "celery",
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "TIMEOUT": "7200",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "mongo_metadata_inheritance": {
                "KEY_PREFIX": "mongo_metadata_inheritance",
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "TIMEOUT": 300,
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "staticfiles": {
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "KEY_PREFIX": "staticfiles_general",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "default": {
                "VERSION": "1",
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "KEY_PREFIX": "default",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "configuration": {
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "KEY_PREFIX": "configuration",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
            "general": {
                "KEY_FUNCTION": "common.djangoapps.util.memcache.safe_key",
                "LOCATION": ["localhost:11211"],
                "KEY_PREFIX": "general",
                "BACKEND": "django.core.cache.backends.memcached.PyMemcacheCache",
                "OPTIONS": {
                    "no_delay": True,
                    "ignore_exc": True,
                    "use_pooling": True,
                    "connect_timeout": 0.5,
                },
            },
        }
    )
    CALCULATOR_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/how-tos/course_development/exercise_tools/add_calculator.html"
    )
    CANVAS_ACCESS_TOKEN: Any = Field(default=None)  # TODO: refine type
    CANVAS_BASE_URL: Any = Field(default=None)  # TODO: refine type
    CASBIN_AUTO_LOAD_POLICY_INTERVAL: int = Field(default=0)
    CASBIN_AUTO_SAVE_POLICY: bool = Field(default=True)
    CASBIN_LOG_LEVEL: str = Field(default="WARNING")
    CASBIN_MODEL: str = Field(
        default="/openedx/venv/lib/python3.12/site-packages/openedx_authz/engine/config/model.conf"
    )
    CELERY_BROKER_HOSTNAME: str = Field(default="")
    CELERY_BROKER_PASSWORD: str = Field(default="")
    CELERY_BROKER_TRANSPORT: str = Field(default="")
    CELERY_BROKER_USER: str = Field(default="")
    CELERY_BROKER_USE_SSL: bool = Field(default=False)
    CELERY_BROKER_VHOST: str = Field(default="")
    CELERY_CREATE_MISSING_QUEUES: bool = Field(default=True)
    CELERY_DEFAULT_EXCHANGE_TYPE: str = Field(default="direct")
    CELERY_EVENT_QUEUE_TTL: Any = Field(default=None)  # TODO: refine type
    CELERY_IGNORE_RESULT: bool = Field(default=False)
    CELERY_MESSAGE_COMPRESSION: str = Field(default="gzip")
    CELERY_QUEUE_HA_POLICY: str = Field(default="all")
    CELERY_RESULT_BACKEND: str = Field(default="django-cache")
    CELERY_RESULT_SERIALIZER: str = Field(default="json")
    CELERY_SEND_EVENTS: bool = Field(default=True)
    CELERY_SEND_TASK_SENT_EVENT: bool = Field(default=True)
    CELERY_STORE_ERRORS_EVEN_IF_IGNORED: bool = Field(default=True)
    CELERY_TASK_SERIALIZER: str = Field(default="json")
    CELERY_TIMEZONE: str = Field(default="UTC")
    CELERY_TRACK_STARTED: bool = Field(default=True)
    CERTIFICATES_HTML_VIEW: bool = Field(default=False)
    CERTIFICATE_TEMPLATE_LANGUAGES: dict[str, Any] = Field(
        default_factory=lambda: {"en": "English", "es": "Español"}
    )
    CERTIFICATE_WEBHOOK_ACCESS_TOKEN: Any = Field(default=None)  # TODO: refine type
    CERTIFICATE_WEBHOOK_URL: Any = Field(default=None)  # TODO: refine type
    CHAT_COMPLETION_API: str = Field(default="")
    CHAT_COMPLETION_API_KEY: str = Field(default="")
    CODE_JAIL_REST_SERVICE_CONNECT_TIMEOUT: float = Field(default=0.5)
    CODE_JAIL_REST_SERVICE_HOST: str = Field(default="http://127.0.0.1:8550")
    CODE_JAIL_REST_SERVICE_READ_TIMEOUT: float = Field(default=3.5)
    CODE_JAIL_REST_SERVICE_REMOTE_EXEC: str = Field(
        default="xmodule.capa.safe_exec.remote_exec.send_safe_exec_request_v0"
    )
    COMMON_ROOT: str = Field(default=Path("/openedx/edx-platform/common"))
    COMPLETION_VIDEO_COMPLETE_PERCENTAGE: float = Field(default=0.95)
    COMPREHENSIVE_THEME_DIRS: list[Any] = Field(default_factory=lambda: [""])
    COMPREHENSIVE_THEME_LOCALE_PATHS: list[Any] = Field(default_factory=lambda: [])
    CONTACT_EMAIL: str = Field(default="info@example.com")
    CONTENT_TYPE_GATE_GROUP_IDS: dict[str, Any] = Field(
        default_factory=lambda: {"limited_access": 1, "full_access": 2}
    )
    CONTEXT_PROCESSORS: list[Any] = Field(
        default_factory=lambda: [
            "django.template.context_processors.request",
            "django.template.context_processors.static",
            "django.template.context_processors.i18n",
            "django.contrib.auth.context_processors.auth",
            "django.template.context_processors.csrf",
            "django.template.context_processors.media",
            "django.template.context_processors.tz",
            "django.contrib.messages.context_processors.messages",
            "sekizai.context_processors.sekizai",
            "common.djangoapps.edxmako.shortcuts.marketing_link_context_processor",
            "lms.djangoapps.courseware.context_processor.user_timezone_locale_prefs",
            "help_tokens.context_processor",
            "openedx.core.djangoapps.site_configuration.context_processors.configuration_context",
            "lms.djangoapps.mobile_api.context_processor.is_from_mobile_app",
            "openedx.features.survey_report.context_processors.admin_extra_context",
            "social_django.context_processors.backends",
            "social_django.context_processors.login_redirect",
        ]
    )
    COURSES_ROOT: str = Field(default=Path("/openedx/data"))
    COURSES_WITH_UNSAFE_CODE: list[Any] = Field(default_factory=lambda: [])
    COURSE_ABOUT_VISIBILITY_PERMISSION: str = Field(default="see_exists")
    COURSE_ACCESS_DURATION_MAX_WEEKS: int = Field(default=18)
    COURSE_ACCESS_DURATION_MIN_WEEKS: int = Field(default=4)
    COURSE_AUTHORING_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    COURSE_CATALOG_API_URL: str = Field(default="http://localhost:8008/api/v1")
    COURSE_CATALOG_URL_ROOT: str = Field(default="http://localhost:8008")
    COURSE_CATALOG_VISIBILITY_PERMISSION: str = Field(default="see_exists")
    COURSE_ENROLLMENT_MODES: dict[str, Any] = Field(default=None)
    COURSE_ID_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    COURSE_KEY_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    COURSE_KEY_REGEX: str = Field(default="(?:[^/+]+(/|\\+)[^/+]+(/|\\+)[^/?]+)")
    COURSE_LIVE_GLOBAL_CREDENTIALS: dict[str, Any] = Field(default_factory=lambda: {})
    COURSE_MODE_DEFAULTS: dict[str, Any] = Field(default=None)
    COURSE_OLX_VALIDATION_IGNORE_LIST: Any = Field(default=None)  # TODO: refine type
    COURSE_OLX_VALIDATION_STAGE: int = Field(default=1)
    COURSE_TRANSLATIONS_BASE_DIR: str = Field(
        default="/openedx/data/course_translations/"
    )
    COURSE_TRANSLATIONS_SUPPORTED_ARCHIVE_EXTENSIONS: list[Any] = Field(
        default_factory=lambda: [".tar.gz", ".tgz", ".tar"]
    )
    COURSE_TRANSLATIONS_SUPPORTED_LANGUAGES: dict[str, Any] = Field(
        default_factory=lambda: {
            "ar": "Arabic",
            "de": "German",
            "de_DE": "German (Germany)",
            "el": "Greek",
            "en": "English",
            "es_ES": "Spanish (Spain)",
            "es_419": "Spanish (Latin America)",
            "fr": "French",
            "hi": "Hindi",
            "ja": "Japanese",
            "pt": "Portuguese",
            "pt_BR": "Portuguese (Brazil)",
            "ru": "Russian",
            "sw": "Swahili",
            "zh": "Chinese",
            "zh_HANS": "Chinese (Simplified)",
            "zh_HANT": "Chinese (Traditional)",
        }
    )
    COURSE_TRANSLATIONS_TARGET_DIRECTORIES: list[Any] = Field(
        default_factory=lambda: [
            "about",
            "course",
            "chapter",
            "drafts",
            "html",
            "info",
            "problem",
            "sequential",
            "vertical",
            "video",
            "static",
            "tabs",
        ]
    )
    COURSE_TRANSLATIONS_TRANSLATABLE_EXTENSIONS: list[Any] = Field(
        default_factory=lambda: [".html", ".xml", ".srt"]
    )
    CREDENTIALS_SERVICE_USERNAME: str = Field(default="credentials_service_user")
    CREDIT_PROVIDER_SECRET_KEYS: dict[str, Any] = Field(default_factory=lambda: {})
    CREDIT_PROVIDER_TIMESTAMP_EXPIRATION: int = Field(default=900)
    CREDIT_TASK_DEFAULT_RETRY_DELAY: int = Field(default=30)
    CREDIT_TASK_MAX_RETRIES: int = Field(default=5)
    CROSS_DOMAIN_CSRF_COOKIE_DOMAIN: str = Field(default="")
    CROSS_DOMAIN_CSRF_COOKIE_NAME: str = Field(default="")
    CSRF_COOKIE_AGE: int = Field(default=31449600)
    CSRF_COOKIE_SECURE: bool = Field(default=False)
    CSRF_TRUSTED_ORIGINS: list[Any] = Field(default_factory=lambda: [])
    CUSTOM_COURSES_EDX: bool = Field(default=False)
    CUSTOM_PAGES_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/how-tos/course_development/manage_custom_page.html"
    )
    CUSTOM_RESOURCE_TEMPLATES_DIRECTORY: Any = Field(default=None)  # TODO: refine type
    DATABASES: dict[str, Any] = Field(
        default_factory=lambda: {
            "default": {
                "ATOMIC_REQUESTS": True,
                "CONN_MAX_AGE": 0,
                "ENGINE": "django.db.backends.mysql",
                "HOST": "127.0.0.1",
                "NAME": "edxapp",
                "OPTIONS": {},
                "PASSWORD": "password",  # pragma: allowlist secret
                "PORT": "3306",
                "USER": "edxapp001",
            },
            "read_replica": {
                "CONN_MAX_AGE": 0,
                "ENGINE": "django.db.backends.mysql",
                "HOST": "127.0.0.1",
                "NAME": "edxapp",
                "OPTIONS": {},
                "PASSWORD": "password",  # pragma: allowlist secret
                "PORT": "3306",
                "USER": "edxapp001",
            },
            "student_module_history": {
                "CONN_MAX_AGE": 0,
                "ENGINE": "django.db.backends.mysql",
                "HOST": "127.0.0.1",
                "NAME": "edxapp_csmh",
                "OPTIONS": {},
                "PASSWORD": "password",  # pragma: allowlist secret
                "PORT": "3306",
                "USER": "edxapp001",
            },
        }
    )
    DATABASE_ROUTERS: list[Any] = Field(
        default_factory=lambda: [
            "openedx.core.lib.django_courseware_routers.StudentModuleHistoryExtendedRouter",
            "edx_django_utils.db.read_replica.ReadReplicaRouter",
        ]
    )
    DATA_UPLOAD_MAX_MEMORY_SIZE: Any = Field(default=None)  # TODO: refine type
    DATA_UPLOAD_MAX_NUMBER_FIELDS: Any = Field(default=None)  # TODO: refine type
    DEBUG: bool = Field(default=False)
    DEBUG_TOOLBAR_PATCH_SETTINGS: bool = Field(default=False)
    DEFAULT_AUTO_FIELD: str = Field(default="django.db.models.AutoField")
    DEFAULT_COURSE_ABOUT_IMAGE_URL: str = Field(default="images/pencils.jpg")
    DEFAULT_COURSE_VISIBILITY_IN_CATALOG: str = Field(default="both")
    DEFAULT_EMAIL_LOGO_URL: str = Field(
        default="https://edx-cdn.org/v3/default/logo.png"
    )
    DEFAULT_FEEDBACK_EMAIL: str = Field(default="feedback@example.com")
    DEFAULT_FROM_EMAIL: str = Field(default="registration@example.com")
    DEFAULT_HASHING_ALGORITHM: str = Field(default="sha256")
    DEFAULT_MOBILE_AVAILABLE: bool = Field(default=False)
    DEFAULT_NOTIFICATION_ICON_URL: str = Field(default="")
    DEFAULT_SITE_THEME: Any = Field(default=None)  # TODO: refine type
    DEPRECATED_ADVANCED_COMPONENT_TYPES: list[Any] = Field(default_factory=lambda: [])
    DISABLE_ACCOUNT_ACTIVATION_REQUIREMENT_SWITCH: str = Field(
        default="verify_student_disable_account_activation_requirement"
    )
    DISABLE_MOBILE_COURSE_AVAILABLE: bool = Field(default=False)
    DISABLE_START_DATES: bool = Field(default=False)
    DISABLE_UNENROLLMENT: bool = Field(default=False)
    DISCUSSIONS_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/concepts/communication/about_course_discussions.html"
    )
    DISCUSSIONS_MFE_FEEDBACK_URL: Any = Field(default=None)  # TODO: refine type
    DISCUSSIONS_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    DISCUSSION_RATELIMIT: str = Field(default="100/m")
    DISCUSSION_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "MAX_COMMENT_DEPTH": 2,
            "COURSE_PUBLISH_TASK_DELAY": 30,
        }
    )
    DJFS: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "osfs",
            "directory_root": "/edx/var/edxapp/django-pyfs/static/django-pyfs",
            "url_root": "/static/django-pyfs",
        }
    )
    ECOMMERCE_API_SIGNING_KEY: str = Field(default="SET-ME-PLEASE")
    ECOMMERCE_API_URL: str = Field(default="http://localhost:8002/api/v2")
    ECOMMERCE_PUBLIC_URL_ROOT: str = Field(default="http://localhost:8002")
    EDXMKTG_LOGGED_IN_COOKIE_NAME: str = Field(default="edxloggedin")
    EDXMKTG_USER_INFO_COOKIE_NAME: str = Field(default="edx-user-info")
    EDXMKTG_USER_INFO_COOKIE_VERSION: int = Field(default=1)
    EDXNOTES_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/how-tos/course_development/exercise_tools/enable_notes.html"
    )
    EDX_DRF_EXTENSIONS: dict[str, Any] = Field(
        default_factory=lambda: {
            "JWT_PAYLOAD_USER_ATTRIBUTE_MAPPING": {},
            "VERIFY_LMS_USER_ID_PROPERTY_NAME": "id",
        }
    )
    EDX_PLATFORM_REVISION: str = Field(default="release")
    EDX_ROOT_URL: str = Field(default="")
    ELASTIC_SEARCH_CONFIG: list[Any] = Field(
        default_factory=lambda: [{"use_ssl": False, "host": "localhost", "port": 9200}]
    )
    EMAIL_CHANGE_RATE_LIMIT: str = Field(default="")
    EMBARGO: bool = Field(default=False)
    EMBARGO_SITE_REDIRECT_URL: Any = Field(default=None)  # TODO: refine type
    ENABLE_AUTOADVANCE_VIDEOS: bool = Field(default=False)
    ENABLE_AUTOMATIC_AUTHZ_COURSE_AUTHORING_MIGRATION: bool = Field(default=False)
    ENABLE_AUTO_LANGUAGE_SELECTION: bool = Field(default=False)
    ENABLE_CHANGE_USER_PASSWORD_ADMIN: bool = Field(default=False)
    ENABLE_CODEJAIL_REST_SERVICE: bool = Field(default=False)
    ENABLE_COMPREHENSIVE_THEMING: bool = Field(default=False)
    ENABLE_COPPA_COMPLIANCE: bool = Field(default=False)
    ENABLE_CORS_HEADERS: bool = Field(default=False)
    ENABLE_COURSE_OLX_VALIDATION: bool = Field(default=False)
    ENABLE_CREDIT_ELIGIBILITY: bool = Field(default=True)
    ENABLE_CROSS_DOMAIN_CSRF_COOKIE: bool = Field(default=False)
    ENABLE_CSMH_EXTENDED: bool = Field(default=True)
    ENABLE_DISCUSSION_SERVICE: bool = Field(default=True)
    ENABLE_DYNAMIC_REGISTRATION_FIELDS: bool = Field(default=False)
    ENABLE_EDXNOTES: bool = Field(default=False)
    ENABLE_ENROLLMENT_RESET: bool = Field(default=False)
    ENABLE_ENROLLMENT_TRACK_USER_PARTITION: bool = Field(default=True)
    ENABLE_HELP_LINK: bool = Field(default=True)
    ENABLE_INTEGRITY_SIGNATURE: bool = Field(default=False)
    ENABLE_JASMINE: bool = Field(default=False)
    ENABLE_LTI_PII_ACKNOWLEDGEMENT: bool = Field(default=False)
    ENABLE_MKTG_SITE: bool = Field(default=False)
    ENABLE_MOBILE_REST_API: bool = Field(default=False)
    ENABLE_ORA_ALL_FILE_URLS: bool = Field(default=False)
    ENABLE_ORA_USER_STATE_UPLOAD_DATA: bool = Field(default=False)
    ENABLE_PASSWORD_RESET_FAILURE_EMAIL: bool = Field(default=False)
    ENABLE_PREREQUISITE_COURSES: bool = Field(default=False)
    ENABLE_PUBLISHER: bool = Field(default=False)
    ENABLE_READING_FROM_MULTIPLE_HISTORY_TABLES: bool = Field(default=True)
    ENABLE_SERVICE_STATUS: bool = Field(default=False)
    ENABLE_SPECIAL_EXAMS: bool = Field(default=False)
    ENABLE_TEAMS: bool = Field(default=True)
    ENABLE_TEXTBOOK: bool = Field(default=True)
    ENABLE_VIDEO_BUMPER: bool = Field(default=False)
    ENROLLMENT_COURSE_ACCESS_ROLES: list[Any] = Field(
        default_factory=lambda: ["instructor", "staff"]
    )
    ENROLLMENT_WEBHOOK_ACCESS_TOKEN: Any = Field(default=None)  # TODO: refine type
    ENROLLMENT_WEBHOOK_URL: Any = Field(default=None)  # TODO: refine type
    ENTERPRISE_API_CACHE_TIMEOUT: int = Field(default=3600)
    ENTERPRISE_BACKEND_SERVICE_EDX_OAUTH2_KEY: str = Field(
        default="enterprise-backend-service-key"
    )
    ENTERPRISE_BACKEND_SERVICE_EDX_OAUTH2_PROVIDER_URL: str = Field(
        default="http://127.0.0.1:8000/oauth2"
    )
    ENTERPRISE_BACKEND_SERVICE_EDX_OAUTH2_SECRET: str = Field(
        default="enterprise-backend-service-secret"
    )
    ENTERPRISE_CATALOG_INTERNAL_ROOT_URL: str = Field(
        default="http://enterprise.catalog.app:18160"
    )
    ENTERPRISE_CUSTOMER_CATALOG_DEFAULT_CONTENT_FILTER: dict[str, Any] = Field(
        default_factory=lambda: {}
    )
    ENTERPRISE_MARKETING_FOOTER_QUERY_PARAMS: dict[str, Any] = Field(
        default_factory=lambda: {}
    )
    ENTERPRISE_SERVICE_WORKER_USERNAME: str = Field(default="enterprise_worker")
    ENTRANCE_EXAM_MIN_SCORE_PCT: int = Field(default=50)
    ENV_ROOT: str = Field(default=Path("/openedx"))
    EVENT_TRACKING_BACKENDS: dict[str, Any] = Field(
        default_factory=lambda: {
            "tracking_logs": {
                "ENGINE": "eventtracking.backends.routing.RoutingBackend",
                "OPTIONS": {
                    "backends": {
                        "logger": {
                            "ENGINE": "eventtracking.backends.logger.LoggerBackend",
                            "OPTIONS": {"name": "tracking", "max_event_size": 50000},
                        }
                    },
                    "processors": [
                        {
                            "ENGINE": "common.djangoapps.track.shim.LegacyFieldMappingProcessor"
                        },
                        {
                            "ENGINE": "common.djangoapps.track.shim.PrefixedEventProcessor"
                        },
                    ],
                },
            },
            "segmentio": {
                "ENGINE": "eventtracking.backends.routing.RoutingBackend",
                "OPTIONS": {
                    "backends": {
                        "segment": {
                            "ENGINE": "eventtracking.backends.segment.SegmentBackend"
                        }
                    },
                    "processors": [
                        {
                            "ENGINE": "eventtracking.processors.whitelist.NameWhitelistProcessor",
                            "OPTIONS": {"whitelist": []},
                        },
                        {
                            "ENGINE": "common.djangoapps.track.shim.GoogleAnalyticsProcessor"
                        },
                    ],
                },
            },
            "rapid_response": {
                "ENGINE": "rapid_response_xblock.logger.SubmissionRecorder",
                "OPTIONS": {"name": "rapid_response"},
            },
        }
    )
    EVENT_TRACKING_ENABLED: bool = Field(default=True)
    EVENT_TRACKING_PROCESSORS: list[Any] = Field(default_factory=lambda: [])
    EVENT_TRACKING_SEGMENTIO_EMIT_WHITELIST: list[Any] = Field(
        default_factory=lambda: []
    )
    EXAMS_SERVICE_URL: str = Field(default="http://localhost:18740/api/v1")
    EXPIRED_NOTIFICATIONS_DELETE_BATCH_SIZE: int = Field(default=10000)
    FALLBACK_TO_ENGLISH_TRANSCRIPTS: bool = Field(default=True)
    FAVICON_PATH: str = Field(default="images/favicon.ico")
    FAVICON_URL: Any = Field(default=None)  # TODO: refine type
    FCM_APP_NAME: str = Field(default="fcm-edx-platform")
    FEATURES: Any = Field(
        default=None
    )  # DERIVED: computed from other settings — add a @model_validator to reproduce
    FEEDBACK_SUBMISSION_EMAIL: str = Field(default="")
    FERNET_KEYS: list[Any] = Field(
        default_factory=lambda: ["DUMMY KEY CHANGE BEFORE GOING TO PRODUCTION"]
    )
    FILE_UPLOAD_STORAGE_BUCKET_NAME: str = Field(
        default="SET-ME-PLEASE (ex. bucket-name)"
    )
    FILE_UPLOAD_STORAGE_PREFIX: str = Field(default="submissions_attachments")
    FINANCIAL_REPORTS: dict[str, Any] = Field(
        default_factory=lambda: {
            "STORAGE_TYPE": "localfs",
            "BUCKET": None,
            "ROOT_PATH": "sandbox",
        }
    )
    FIREBASE_APP: Any = Field(default=None)  # TODO: refine type
    FIREBASE_CREDENTIALS: Any = Field(default=None)  # TODO: refine type
    FIREBASE_CREDENTIALS_PATH: Any = Field(default=None)  # TODO: refine type
    GENERATE_PROFILE_SCORES: bool = Field(default=False)
    GEOIP_PATH: str = Field(
        default=Path(
            "/openedx/edx-platform/common/static/data/geoip/GeoLite2-Country.mmdb"
        )
    )
    GOOGLE_ANALYTICS_ACCOUNT: Any = Field(default=None)  # TODO: refine type
    GRADES_DOWNLOAD: dict[str, Any] = Field(
        default_factory=lambda: {
            "STORAGE_CLASS": "django.core.files.storage.FileSystemStorage",
            "STORAGE_KWARGS": {"location": "/tmp/edx-s3/grades"},
            "STORAGE_TYPE": None,
            "BUCKET": None,
            "ROOT_PATH": None,
        }
    )
    HEARTBEAT_CELERY_TIMEOUT: int = Field(default=5)
    HEARTBEAT_CHECKS: list[Any] = Field(
        default_factory=lambda: [
            "openedx.core.djangoapps.heartbeat.default_checks.check_modulestore",
            "openedx.core.djangoapps.heartbeat.default_checks.check_database",
        ]
    )
    HEARTBEAT_EXTENDED_CHECKS: tuple[Any, ...] = Field(
        default=("openedx.core.djangoapps.heartbeat.default_checks.check_celery",)
    )  # TODO: refine type
    HELP_TOKENS_BOOKS: dict[str, Any] = Field(
        default_factory=lambda: {
            "learner": "https://docs.openedx.org/en/latest/learners",
            "course_author": "https://docs.openedx.org/en/latest/educators",
        }
    )
    HELP_TOKENS_LANGUAGE_CODE: str = Field(default="en")
    HELP_TOKENS_VERSION: str = Field(default="latest")
    HTTPS: str = Field(default="on")
    ICP_LICENSE: Any = Field(default=None)  # TODO: refine type
    ICP_LICENSE_INFO: dict[str, Any] = Field(default_factory=lambda: {})
    IDA_LOGOUT_URI_LIST: list[Any] = Field(default_factory=lambda: [])
    ID_VERIFICATION_SUPPORT_LINK: str = Field(default="")
    INTEGRATED_CHANNELS_API_CHUNK_TRANSMISSION_LIMIT: dict[str, Any] = Field(
        default_factory=lambda: {}
    )
    JWT_AUTH: dict[str, Any] = Field(
        default=None
    )  # OPAQUE: original dict value is not serialisable
    LANGUAGES: list[Any] = Field(
        default_factory=lambda: [
            ("en", "English"),
            ("rtl", "Right-to-Left Test Language"),
            ("eo", "Dummy Language (Esperanto)"),
            ("am", "አማርኛ"),
            ("ar", "العربية"),
            ("az", "azərbaycanca"),
            ("bg-bg", "български (България)"),
            ("bn-bd", "বাংলা (বাংলাদেশ)"),
            ("bn-in", "বাংলা (ভারত)"),
            ("bs", "bosanski"),
            ("ca", "Català"),
            ("ca@valencia", "Català (València)"),
            ("cs", "Čeština"),
            ("cy", "Cymraeg"),
            ("da", "dansk"),
            ("de-de", "Deutsch (Deutschland)"),
            ("el", "Ελληνικά"),
            ("en-uk", "English (United Kingdom)"),
            ("en@lolcat", "LOLCAT English"),
            ("en@pirate", "Pirate English"),
            ("es-419", "Español (Latinoamérica)"),
            ("es-ar", "Español (Argentina)"),
            ("es-ec", "Español (Ecuador)"),
            ("es-es", "Español (España)"),
            ("es-mx", "Español (México)"),
            ("es-pe", "Español (Perú)"),
            ("et-ee", "Eesti (Eesti)"),
            ("eu-es", "euskara (Espainia)"),
            ("fa", "فارسی"),
            ("fa-ir", "فارسی (ایران)"),
            ("fi-fi", "Suomi (Suomi)"),
            ("fil", "Filipino"),
            ("fr", "Français"),
            ("gl", "Galego"),
            ("gu", "ગુજરાતી"),
            ("he", "עברית"),
            ("hi", "हिन्दी"),
            ("hr", "hrvatski"),
            ("hu", "magyar"),
            ("hy-am", "Հայերեն (Հայաստան)"),
            ("id", "Bahasa Indonesia"),
            ("it-it", "Italiano (Italia)"),
            ("ja-jp", "日本語 (日本)"),
            ("kk-kz", "қазақ тілі (Қазақстан)"),
            ("km-kh", "ភាសាខ្មែរ (កម្ពុជា)"),
            ("kn", "ಕನ್ನಡ"),
            ("ko-kr", "한국어 (대한민국)"),
            ("lt-lt", "Lietuvių (Lietuva)"),
            ("ml", "മലയാളം"),
            ("mn", "Монгол хэл"),
            ("mr", "मराठी"),
            ("ms", "Bahasa Melayu"),
            ("nb", "Norsk bokmål"),
            ("ne", "नेपाली"),
            ("nl-nl", "Nederlands (Nederland)"),
            ("or", "ଓଡ଼ିଆ"),
            ("pl", "Polski"),
            ("pt-br", "Português (Brasil)"),
            ("pt-pt", "Português (Portugal)"),
            ("ro", "română"),
            ("ru", "Русский"),
            ("si", "සිංහල"),
            ("sk", "Slovenčina"),
            ("sl", "Slovenščina"),
            ("sq", "shqip"),
            ("sr", "Српски"),
            ("sv", "svenska"),
            ("sw", "Kiswahili"),
            ("ta", "தமிழ்"),
            ("te", "తెలుగు"),
            ("th", "ไทย"),
            ("tr-tr", "Türkçe (Türkiye)"),
            ("uk", "Українська"),
            ("ur", "اردو"),
            ("vi", "Tiếng Việt"),
            ("uz", "Ўзбек"),
            ("zh-cn", "中文 (简体)"),
            ("zh-hk", "中文 (香港)"),
            ("zh-tw", "中文 (台灣)"),
        ]
    )
    LANGUAGES_BIDI: tuple[Any, ...] = Field(
        default=("he", "ar", "fa", "ur", "fa-ir", "rtl")
    )  # TODO: refine type
    LANGUAGE_CODE: str = Field(default="en")
    LANGUAGE_COOKIE_NAME: str = Field(default="openedx-language-preference")
    LANGUAGE_DICT: dict[str, Any] = Field(
        default_factory=lambda: {
            "en": "English",
            "rtl": "Right-to-Left Test Language",
            "eo": "Dummy Language (Esperanto)",
            "am": "አማርኛ",
            "ar": "العربية",
            "az": "azərbaycanca",
            "bg-bg": "български (България)",
            "bn-bd": "বাংলা (বাংলাদেশ)",
            "bn-in": "বাংলা (ভারত)",
            "bs": "bosanski",
            "ca": "Català",
            "ca@valencia": "Català (València)",
            "cs": "Čeština",
            "cy": "Cymraeg",
            "da": "dansk",
            "de-de": "Deutsch (Deutschland)",
            "el": "Ελληνικά",
            "en-uk": "English (United Kingdom)",
            "en@lolcat": "LOLCAT English",
            "en@pirate": "Pirate English",
            "es-419": "Español (Latinoamérica)",
            "es-ar": "Español (Argentina)",
            "es-ec": "Español (Ecuador)",
            "es-es": "Español (España)",
            "es-mx": "Español (México)",
            "es-pe": "Español (Perú)",
            "et-ee": "Eesti (Eesti)",
            "eu-es": "euskara (Espainia)",
            "fa": "فارسی",
            "fa-ir": "فارسی (ایران)",
            "fi-fi": "Suomi (Suomi)",
            "fil": "Filipino",
            "fr": "Français",
            "gl": "Galego",
            "gu": "ગુજરાતી",
            "he": "עברית",
            "hi": "हिन्दी",
            "hr": "hrvatski",
            "hu": "magyar",
            "hy-am": "Հայերեն (Հայաստան)",
            "id": "Bahasa Indonesia",
            "it-it": "Italiano (Italia)",
            "ja-jp": "日本語 (日本)",
            "kk-kz": "қазақ тілі (Қазақстан)",
            "km-kh": "ភាសាខ្មែរ (កម្ពុជា)",
            "kn": "ಕನ್ನಡ",
            "ko-kr": "한국어 (대한민국)",
            "lt-lt": "Lietuvių (Lietuva)",
            "ml": "മലയാളം",
            "mn": "Монгол хэл",
            "mr": "मराठी",
            "ms": "Bahasa Melayu",
            "nb": "Norsk bokmål",
            "ne": "नेपाली",
            "nl-nl": "Nederlands (Nederland)",
            "or": "ଓଡ଼ିଆ",
            "pl": "Polski",
            "pt-br": "Português (Brasil)",
            "pt-pt": "Português (Portugal)",
            "ro": "română",
            "ru": "Русский",
            "si": "සිංහල",
            "sk": "Slovenčina",
            "sl": "Slovenščina",
            "sq": "shqip",
            "sr": "Српски",
            "sv": "svenska",
            "sw": "Kiswahili",
            "ta": "தமிழ்",
            "te": "తెలుగు",
            "th": "ไทย",
            "tr-tr": "Türkçe (Türkiye)",
            "uk": "Українська",
            "ur": "اردو",
            "vi": "Tiếng Việt",
            "uz": "Ўзбек",
            "zh-cn": "中文 (简体)",
            "zh-hk": "中文 (香港)",
            "zh-tw": "中文 (台灣)",
        }
    )
    LEARNER_ENGAGEMENT_PROMPT_FOR_ACTIVE_CONTRACT: str = Field(default="")
    LEARNER_ENGAGEMENT_PROMPT_FOR_NON_ACTIVE_CONTRACT: str = Field(default="")
    LEARNER_HOME_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    LEARNER_PROGRESS_PROMPT_FOR_ACTIVE_CONTRACT: str = Field(default="")
    LEARNER_PROGRESS_PROMPT_FOR_NON_ACTIVE_CONTRACT: str = Field(default="")
    LEARNING_MICROFRONTEND_URL: Any = Field(default=None)  # TODO: refine type
    LICENSING: bool = Field(default=False)
    LITE_LLM_REQUEST_TIMEOUT: int = Field(default=300)
    LLM_HTMLXML_MAX_CHARS_PER_REQUEST: int = Field(default=6000)
    LLM_HTMLXML_MAX_CHARS_PER_UNIT: int = Field(default=800)
    LLM_HTMLXML_MAX_UNITS_PER_REQUEST: int = Field(default=40)
    LLM_TRANSLATION_CACHE_MAX_ENTRIES: int = Field(default=5000)
    LMS_ENROLLMENT_API_PATH: str = Field(default="/api/enrollment/v1/")
    LOCALE_PATHS: list[Any] = Field(
        default_factory=lambda: [Path("/openedx/edx-platform/conf/locale")]
    )
    LOCAL_LOGLEVEL: str = Field(default="INFO")
    LOGGING_ENV: str = Field(default="sandbox")
    LOGIN_AND_REGISTER_FORM_RATELIMIT: str = Field(default="100/5m")
    LOGIN_ISSUE_SUPPORT_LINK: str = Field(default="")
    LOGIN_REDIRECT_WHITELIST: list[Any] = Field(default_factory=lambda: [])
    LOGISTRATION_API_RATELIMIT: str = Field(default="20/m")
    LOGISTRATION_PER_EMAIL_RATELIMIT_RATE: str = Field(default="30/5m")
    LOGISTRATION_RATELIMIT_RATE: str = Field(default="100/5m")
    LOGO_IMAGE_EXTRA_TEXT: str = Field(default="")
    LOGO_TRADEMARK_URL: Any = Field(default=None)  # TODO: refine type
    LOGO_URL: Any = Field(default=None)  # TODO: refine type
    LOGO_URL_PNG: Any = Field(default=None)  # TODO: refine type
    LOG_DIR: str = Field(default="/edx/var/log/edx")
    MANAGERS: list[Any] = Field(default_factory=lambda: [])
    MARKETING_EMAILS_OPT_IN: bool = Field(default=False)
    MARK_LIBRARY_CONTENT_BLOCK_COMPLETE_ON_VIEW: bool = Field(default=False)
    MAX_FAILED_LOGIN_ATTEMPTS_ALLOWED: int = Field(default=6)
    MAX_FAILED_LOGIN_ATTEMPTS_LOCKOUT_PERIOD_SECS: int = Field(default=1800)
    MEDIA_ROOT: str = Field(default="/edx/var/edxapp/media/")
    MEDIA_URL: str = Field(default="/media/")
    MESSAGE_STORAGE: str = Field(
        default="django.contrib.messages.storage.session.SessionStorage"
    )
    MILESTONES_APP: bool = Field(default=False)
    MIT_LEARN_AI_API_URL: str = Field(default="")
    MIT_LEARN_AI_XBLOCK_CHAT_API_TOKEN: str = Field(default="")
    MIT_LEARN_AI_XBLOCK_CHAT_API_URL: str = Field(default="")
    MIT_LEARN_AI_XBLOCK_CHAT_RATING_URL: str = Field(default="")
    MIT_LEARN_AI_XBLOCK_PROBLEM_SET_LIST_URL: str = Field(default="")
    MIT_LEARN_AI_XBLOCK_TUTOR_CHAT_API_URL: str = Field(default="")
    MIT_LEARN_API_BASE_URL: str = Field(default="")
    MIT_LEARN_SUMMARY_FLASHCARD_URL: str = Field(default="")
    MKTG_URLS: dict[str, Any] = Field(default_factory=lambda: {})
    MKTG_URL_LINK_MAP: dict[str, Any] = Field(
        default_factory=lambda: {
            "ABOUT": "about",
            "CONTACT": "contact",
            "FAQ": "help",
            "COURSES": "courses",
            "ROOT": "root",
            "TOS": "tos",
            "HONOR": "honor",
            "TOS_AND_HONOR": "edx-terms-service",
            "PRIVACY": "privacy",
            "PRESS": "press",
            "BLOG": "blog",
            "DONATE": "donate",
            "SITEMAP.XML": "sitemap_xml",
            "WHAT_IS_VERIFIED_CERT": "verified-certificate",
        }
    )
    MKTG_URL_OVERRIDES: dict[str, Any] = Field(default_factory=lambda: {})
    NOTIFICATIONS_DEFAULT_FROM_EMAIL: str = Field(default="no-reply@example.com")
    NOTIFICATIONS_EXPIRY: int = Field(default=60)
    NOTIFICATION_APPS_OVERRIDE: dict[str, Any] = Field(default_factory=lambda: {})
    NOTIFICATION_CREATION_BATCH_SIZE: int = Field(default=76)
    NOTIFICATION_DAILY_DIGEST_DELIVERY_HOUR: int = Field(default=17)
    NOTIFICATION_DAILY_DIGEST_DELIVERY_MINUTE: int = Field(default=0)
    NOTIFICATION_DIGEST_LOGO: str = Field(
        default="https://edx-cdn.org/v3/default/logo.png"
    )
    NOTIFICATION_IMMEDIATE_EMAIL_BUFFER_MINUTES: int = Field(default=15)
    NOTIFICATION_TYPES_OVERRIDE: dict[str, Any] = Field(default_factory=lambda: {})
    NOTIFICATION_TYPE_ICONS: dict[str, Any] = Field(default_factory=lambda: {})
    NOTIFICATION_WEEKLY_DIGEST_DELIVERY_DAY: int = Field(default=0)
    NOTIFICATION_WEEKLY_DIGEST_DELIVERY_HOUR: int = Field(default=17)
    NOTIFICATION_WEEKLY_DIGEST_DELIVERY_MINUTE: int = Field(default=0)
    NOTIFY_CREDENTIALS_FREQUENCY: int = Field(default=14400)
    OAUTH2_PROVIDER_APPLICATION_MODEL: str = Field(
        default="oauth2_provider.Application"
    )
    OL_OPENEDX_COURSE_SYNC_SERVICE_WORKER_USERNAME: str = Field(default="")
    ONE_CLICK_UNSUBSCRIBE_RATE_LIMIT: str = Field(default="100/m")
    OPENAPI_CACHE_TIMEOUT: int = Field(default=3600)
    OPENEDX_AUTHZ_CONTENT_LIBRARY_MODEL: str = Field(
        default="content_libraries.ContentLibrary"
    )
    OPENEDX_AUTHZ_COURSE_OVERVIEW_MODEL: str = Field(
        default="course_overviews.CourseOverview"
    )
    OPENEDX_ROOT: str = Field(default=Path("/openedx/edx-platform/openedx"))
    OPEN_EDX_FILTERS_CONFIG: dict[str, Any] = Field(
        default_factory=lambda: {
            "org.openedx.learning.xblock.render.started.v1": {
                "pipeline": [
                    "ol_openedx_chat_xblock.filters.DisableMathJaxForOLChatBlock"
                ],
                "fail_silently": False,
            }
        }
    )
    OPTIMIZELY_FULLSTACK_SDK_KEY: Any = Field(default=None)  # TODO: refine type
    OPTIMIZELY_PROJECT_ID: Any = Field(default=None)  # TODO: refine type
    OPTIONAL_APPS: list[Any] = Field(
        default_factory=lambda: [
            (
                "problem_builder",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            ("edx_sga", None),
            (
                "submissions",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment.assessment",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment.fileupload",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment.staffgrader",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment.workflow",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "openassessment.xblock",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            (
                "edxval",
                "openedx.core.djangoapps.content.course_overviews.apps.CourseOverviewsConfig",
            ),
            ("integrated_channels.integrated_channel", None),
            ("integrated_channels.degreed", None),
            ("integrated_channels.degreed2", None),
            ("integrated_channels.sap_success_factors", None),
            ("integrated_channels.cornerstone", None),
            ("integrated_channels.xapi", None),
            ("integrated_channels.blackboard", None),
            ("integrated_channels.canvas", None),
            ("integrated_channels.moodle", None),
            ("channel_integrations.integrated_channel", None),
            ("channel_integrations.degreed2", None),
            ("channel_integrations.sap_success_factors", None),
            ("channel_integrations.cornerstone", None),
            ("channel_integrations.xapi", None),
            ("channel_integrations.blackboard", None),
            ("channel_integrations.canvas", None),
            ("channel_integrations.moodle", None),
            ("django_object_actions", None),
        ]
    )
    OPTIONAL_FIELD_API_RATELIMIT: str = Field(default="10/h")
    ORA_SETTINGS_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/how-tos/course_development/exercise_tools/Manage_ORA_Assignment.html"
    )
    P3P_HEADER: str = Field(default='CP="Open EdX does not have a P3P policy."')
    PARENTAL_CONSENT_AGE_LIMIT: int = Field(default=13)
    PARTNER_SUPPORT_EMAIL: str = Field(default="")
    PASSWORD_POLICY_COMPLIANCE_API_TIMEOUT: int = Field(default=5)
    PASSWORD_POLICY_COMPLIANCE_ROLLOUT_CONFIG: dict[str, Any] = Field(
        default_factory=lambda: {
            "ENFORCE_COMPLIANCE_ON_LOGIN": False,
            "STAFF_USER_COMPLIANCE_DEADLINE": None,
            "ELEVATED_PRIVILEGE_USER_COMPLIANCE_DEADLINE": None,
            "GENERAL_USER_COMPLIANCE_DEADLINE": None,
        }
    )
    PASSWORD_RESET_EMAIL_RATE: str = Field(default="2/h")
    PASSWORD_RESET_IP_RATE: str = Field(default="1/m")
    PASSWORD_RESET_SUPPORT_LINK: str = Field(default="")
    PAYMENT_SUPPORT_EMAIL: str = Field(default="billing@example.com")
    PLATFORM_DESCRIPTION: Any = Field(
        default=None
    )  # DERIVED: computed from other settings — add a @model_validator to reproduce
    PLATFORM_FACEBOOK_ACCOUNT: str = Field(
        default="http://www.facebook.com/YourPlatformFacebookAccount"
    )
    PLATFORM_NAME: Any = Field(
        default=None
    )  # DERIVED: computed from other settings — add a @model_validator to reproduce
    PLATFORM_TWITTER_ACCOUNT: str = Field(default="@YourPlatformTwitterAccount")
    POLICY_CHANGE_TASK_RATE_LIMIT: str = Field(default="900/h")
    PREPEND_LOCALE_PATHS: list[Any] = Field(default_factory=lambda: [])
    PRESS_EMAIL: str = Field(default="press@example.com")
    PROCTORING_BACKENDS: dict[str, Any] = Field(
        default_factory=lambda: {"DEFAULT": "null", "null": {}}
    )
    PROCTORING_SETTINGS: dict[str, Any] = Field(default_factory=lambda: {})
    PROFILE_IMAGE_BACKEND: dict[str, Any] = Field(
        default_factory=lambda: {
            "class": "openedx.core.storage.OverwriteStorage",
            "options": {
                "location": "/edx/var/edxapp/media/profile-images/",
                "base_url": "/media/profile-images/",
            },
        }
    )
    PROFILE_IMAGE_DEFAULT_FILENAME: str = Field(default="images/profiles/default")
    PROFILE_IMAGE_DEFAULT_FILE_EXTENSION: str = Field(default="png")
    PROFILE_IMAGE_HASH_SEED: str = Field(default="placeholder_secret_key")
    PROFILE_IMAGE_MAX_BYTES: int = Field(default=1048576)
    PROFILE_IMAGE_MIN_BYTES: int = Field(default=100)
    PROFILE_IMAGE_SIZES_MAP: dict[str, Any] = Field(
        default_factory=lambda: {"full": 500, "large": 120, "medium": 50, "small": 30}
    )
    PROGRESS_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/references/data/progress_page.html"
    )
    REDIRECT_CACHE_KEY_PREFIX: str = Field(default="redirects")
    REDIRECT_CACHE_TIMEOUT: Any = Field(default=None)  # TODO: refine type
    REGISTRATION_EMAIL_PATTERNS_ALLOWED: Any = Field(default=None)  # TODO: refine type
    REGISTRATION_RATELIMIT: str = Field(default="60/7d")
    REGISTRATION_VALIDATION_RATELIMIT: str = Field(default="30/7d")
    REPO_ROOT: str = Field(default=Path("/openedx/edx-platform"))
    REQUIRE_BASE_URL: str = Field(default="./")
    REQUIRE_DEBUG: bool = Field(default=False)
    RESET_PASSWORD_API_RATELIMIT: str = Field(default="30/7d")
    RESET_PASSWORD_TOKEN_VALIDATE_API_RATELIMIT: str = Field(default="30/7d")
    RESTRICT_AUTOMATIC_AUTH: bool = Field(default=True)
    RETIRED_EMAIL_DOMAIN: str = Field(default="retired.invalid")
    RETIRED_EMAIL_FMT: str = Field(default="retired__user_{}@retired.invalid")
    RETIRED_EMAIL_PREFIX: str = Field(default="retired__user_")
    RETIRED_USERNAME_FMT: str = Field(default="retired__user_{}")
    RETIRED_USERNAME_PREFIX: str = Field(default="retired__user_")
    RETIRED_USER_SALTS: list[Any] = Field(default_factory=lambda: ["abc", "123"])
    RETIREMENT_SERVICE_WORKER_USERNAME: str = Field(default="RETIREMENT_SERVICE_USER")
    RETIREMENT_STATES: list[Any] = Field(
        default_factory=lambda: [
            "PENDING",
            "LOCKING_ACCOUNT",
            "LOCKING_COMPLETE",
            "RETIRING_FORUMS",
            "FORUMS_COMPLETE",
            "RETIRING_EMAIL_LISTS",
            "EMAIL_LISTS_COMPLETE",
            "RETIRING_ENROLLMENTS",
            "ENROLLMENTS_COMPLETE",
            "RETIRING_NOTES",
            "NOTES_COMPLETE",
            "RETIRING_LMS",
            "LMS_COMPLETE",
            "ERRORED",
            "ABORTED",
            "COMPLETE",
        ]
    )
    RETRY_ACTIVATION_EMAIL_MAX_ATTEMPTS: int = Field(default=5)
    RETRY_ACTIVATION_EMAIL_TIMEOUT: float = Field(default=0.5)
    SAML_METADATA_URL_ALLOW_PRIVATE_IPS: bool = Field(default=False)
    SEARCH_ENGINE: Any = Field(default=None)  # TODO: refine type
    SECONDARY_EMAIL_RATE_LIMIT: str = Field(default="")
    SECRET_KEY: str = Field(default="dev key")
    SECURE_PROXY_SSL_HEADER: tuple[Any, ...] = Field(
        default=("HTTP_X_FORWARDED_PROTO", "https")
    )  # TODO: refine type
    SERVER_EMAIL: str = Field(default="devops@example.com")
    SESSION_COOKIE_DOMAIN: Any = Field(default=None)  # TODO: refine type
    SESSION_COOKIE_HTTPONLY: bool = Field(default=True)
    SESSION_COOKIE_NAME: str = Field(default="sessionid")
    SESSION_COOKIE_SECURE: bool = Field(default=False)
    SESSION_ENGINE: str = Field(default="django.contrib.sessions.backends.cache")
    SESSION_INACTIVITY_TIMEOUT_IN_SECONDS: Any = Field(
        default=None
    )  # TODO: refine type
    SESSION_SAVE_EVERY_REQUEST: bool = Field(default=False)
    SESSION_SERIALIZER: str = Field(
        default="openedx.core.lib.session_serializers.PickleSerializer"
    )
    SHARED_COOKIE_DOMAIN: Any = Field(default=None)  # TODO: refine type
    SHIBBOLETH_DOMAIN_PREFIX: str = Field(default="shib:")
    SHOW_ACCOUNT_ACTIVATION_CTA: bool = Field(default=False)
    SHOW_ACTIVATE_CTA_POPUP_COOKIE_NAME: str = Field(
        default="show-account-activation-popup"
    )
    SHOW_BUMPER_PERIODICITY: int = Field(default=604800)
    SHOW_FOOTER_LANGUAGE_SELECTOR: bool = Field(default=False)
    SHOW_HEADER_LANGUAGE_SELECTOR: bool = Field(default=False)
    SHOW_REGISTRATION_LINKS: bool = Field(default=True)
    SIMPLE_HISTORY_DATE_INDEX: bool = Field(default=False)
    SITE_ID: int = Field(default=1)
    SITE_NAME: str = Field(default="localhost")
    SKIP_RATE_LIMIT_ON_ACCOUNT_AFTER_DAYS: int = Field(default=0)
    SOCIAL_AUTH_SAML_SP_PRIVATE_KEY: str = Field(default="")
    SOCIAL_AUTH_SAML_SP_PRIVATE_KEY_DICT: dict[str, Any] = Field(
        default_factory=lambda: {}
    )
    SOCIAL_AUTH_SAML_SP_PUBLIC_CERT: str = Field(default="")
    SOCIAL_AUTH_SAML_SP_PUBLIC_CERT_DICT: dict[str, Any] = Field(
        default_factory=lambda: {}
    )
    SOCIAL_MEDIA_FOOTER_ACE_URLS: dict[str, Any] = Field(
        default_factory=lambda: {
            "reddit": "http://www.reddit.com/r/edx",
            "twitter": "https://twitter.com/edXOnline",
            "linkedin": "http://www.linkedin.com/company/edx",
            "facebook": "http://www.facebook.com/EdxOnline",
        }
    )
    SOCIAL_MEDIA_LOGO_URLS: dict[str, Any] = Field(
        default_factory=lambda: {
            "reddit": "http://email-media.s3.amazonaws.com/edX/2021/social_5_reddit.png",
            "twitter": "http://email-media.s3.amazonaws.com/edX/2021/social_2_twitter.png",
            "linkedin": "http://email-media.s3.amazonaws.com/edX/2021/social_3_linkedin.png",
            "facebook": "http://email-media.s3.amazonaws.com/edX/2021/social_1_fb.png",
        }
    )
    SOCIAL_SHARING_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "CUSTOM_COURSE_URLS": False,
            "DASHBOARD_FACEBOOK": False,
            "CERTIFICATE_FACEBOOK": False,
            "CERTIFICATE_TWITTER": False,
            "DASHBOARD_TWITTER": False,
            "FACEBOOK_BRAND": None,
            "CERTIFICATE_FACEBOOK_TEXT": None,
            "TWITTER_BRAND": None,
            "CERTIFICATE_TWITTER_TEXT": None,
            "DASHBOARD_TWITTER_TEXT": None,
        }
    )
    SOFTWARE_SECURE_REQUEST_RETRY_DELAY: int = Field(default=3600)
    SOFTWARE_SECURE_RETRY_MAX_ATTEMPTS: int = Field(default=6)
    STATICFILES_DIRS: list[Any] = Field(
        default_factory=lambda: [
            Path("/openedx/edx-platform/common/static"),
            Path("/openedx/edx-platform/lms/static"),
            Path("/openedx/edx-platform/node_modules/@edx"),
            Path("/openedx/edx-platform/xmodule/static"),
        ]
    )
    STATICFILES_FINDERS: list[Any] = Field(
        default_factory=lambda: [
            "openedx.core.djangoapps.theming.finders.ThemeFilesFinder",
            "django.contrib.staticfiles.finders.FileSystemFinder",
            "django.contrib.staticfiles.finders.AppDirectoriesFinder",
            "openedx.core.lib.xblock_pipeline.finder.XBlockPipelineFinder",
            "pipeline.finders.PipelineFinder",
        ]
    )
    STATICFILES_STORAGE_KWARGS: dict[str, Any] = Field(default_factory=lambda: {})
    STATICI18N_FILENAME_FUNCTION: str = Field(
        default="statici18n.utils.legacy_filename"
    )
    STATICI18N_OUTPUT_DIR: str = Field(default="js/i18n")
    STATIC_ROOT_BASE: Any = Field(default=None)  # TODO: refine type
    STATIC_URL_BASE: Any = Field(default=None)  # TODO: refine type
    STORAGES: dict[str, Any] = Field(
        default_factory=lambda: {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "openedx.core.storage.ProductionStorage"},
        }
    )
    SUPPORT_SITE_LINK: str = Field(default="")
    SWIFT_AUTH_URL: Any = Field(default=None)  # TODO: refine type
    SWIFT_AUTH_VERSION: Any = Field(default=None)  # TODO: refine type
    SWIFT_KEY: Any = Field(default=None)  # TODO: refine type
    SWIFT_REGION_NAME: Any = Field(default=None)  # TODO: refine type
    SWIFT_TEMP_URL_DURATION: int = Field(default=1800)
    SWIFT_TEMP_URL_KEY: Any = Field(default=None)  # TODO: refine type
    SWIFT_TENANT_ID: Any = Field(default=None)  # TODO: refine type
    SWIFT_TENANT_NAME: Any = Field(default=None)  # TODO: refine type
    SWIFT_USERNAME: Any = Field(default=None)  # TODO: refine type
    SYSLOG_SERVER: str = Field(default="")
    SYSTEM_WIDE_ROLE_CLASSES: list[Any] = Field(default_factory=lambda: [])
    TEAMS_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/navigation/advanced_features.html#use-teams-in-your-course"
    )
    TECH_SUPPORT_EMAIL: str = Field(default="technical@example.com")
    TEXTBOOKS_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/how-tos/course_development/manage_textbooks.html"
    )
    TIME_ZONE: str = Field(default="UTC")
    TRACKING_BACKENDS: dict[str, Any] = Field(
        default_factory=lambda: {
            "logger": {
                "ENGINE": "common.djangoapps.track.backends.logger.LoggerBackend",
                "OPTIONS": {"name": "tracking"},
            }
        }
    )
    TRACKING_IGNORE_URL_PATTERNS: list[Any] = Field(
        default_factory=lambda: [
            "^/event",
            "^/login",
            "^/heartbeat",
            "^/segmentio/event",
            "^/performance",
        ]
    )
    TRACK_MAX_EVENT: int = Field(default=50000)
    TRANSCRIPT_LANG_CACHE_TIMEOUT: int = Field(default=86400)
    TRANSLATE_FILE_TASK_LIMITS: dict[str, Any] = Field(
        default_factory=lambda: {
            "soft_time_limit": 1740,
            "time_limit": 1800,
            "max_retries": 1,
            "retry_countdown": 60,
        }
    )
    TRANSLATIONS_PROVIDERS: dict[str, Any] = Field(
        default_factory=lambda: {
            "default_provider": "mistral",
            "deepl": {"api_key": ""},
            "openai": {"api_key": "", "default_model": "gpt-5.2"},
            "gemini": {"api_key": "", "default_model": "gemini-3-pro-preview"},
            "mistral": {"api_key": "", "default_model": "mistral-large-latest"},
        }
    )
    UNIVERSITY_EMAIL: str = Field(default="university@example.com")
    USAGE_ID_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    USAGE_KEY_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    USERNAME_PATTERN: str = Field(
        default=None
    )  # OPAQUE: original str value is not serialisable
    USERNAME_REGEX_PARTIAL: str = Field(default="[\\w .@_+-]+")
    USERNAME_REPLACEMENT_WORKER: str = Field(default="REPLACE WITH VALID USERNAME")
    USE_EXTRACTED_ANNOTATABLE_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_DISCUSSION_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_HTML_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_LTI_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_POLL_QUESTION_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_PROBLEM_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_VIDEO_BLOCK: bool = Field(default=True)
    USE_EXTRACTED_WORD_CLOUD_BLOCK: bool = Field(default=True)
    USE_I18N: bool = Field(default=True)
    USE_TZ: bool = Field(default=True)
    VERIFY_STUDENT: dict[str, Any] = Field(
        default_factory=lambda: {"DAYS_GOOD_FOR": 365, "EXPIRING_SOON_WINDOW": 28}
    )
    VIDEO_CDN_URL: dict[str, Any] = Field(default_factory=lambda: {})
    VIDEO_IMAGE_MAX_AGE: int = Field(default=31536000)
    VIDEO_IMAGE_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "VIDEO_IMAGE_MAX_BYTES": 2097152,
            "VIDEO_IMAGE_MIN_BYTES": 2048,
            "STORAGE_KWARGS": {"location": "/edx/var/edxapp/media/"},
            "DIRECTORY_PREFIX": "video-images/",
            "BASE_URL": "/media/",
        }
    )
    VIDEO_TRANSCRIPTS_MAX_AGE: int = Field(default=31536000)
    VIDEO_TRANSCRIPTS_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "VIDEO_TRANSCRIPTS_MAX_BYTES": 3145728,
            "STORAGE_KWARGS": {"location": "/edx/var/edxapp/media/"},
            "DIRECTORY_PREFIX": "video-transcripts/",
            "BASE_URL": "/media/",
        }
    )
    WEBPACK_LOADER: dict[str, Any] = Field(
        default_factory=lambda: {
            "DEFAULT": {
                "BUNDLE_DIR_NAME": "bundles/",
                "STATS_FILE": Path("/openedx/staticfiles/webpack-stats.json"),
            },
            "WORKERS": {
                "BUNDLE_DIR_NAME": "bundles/",
                "STATS_FILE": Path("/openedx/staticfiles/webpack-worker-stats.json"),
            },
        }
    )
    WIKI_ENABLED: bool = Field(default=True)
    WIKI_HELP_URL: str = Field(
        default="https://docs.openedx.org/en/latest/educators/concepts/communication/about_course_wiki.html"
    )
    XBLOCK_EXTRA_MIXINS: tuple[Any, ...] = Field(default=())  # TODO: refine type
    XBLOCK_FIELD_DATA_WRAPPERS: tuple[Any, ...] = Field(default=())  # TODO: refine type
    XBLOCK_FS_STORAGE_BUCKET: Any = Field(default=None)  # TODO: refine type
    XBLOCK_FS_STORAGE_PREFIX: Any = Field(default=None)  # TODO: refine type
    XBLOCK_MIXINS: tuple[Any, ...] = Field(
        default=None
    )  # OPAQUE: original tuple value is not serialisable
    XBLOCK_RUNTIME_V2_EPHEMERAL_DATA_CACHE: str = Field(default="default")
    XBLOCK_SETTINGS: dict[str, Any] = Field(default_factory=lambda: {})
    XMODULE_ROOT: str = Field(default=Path("/openedx/edx-platform/xmodule"))
    XQUEUE_INTERFACE: dict[str, Any] = Field(
        default_factory=lambda: {
            "url": "http://localhost:18040",
            "basic_auth": ["edx", "edx"],
            "django_auth": {
                "username": "lms",
                "password": "password",  # pragma: allowlist secret
            },
        }
    )
    XQUEUE_WAITTIME_BETWEEN_REQUESTS: int = Field(default=5)
    X_FRAME_OPTIONS: str = Field(default="DENY")
    YOUTUBE: dict[str, Any] = Field(
        default=None
    )  # OPAQUE: original dict value is not serialisable
    YOUTUBE_API_KEY: str = Field(default="PUT_YOUR_API_KEY_HERE")
    ZENDESK_CUSTOM_FIELDS: dict[str, Any] = Field(default_factory=lambda: {})
    ZENDESK_GROUP_ID_MAPPING: dict[str, Any] = Field(default_factory=lambda: {})
    ZENDESK_OAUTH_ACCESS_TOKEN: Any = Field(default=None)  # TODO: refine type
    ZENDESK_URL: Any = Field(default=None)  # TODO: refine type
