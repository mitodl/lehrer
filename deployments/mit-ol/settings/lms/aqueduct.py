"""LMS production settings module — django-aqueduct entry point.

Injected by the lehrer Dagger build into:
  /openedx/edx-platform/lms/envs/aqueduct.py

Usage::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct

The typed model is split across two sibling files:

  models/base.py     ← ProductionSettingsMixin (lehrer core; K8s source wiring,
                       type corrections, structural deferrals, shared validators)
  models/aqueduct.py ← AqueductSettings(BaseSettings), pure django-aqueduct
                       codegen v2 output.  Regenerate via::

    dagger call platform regenerate-aqueduct-settings \\
        --deployment-name mit-ol --release-name master \\
        --build-manifest ./deployments/mit-ol/build_manifest.yaml \\
        export --path ./generated
    # then copy generated/lms/models/aqueduct.py over the committed model.

The mixin is listed **first** so its declarations win in the pydantic MRO over
the generated defaults — see models/base.py.

Loading strategy (highest → lowest priority):

1. Environment variables — flat scalars from K8s ``envFrom`` ConfigMaps
   and Secrets.
2. YAML files under ``OL_SETTINGS_DIR`` (sorted, deep-merged) — complex
   types such as ``DATABASES``, ``CACHES``, ``JWT_AUTH``, ``FEATURES``.
3. ``AqueductSettings`` field defaults from ``lms.envs.models.aqueduct``,
   overlaid onto ``lms.envs.common``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field, model_validator

from django_aqueduct import configure_django_settings

from .models.aqueduct import AqueductSettings
from .models.base import ProductionSettingsMixin


class LMSProductionSettings(ProductionSettingsMixin, AqueductSettings):
    """Typed LMS production settings."""

    # YAML key from 82-lms-interpolated-config; Django setting is LMS_SEGMENT_KEY.
    SEGMENT_KEY: str | None = Field(default=None)

    # List from 81-lms-general-config; prepended onto AUTHENTICATION_BACKENDS by
    # the post-configure structural adjustment below (AUTHENTICATION_BACKENDS is
    # deferred to the plugin-complete base, so it can't be mutated in-model).
    THIRD_PARTY_AUTH_BACKENDS: list[str] | None = Field(default=None)
    # Legacy code paths still read these values from settings.FEATURES.
    FEATURES_COMPAT_KEYS: ClassVar[tuple[str, ...]] = (
        "ALLOW_ALL_ADVANCED_COMPONENTS",
        "ALLOW_COURSE_STAFF_GRADE_DOWNLOADS",
        "ALLOW_HIDING_DISCUSSION_TAB",
        "ALLOW_PUBLIC_ACCOUNT_CREATION",
        "AUTH_USE_CERTIFICATES",
        "AUTH_USE_OPENID_PROVIDER",
        "BYPASS_ACTIVATION_EMAIL_FOR_EXTAUTH",
        "DISABLE_START_DATES",
        "DISABLE_LOGIN_BUTTON",
        "EMBARGO",
        "ENABLE_AUTO_COURSE_REGISTRATION",
        "ENABLE_AUTO_GITHUB_REPO_CREATION",
        "ENABLE_BLAKE2B_HASHING",
        "ENABLE_BULK_ENROLLMENT_VIEW",
        "ENABLE_BULK_USER_RETIREMENT",
        "ENABLE_COMBINED_LOGIN_REGISTRATION",
        "ENABLE_COUNTRY_ACCESS",
        "ENABLE_CORS_HEADERS",
        "ENABLE_COURSEWARE_INDEX",
        "ENABLE_COURSEWARE_SEARCH",
        "ENABLE_COURSE_BLOCKS_NAVIGATION_API",
        "ENABLE_COURSE_HOME_REDIRECT",
        "ENABLE_CREDIT_API",
        "ENABLE_CREDIT_ELIGIBILITY",
        "ENABLE_CROSS_DOMAIN_CSRF_COOKIE",
        "ENABLE_CSMH_EXTENDED",
        "ENABLE_DISCUSSION_HOME_PANEL",
        "ENABLE_DISCUSSION_SERVICE",
        "ENABLE_EDX_USERNAME_CHANGER",
        "ENABLE_ENROLLMENT_RESET",
        "ENABLE_ENROLLMENT_TRACK_USER_PARTITION",
        "ENABLE_EXAM_SETTINGS_HTML_VIEW",
        "ENABLE_EXPORT_GIT",
        "ENABLE_FORUM_DAILY_DIGEST",
        "ENABLE_GIT_AUTO_EXPORT",
        "ENABLE_GRADE_DOWNLOADS",
        "ENABLE_INSTRUCTOR_ANALYTICS",
        "ENABLE_INSTRUCTOR_EMAIL",
        "ENABLE_INSTRUCTOR_REMOTE_GRADEBOOK_CONTROLS",
        "ENABLE_LIBRARY_AUTHORING_MICROFRONTEND",
        "ENABLE_LIBRARY_INDEX",
        "ENABLE_LTI_PROVIDER",
        "ENABLE_MKTG_SITE",
        "ENABLE_MOBILE_REST_API",
        "ENABLE_NEW_BULK_EMAIL_EXPERIENCE",
        "ENABLE_OAUTH2_PROVIDER",
        "ENABLE_ORA_USERNAMES_ON_DATA_EXPORT",
        "ENABLE_OTHER_COURSE_SETTINGS",
        "ENABLE_PAID_COURSE_REGISTRATION",
        "ENABLE_PREREQUISITE_COURSES",
        "ENABLE_PROCTORED_EXAMS",
        "ENABLE_READING_FROM_MULTIPLE_HISTORY_TABLES",
        "ENABLE_RENDER_XBLOCK_API",
        "ENABLE_SHOPPING_CART",
        "ENABLE_SPECIAL_EXAMS",
        "ENABLE_SYSADMIN_DASHBOARD",
        "ENABLE_TEAMS",
        "ENABLE_THIRD_PARTY_AUTH",
        "ENABLE_TEXTBOOK",
        "ENABLE_UNICODE_USERNAME",
        "ENABLE_V2_CERT_DISPLAY_SETTINGS",
        "ENABLE_VIDEO_UPLOAD_PIPELINE",
        "MAX_ENROLLMENT_INSTR_BUTTONS",
        "REQUIRE_COURSE_EMAIL_AUTH",
        "RESTRICT_ENROLL_BY_REG_METHOD",
        "SESSION_COOKIE_SECURE",
        "SHOW_FOOTER_LANGUAGE_SELECTOR",
        "SHOW_HEADER_LANGUAGE_SELECTOR",
        "SKIP_EMAIL_VALIDATION",
    )

    @model_validator(mode="after")
    def _derive_features_compat(self) -> LMSProductionSettings:
        """Mirror select module-level settings into FEATURES for compatibility."""
        features = getattr(self, "FEATURES", None)
        if not isinstance(features, dict):
            features = {}
        for key in self.FEATURES_COMPAT_KEYS:
            if key in features:
                continue
            value = getattr(self, key, None)
            if value is not None:
                features[key] = value
        self.FEATURES = features  # type: ignore[attr-defined]
        return self

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
    def _derive_social_auth_clean_usernames(self) -> LMSProductionSettings:
        if getattr(self, "SOCIAL_AUTH_CLEAN_USERNAMES", None) is None:
            self.SOCIAL_AUTH_CLEAN_USERNAMES = False  # type: ignore[attr-defined]
        return self


def _apply_structural_overrides(merged: dict[str, Any], model: Any) -> None:
    """Post-overlay adjustments to plugin-complete INSTALLED_APPS / AUTH_BACKENDS.

    Passed as ``configure_django_settings(post_configure=…)``; runs *after* the
    ``base="lms.envs.common"`` overlay, so ``INSTALLED_APPS`` and
    ``AUTHENTICATION_BACKENDS`` here are the live, plugin-complete base lists
    (the model never overrides them, so the overlay defers them to the base).
    These two mit-ol adjustments *extend* those lists, which a ``@model_validator``
    cannot do — the model is built before the overlay and has no access to the
    base.  ``merged`` is the merged settings dict (mutate in place); ``model`` is
    the validated model instance for typed inputs.
    """
    features = getattr(model, "FEATURES", None) or {}
    backends = list(merged.get("AUTHENTICATION_BACKENDS") or [])

    # Prepend THIRD_PARTY_AUTH_BACKENDS (arrives via YAML) unless third-party auth
    # is explicitly disabled.  Deduplication preserves order.
    third_party = getattr(model, "THIRD_PARTY_AUTH_BACKENDS", None)
    if third_party and (
        not isinstance(features, dict) or features.get("ENABLE_THIRD_PARTY_AUTH", True)
    ):
        backends = list(third_party) + [b for b in backends if b not in third_party]

    # LTI provider: add the app + backend when enabled.  lms/urls.py always
    # includes lms.djangoapps.lti_provider.urls, so the app must be in
    # INSTALLED_APPS whenever LTI is enabled or Django raises at startup.
    # (production.py did this; common.py does not, so the base overlay omits it.)
    if getattr(model, "ENABLE_LTI_PROVIDER", False):
        lti_app = "lms.djangoapps.lti_provider.apps.LtiProviderConfig"
        lti_backend = "lms.djangoapps.lti_provider.users.LtiBackend"
        apps = list(merged.get("INSTALLED_APPS") or [])
        if lti_app not in apps:
            apps.append(lti_app)
            merged["INSTALLED_APPS"] = apps
        if lti_backend not in backends:
            backends.append(lti_backend)

    merged["AUTHENTICATION_BACKENDS"] = backends


# base="lms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not override (env/YAML source or
# validator) defers to the real common.py value — including the structural
# settings openedx augments at runtime via add_plugins (INSTALLED_APPS, …).
# post_configure runs _apply_structural_overrides against the merged,
# plugin-complete settings (see that function).
configure_django_settings(
    LMSProductionSettings,
    base="lms.envs.common",
    post_configure=_apply_structural_overrides,
)
