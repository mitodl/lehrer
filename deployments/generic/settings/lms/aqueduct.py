"""LMS production settings module — django-aqueduct entry point.

Generic Open edX deployment — no operator-specific customizations.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/lms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``lms.envs.models.aqueduct``.
"""

from __future__ import annotations

from pydantic import model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings


class LMSProductionSettings(AqueductSettings):
    """Typed LMS production settings — generic Open edX deployment."""

    @model_validator(mode="after")
    def _derive_urlconf(self) -> LMSProductionSettings:
        if getattr(self, "ROOT_URLCONF", None) is None:
            self.ROOT_URLCONF = "lms.urls"  # type: ignore[attr-defined]
        return self


# base="lms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not carry, or that the generator could
# not serialise (rendered as None — e.g. opaque tuples/dicts), falls back to
# the real common.py value instead of vanishing to Django's empty default.
configure_django_settings(LMSProductionSettings, base="lms.envs.common")
