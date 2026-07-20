"""LMS production settings module — django-aqueduct entry point.

Generic Open edX deployment — no operator-specific customizations.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/lms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct

The typed model that backs this module is split across two sibling files:

  models/base.py     ← ProductionSettingsMixin (lehrer core; K8s source wiring,
                       type corrections, structural deferrals, shared validators)
  models/aqueduct.py ← AqueductSettings(BaseSettings), pure django-aqueduct
                       codegen v2 output; regenerate via
                       ``OpenedxPlatform.regenerate_aqueduct_settings``.

The mixin is listed **first** so its declarations win in the pydantic MRO over
the generated defaults (that precedence is what activates the type corrections
and the structural deferrals — see models/base.py).

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``lms.envs.models.aqueduct``,
   overlaid onto ``lms.envs.common`` (see ``configure_django_settings`` below).
"""

from __future__ import annotations

from pydantic import model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings
from .models.base import ProductionSettingsMixin


class LMSProductionSettings(ProductionSettingsMixin, AqueductSettings):
    """Typed LMS production settings — generic Open edX deployment."""

    @model_validator(mode="after")
    def _derive_urlconf(self) -> LMSProductionSettings:
        if getattr(self, "ROOT_URLCONF", None) is None:
            self.ROOT_URLCONF = "lms.urls"  # type: ignore[attr-defined]
        return self


# base="lms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not override (via an env/YAML source or a
# validator) defers to the real common.py value — including the structural
# settings openedx augments at runtime via add_plugins (INSTALLED_APPS, …),
# which the static model carries only as a plugin-incomplete snapshot.
configure_django_settings(LMSProductionSettings, base="lms.envs.common")
