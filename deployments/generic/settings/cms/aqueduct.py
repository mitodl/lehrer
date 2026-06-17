"""CMS (Studio) production settings module — django-aqueduct entry point.

Generic Open edX deployment — no operator-specific customizations.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/cms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=cms.envs.aqueduct
"""

from __future__ import annotations

from pydantic import model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings


class CMSProductionSettings(AqueductSettings):
    """Typed CMS (Studio) production settings — generic Open edX deployment."""

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
