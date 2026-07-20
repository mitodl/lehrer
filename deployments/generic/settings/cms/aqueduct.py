"""CMS (Studio) production settings module — django-aqueduct entry point.

Generic Open edX deployment — no operator-specific customizations.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/cms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=cms.envs.aqueduct

The typed model is split across models/base.py (ProductionSettingsMixin, lehrer
core) and models/aqueduct.py (AqueductSettings(BaseSettings), pure django-aqueduct
codegen v2 output).  The mixin is listed first so its declarations win in the
pydantic MRO — see the generic LMS entry module and models/base.py.
"""

from __future__ import annotations

from pydantic import model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings
from .models.base import ProductionSettingsMixin


class CMSProductionSettings(ProductionSettingsMixin, AqueductSettings):
    """Typed CMS (Studio) production settings — generic Open edX deployment."""

    @model_validator(mode="after")
    def _derive_urlconf(self) -> CMSProductionSettings:
        if getattr(self, "ROOT_URLCONF", None) is None:
            self.ROOT_URLCONF = "cms.urls"  # type: ignore[attr-defined]
        return self


# base="cms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not override (via an env/YAML source or a
# validator) defers to the real common.py value — including the structural
# settings openedx augments at runtime via add_plugins (INSTALLED_APPS, …),
# which the static model carries only as a plugin-incomplete snapshot.
configure_django_settings(CMSProductionSettings, base="cms.envs.common")
