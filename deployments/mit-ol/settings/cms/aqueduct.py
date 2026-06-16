"""CMS (Studio) production settings module — django-aqueduct entry point.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/cms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=cms.envs.aqueduct

The typed pydantic model that backs this module lives alongside it at
``cms.envs.models.aqueduct`` (generated from the running platform via
``manage.py generate_aqueduct_settings``).  Update that model by running
the command inside the Docker image and committing the result to lehrer::

    DJANGO_SETTINGS_MODULE=cms.envs.aqueduct \\
        python manage.py generate_aqueduct_settings \\
        --output cms/envs/models/aqueduct.py

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``cms.envs.models.aqueduct``.
"""

from __future__ import annotations

from pydantic import model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings
from .models.base import ProductionSettingsMixin


class CMSProductionSettings(ProductionSettingsMixin, AqueductSettings):
    """Typed CMS (Studio) production settings."""

    @model_validator(mode="after")
    def _derive_urlconf(self) -> CMSProductionSettings:
        if getattr(self, "ROOT_URLCONF", None) is None:
            self.ROOT_URLCONF = "cms.urls"  # type: ignore[attr-defined]
        return self


# base="cms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not carry, or that the generator could
# not serialise (rendered as None — e.g. opaque tuples/dicts), falls back to
# the real common.py value instead of vanishing to Django's empty default.
configure_django_settings(CMSProductionSettings, base="cms.envs.common")
