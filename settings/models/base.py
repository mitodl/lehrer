"""Shared OL Kubernetes production settings base for both LMS and CMS.

Injected by the lehrer Dagger build into both:
  /openedx/edx-platform/lms/envs/mitol/ol_production_base.py
  /openedx/edx-platform/cms/envs/mitol/ol_production_base.py

Each service's ``ol_production.py`` imports from this module using a relative
import (``from .ol_production_base import OLBaseProductionSettings``), so the
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
   ``ALLOWED_HOSTS``, …).

3. **AqueductSettings field defaults** — typed snapshot of common.py
   defaults captured by ``manage.py generate_aqueduct_settings``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

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
        """
        return (
            env_settings,
            YamlConfigSettingsSource(
                settings_cls,
                yaml_file=_sorted_yaml_files(_SETTINGS_DIR),
                deep_merge=True,
            ),
        )

    # ------------------------------------------------------------------
    # Shared derived-setting validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _derive_celery_queue_names(self) -> "BaseProductionSettings":
        """Build CELERY_DEFAULT_* queue names from SERVICE_VARIANT."""
        if self.CELERY_DEFAULT_QUEUE is None:
            queue = f"edx.{self.SERVICE_VARIANT}.core.default"
            self.CELERY_DEFAULT_QUEUE = queue
            self.CELERY_DEFAULT_ROUTING_KEY = queue  # type: ignore[attr-defined]
            self.CELERY_DEFAULT_EXCHANGE = queue  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_broker_url(self) -> "BaseProductionSettings":
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
    def _derive_static_paths(self) -> "BaseProductionSettings":
        """Override STATIC_ROOT / STATIC_URL from *_BASE env-var variants."""
        if self.STATIC_ROOT_BASE:
            self.STATIC_ROOT = self.STATIC_ROOT_BASE  # type: ignore[assignment]
        if self.STATIC_URL_BASE:
            url = self.STATIC_URL_BASE
            if not url.endswith("/"):
                url += "/"
            self.STATIC_URL = url
        return self

    @model_validator(mode="after")
    def _derive_mako_module_dir(self) -> "BaseProductionSettings":
        """MAKO_MODULE_DIR lives in the system temp dir, keyed by service variant."""
        if self.MAKO_MODULE_DIR is None:
            self.MAKO_MODULE_DIR = os.path.join(  # type: ignore[assignment]
                tempfile.gettempdir(), f"edx_mako_{self.SERVICE_VARIANT}"
            )
        return self

    @model_validator(mode="after")
    def _derive_statici18n_root(self) -> "BaseProductionSettings":
        """STATICI18N_ROOT mirrors STATIC_ROOT."""
        if self.STATICI18N_ROOT is None and self.STATIC_ROOT:
            self.STATICI18N_ROOT = self.STATIC_ROOT
        return self

    @model_validator(mode="after")
    def _derive_language_settings(self) -> "BaseProductionSettings":
        """Populate LANGUAGE_COOKIE_NAME (from YAML alias) and LANGUAGE_DICT."""
        if self.LANGUAGE_COOKIE:
            self.LANGUAGE_COOKIE_NAME = self.LANGUAGE_COOKIE
        if self.LANGUAGES:
            self.LANGUAGE_DICT = dict(self.LANGUAGES)  # type: ignore[arg-type, attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_elastic_search_config(self) -> "BaseProductionSettings":
        """Use ELASTIC_SEARCH_CONFIG_ES7 as the authoritative search config."""
        if self.ELASTIC_SEARCH_CONFIG_ES7:
            object.__setattr__(
                self, "ELASTIC_SEARCH_CONFIG", self.ELASTIC_SEARCH_CONFIG_ES7
            )
        return self

    @model_validator(mode="after")
    def _derive_timezone(self) -> "BaseProductionSettings":
        """Align Django TIME_ZONE with Celery's timezone."""
        if self.CELERY_TIMEZONE:
            self.TIME_ZONE = self.CELERY_TIMEZONE
        return self

    @model_validator(mode="after")
    def _derive_logging(self) -> "BaseProductionSettings":
        """Build LOGGING from log-dir / environment / loglevel.

        All three inputs are flat scalars arriving as env vars; they are
        declared as explicit fields so pydantic populates them before this
        validator runs.
        """
        from openedx.core.lib.logsettings import get_logger_config  # noqa: PLC0415

        self.LOGGING = get_logger_config(  # type: ignore[attr-defined]
            self.LOG_DIR,
            logging_env=self.LOGGING_ENV,
            local_loglevel=self.LOCAL_LOGLEVEL,
            service_variant=self.SERVICE_VARIANT,
        )
        return self
