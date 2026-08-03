"""CMS (Studio) production settings module — django-aqueduct entry point.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/cms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=cms.envs.aqueduct

The typed model is split across two sibling files:

  models/base.py     ← ProductionSettingsMixin (lehrer core; K8s source wiring,
                       type corrections, structural deferrals, shared validators)
  models/aqueduct.py ← AqueductSettings(BaseSettings), pure django-aqueduct
                       codegen v2 output.  Regenerate via::

    dagger call platform regenerate-aqueduct-settings \\
        --deployment-name mit-ol --release-name master \\
        --build-manifest ./deployments/mit-ol/build_manifest.yaml \\
        export --path ./generated
    # then copy generated/cms/models/aqueduct.py over the committed model.

The mixin is listed **first** so its declarations win in the pydantic MRO over
the generated defaults — see the LMS entry module and models/base.py.

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``cms.envs.models.aqueduct``,
   overlaid onto ``cms.envs.common``.
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
# defaults: any setting the model does not override (via an env/YAML source or a
# validator) defers to the real common.py value — including the structural
# settings openedx augments at runtime via add_plugins (INSTALLED_APPS, …),
# which the static model carries only as a plugin-incomplete snapshot.
configure_django_settings(CMSProductionSettings, base="cms.envs.common")
