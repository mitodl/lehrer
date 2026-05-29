"""LMS production settings module — django-aqueduct entry point.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/lms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct

The typed pydantic model that backs this module lives alongside it at
``lms.envs.models.aqueduct`` (generated from the running platform via
``manage.py generate_aqueduct_settings``).  Update that model by running
the command inside the Docker image and committing the result to lehrer::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct \\
        python manage.py generate_aqueduct_settings \\
        --output lms/envs/models/aqueduct.py

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``lms.envs.models.aqueduct``.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings
from .models.base import BaseProductionSettings


class LMSProductionSettings(BaseProductionSettings, AqueductSettings):
    """Typed LMS production settings."""

    # YAML key from 82-lms-interpolated-config; Django setting is LMS_SEGMENT_KEY.
    SEGMENT_KEY: str | None = Field(default=None)

    # List from 81-lms-general-config; merged into AUTHENTICATION_BACKENDS below.
    THIRD_PARTY_AUTH_BACKENDS: list[str] | None = Field(default=None)

    @model_validator(mode="after")
    def _derive_urlconf(self) -> LMSProductionSettings:
        if getattr(self, "ROOT_URLCONF", None) is None:
            self.ROOT_URLCONF = "lms.urls"  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_segment_key(self) -> LMSProductionSettings:
        """Map env-var SEGMENT_KEY → Django LMS_SEGMENT_KEY."""
        if self.SEGMENT_KEY is not None:
            self.LMS_SEGMENT_KEY = self.SEGMENT_KEY  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_cors_credentials(self) -> LMSProductionSettings:
        """Enable CORS credentials when the relevant FEATURES flags are on."""
        features = getattr(self, "FEATURES", None) or {}
        if isinstance(features, dict) and (
            features.get("ENABLE_CORS_HEADERS")
            or features.get("ENABLE_CROSS_DOMAIN_CSRF_COOKIE")
        ):
            self.CORS_ALLOW_CREDENTIALS = True  # type: ignore[attr-defined]
        return self

    @model_validator(mode="after")
    def _derive_authentication_backends(self) -> LMSProductionSettings:
        """Prepend THIRD_PARTY_AUTH_BACKENDS before AUTHENTICATION_BACKENDS.

        Arrives via YAML (complex list type).  Deduplication preserves order.
        """
        if not self.THIRD_PARTY_AUTH_BACKENDS:
            return self
        features = getattr(self, "FEATURES", None) or {}
        if isinstance(features, dict) and not features.get(
            "ENABLE_THIRD_PARTY_AUTH", True
        ):
            return self
        existing = list(getattr(self, "AUTHENTICATION_BACKENDS", None) or [])
        self.AUTHENTICATION_BACKENDS = self.THIRD_PARTY_AUTH_BACKENDS + [  # type: ignore[attr-defined]
            b for b in existing if b not in self.THIRD_PARTY_AUTH_BACKENDS
        ]
        return self

    @model_validator(mode="after")
    def _derive_social_auth_clean_usernames(self) -> LMSProductionSettings:
        if getattr(self, "SOCIAL_AUTH_CLEAN_USERNAMES", None) is None:
            self.SOCIAL_AUTH_CLEAN_USERNAMES = False  # type: ignore[attr-defined]
        return self


configure_django_settings(LMSProductionSettings)
