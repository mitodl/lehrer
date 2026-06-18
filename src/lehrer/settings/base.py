"""Shared production settings base for both LMS and CMS.

Injected by the lehrer Dagger build into both:
  /openedx/edx-platform/lms/envs/models/base.py
  /openedx/edx-platform/cms/envs/models/base.py

Each service's ``aqueduct.py`` imports from this module using a relative
import (``from .models.base import ProductionSettingsMixin``), so the
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
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class PathString(str):
    """String subclass that acts like a Path object for path-related operations.

    This bridges the gap between edx-platform code that expects Path objects
    (using the '/' operator) and code that expects string methods (like isdir()).
    """

    def __truediv__(self, other: str | Path) -> PathString:
        """Support the '/' operator for path joining."""
        return PathString(str(Path(self) / other))

    def __rtruediv__(self, other: str | Path) -> PathString:
        """Support reverse '/' operator."""
        return PathString(str(Path(other) / self))

    def is_dir(self) -> bool:
        """pathlib.Path style directory check."""
        return Path(self).is_dir()

    def isdir(self) -> bool:
        """os.path style directory check (backward compatibility)."""
        return self.is_dir()


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
    if not settings_dir:
        return []
    base = Path(settings_dir)
    if not base.is_dir():
        return []
    nested = sorted(base.glob("*/*.yaml"))
    return nested if nested else sorted(base.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Shared base settings model
# ---------------------------------------------------------------------------


class ProductionSettingsMixin(BaseSettings):
    """K8s deployment adapter mixed into LMS/CMS production settings classes.

    Provides three things that the generated ``AqueductSettings`` model does not:

    1. **Settings loading** — ``settings_customise_sources`` wires the two-tier
       env-var-then-YAML source pipeline used in Kubernetes deployments.

    2. **Type corrections** — re-declares fields whose generated types are too
       narrow (e.g. ``CELERY_BROKER_USE_SSL`` is ``bool`` in the generated model
       but carries a dict of SSL options in production).  Because this mixin
       appears before ``AqueductSettings`` in every subclass's MRO, its
       declarations win without touching the generated file.

    3. **Derived-setting validators** — ``@model_validator`` methods that
       reproduce the post-YAML logic previously scattered across
       ``lms/envs/production.py`` (``BROKER_URL``, ``LOGGING``, etc.).

    Usage::

        class LMSProductionSettings(ProductionSettingsMixin, AqueductSettings):
            ...

    Do *not* instantiate this class directly as ``DJANGO_SETTINGS_MODULE``.
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

    # MongoDB connection scalars — consumed by _derive_doc_store_config to build
    # DOC_STORE_CONFIG (a nested dict that can't arrive cleanly as a single env var).
    MONGODB_HOST: str = Field(default="")
    MONGODB_PORT: int = Field(default=27017)
    MONGODB_USER: str = Field(default="")
    MONGO_PASSWORD: str = Field(default="")  # key name used in openedx-secrets Secret
    MONGODB_DB: str = Field(default="edxapp")
    MONGODB_REPLICASET: str = Field(default="")
    MONGODB_AUTH_SOURCE: str = Field(default="")

    # MySQL connection scalars — consumed by _derive_databases to point the
    # nested DATABASES dict at the configured server. Host/port/user/db come from
    # the platform ConfigMap; DB_PASSWORD comes from the openedx-secrets Secret.
    MYSQL_HOST: str = Field(default="")
    MYSQL_PORT: int = Field(default=3306)
    MYSQL_USER: str = Field(default="")
    MYSQL_DB_NAME: str = Field(default="edxapp")
    DB_PASSWORD: str = Field(default="")

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
    def _derive_celery_queue_names(self) -> ProductionSettingsMixin:
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
    def _derive_broker_url(self) -> ProductionSettingsMixin:
        """Build BROKER_URL from CELERY_BROKER_* components.

        CELERY_BROKER_HOSTNAME and CELERY_BROKER_PASSWORD arrive as flat env
        vars (hostname from a ConfigMap, password from a Secret).
        """
        if self.CELERY_BROKER_TRANSPORT and not getattr(self, "BROKER_URL", None):
            user = quote(self.CELERY_BROKER_USER or "", safe="")
            password = quote(self.CELERY_BROKER_PASSWORD or "", safe="")
            self.BROKER_URL = (  # type: ignore[attr-defined]
                f"{self.CELERY_BROKER_TRANSPORT}://"
                f"{user}:{password}"
                f"@{self.CELERY_BROKER_HOSTNAME}/{self.CELERY_BROKER_VHOST}"
            )
        if isinstance(self.CELERY_BROKER_USE_SSL, dict):
            self.BROKER_USE_SSL = self.CELERY_BROKER_USE_SSL
        return self

    @model_validator(mode="after")
    def _derive_static_paths(self) -> ProductionSettingsMixin:
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
    def _derive_mako_module_dir(self) -> ProductionSettingsMixin:
        """MAKO_MODULE_DIR lives in the system temp dir, keyed by service variant."""
        if getattr(self, "MAKO_MODULE_DIR", None) is None:
            service_variant = getattr(self, "SERVICE_VARIANT", None)
            if service_variant:
                self.MAKO_MODULE_DIR = os.path.join(  # type: ignore[attr-defined]
                    tempfile.gettempdir(), f"edx_mako_{service_variant}"
                )
        return self

    @model_validator(mode="after")
    def _derive_statici18n_root(self) -> ProductionSettingsMixin:
        """STATICI18N_ROOT mirrors STATIC_ROOT."""
        if getattr(self, "STATICI18N_ROOT", None) is None:
            static_root = getattr(self, "STATIC_ROOT", None)
            if static_root:
                self.STATICI18N_ROOT = static_root  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_language_settings(self) -> ProductionSettingsMixin:
        """Populate LANGUAGE_COOKIE_NAME (from YAML alias) and LANGUAGE_DICT."""
        if self.LANGUAGE_COOKIE:
            self.LANGUAGE_COOKIE_NAME = self.LANGUAGE_COOKIE  # type: ignore[attr-defined]
        languages = getattr(self, "LANGUAGES", None)
        if languages:
            self.LANGUAGE_DICT = dict(languages)  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_elastic_search_config(self) -> ProductionSettingsMixin:
        """Use ELASTIC_SEARCH_CONFIG_ES7 as the authoritative search config."""
        if self.ELASTIC_SEARCH_CONFIG_ES7:
            self.ELASTIC_SEARCH_CONFIG = self.ELASTIC_SEARCH_CONFIG_ES7  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_doc_store_config(self) -> ProductionSettingsMixin:
        """Build DOC_STORE_CONFIG from MONGODB_* env vars.

        edx-platform's modulestore uses DOC_STORE_CONFIG as a nested dict, so it
        can't arrive cleanly as a single env var. The individual scalars come from
        the platform ConfigMap (host, port, user, db, replicaSet, authsource) and
        the openedx-secrets Secret (MONGO_PASSWORD).
        """
        if not self.MONGODB_HOST:
            return self
        config: dict = {
            "host": self.MONGODB_HOST,
            "port": self.MONGODB_PORT,
            "db": self.MONGODB_DB,
        }
        if self.MONGODB_USER:
            config["user"] = self.MONGODB_USER
        if self.MONGO_PASSWORD:
            config["password"] = self.MONGO_PASSWORD
        if self.MONGODB_AUTH_SOURCE:
            config["authsource"] = self.MONGODB_AUTH_SOURCE
        if self.MONGODB_REPLICASET:
            config["replicaSet"] = self.MONGODB_REPLICASET
        self.DOC_STORE_CONFIG = config  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_databases(self) -> ProductionSettingsMixin:
        """Point DATABASES at the configured MySQL server.

        edx-platform's DATABASES is a nested dict (default / read_replica /
        student_module_history) that can't arrive cleanly as a single env var.
        The connection scalars come from the platform ConfigMap (host, port,
        user, db name) and the openedx-secrets Secret (DB_PASSWORD); apply them
        to every alias. The student_module_history alias keeps its own NAME
        (edxapp_csmh); default and read_replica use MYSQL_DB_NAME.
        """
        if not self.MYSQL_HOST:
            return self
        for alias, db in self.DATABASES.items():
            db["HOST"] = self.MYSQL_HOST
            db["PORT"] = str(self.MYSQL_PORT)
            if self.MYSQL_USER:
                db["USER"] = self.MYSQL_USER
            if self.DB_PASSWORD:
                db["PASSWORD"] = self.DB_PASSWORD
            if self.MYSQL_DB_NAME and alias in ("default", "read_replica"):
                db["NAME"] = self.MYSQL_DB_NAME
        return self

    @model_validator(mode="after")
    def _fix_media_root(self) -> ProductionSettingsMixin:
        """Redirect the legacy /edx/ MEDIA_ROOT to a path that exists in the container.

        edx-platform common settings default MEDIA_ROOT to /edx/var/edxapp/media/,
        a path that does not exist (and cannot be created) in the lehrer container.
        Redirect it to /openedx/data/media/ unless an explicit override was supplied
        (e.g. via MEDIA_ROOT env var pointing to S3 or a PVC mount path).

        A field-level declaration in this mixin would not work: because
        AqueductSettings is a *subclass* of ProductionSettingsMixin (not a sibling),
        AqueductSettings.MEDIA_ROOT wins in the MRO. A model_validator runs after
        instantiation regardless of class hierarchy, so it reliably overrides the
        generated default without touching the generated file.
        """
        media_root = getattr(self, "MEDIA_ROOT", None)
        if media_root is None or str(media_root).startswith("/edx/"):
            self.MEDIA_ROOT = "/openedx/data/media/"  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_timezone(self) -> ProductionSettingsMixin:
        """Align Django TIME_ZONE with Celery's timezone."""
        celery_timezone = getattr(self, "CELERY_TIMEZONE", None)
        if celery_timezone:
            self.TIME_ZONE = celery_timezone  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_xblock_mixins(self) -> ProductionSettingsMixin:
        """Restore XBLOCK_MIXINS when it couldn't be serialised by aqueduct.

        The tuple-of-classes value is not JSON-serialisable, so aqueduct sets
        the Pydantic default to None.  Import the canonical value from
        openedx.core.lib.xblock_utils at runtime when no override is present.
        """
        if getattr(self, "XBLOCK_MIXINS", None) is None:
            from lms.envs.common import XBLOCK_MIXINS  # noqa: PLC0415

            self.XBLOCK_MIXINS = XBLOCK_MIXINS  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_logging(self) -> ProductionSettingsMixin:
        """Build LOGGING from log-dir / environment / loglevel.

        All three inputs are flat scalars arriving as env vars; they are
        declared as explicit fields so pydantic populates them before this
        validator runs.
        """
        from openedx.core.lib.logsettings import get_docker_logger_config  # noqa: PLC0415

        service_variant = getattr(self, "SERVICE_VARIANT", None) or "lms"
        self.LOGGING = get_docker_logger_config(  # type: ignore[attr-defined]
            self.LOG_DIR,
            logging_env=self.LOGGING_ENV,
            debug=(self.LOCAL_LOGLEVEL == "DEBUG"),
            service_variant=service_variant,
        )
        return self

    @model_validator(mode="after")
    def _convert_path_strings_to_path_objects(self) -> ProductionSettingsMixin:
        """Convert path-related settings to PathString objects.

        PathString is a str subclass that supports both the '/' operator
        (like Path) and string methods (like isdir()). This bridges
        edx-platform code that expects Path-like behavior.

        edx-platform code (e.g., xmodule/modulestore/api.py:get_python_locale_root)
        uses the '/' operator on these settings, while other code calls .isdir()
        as a string method. PathString supports both.
        """
        path_settings = [
            "REPO_ROOT",
            "COMMON_ROOT",
            "ENV_ROOT",
            "OPENEDX_ROOT",
            "XMODULE_ROOT",
            "COURSES_ROOT",
        ]
        for setting_name in path_settings:
            value = getattr(self, setting_name, None)
            if isinstance(value, str) and not isinstance(value, PathString):
                setattr(self, setting_name, PathString(value))  # type: ignore[attr-defined]
        return self
