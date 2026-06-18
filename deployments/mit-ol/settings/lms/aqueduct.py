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


class LMSProductionSettings(AqueductSettings):
    """Typed LMS production settings."""

    # YAML key from 82-lms-interpolated-config; Django setting is LMS_SEGMENT_KEY.
    SEGMENT_KEY: str | None = Field(default=None)

    # List from 81-lms-general-config; merged into AUTHENTICATION_BACKENDS below.
    THIRD_PARTY_AUTH_BACKENDS: list[str] | None = Field(default=None)
    # Legacy code paths still read these values from settings.FEATURES.
    FEATURES_COMPAT_KEYS: tuple[str, ...] = (
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

    @model_validator(mode="after")
    def _derive_lti_provider(self) -> LMSProductionSettings:
        """Mirror production.py: add lti_provider app + backend when enabled.

        lms/urls.py unconditionally includes lms.djangoapps.lti_provider.urls,
        so the app must be in INSTALLED_APPS whenever LTI is enabled or Django
        will raise a RuntimeError at startup when importing the models.
        """
        if not getattr(self, "ENABLE_LTI_PROVIDER", False):
            return self
        apps: list = list(getattr(self, "INSTALLED_APPS", None) or [])
        lti_app = "lms.djangoapps.lti_provider.apps.LtiProviderConfig"
        lti_backend = "lms.djangoapps.lti_provider.users.LtiBackend"
        if lti_app not in apps:
            apps.append(lti_app)
            self.INSTALLED_APPS = apps  # type: ignore[attr-defined]
        backends: list = list(getattr(self, "AUTHENTICATION_BACKENDS", None) or [])
        if lti_backend not in backends:
            backends.append(lti_backend)
            self.AUTHENTICATION_BACKENDS = backends  # type: ignore[attr-defined]
        return self


# base="lms.envs.common" overlays the model onto edx-platform's upstream
# defaults: any setting the model does not carry, or that the generator could
# not serialise (rendered as None — e.g. opaque tuples/dicts), falls back to
# the real common.py value instead of vanishing to Django's empty default.
configure_django_settings(LMSProductionSettings, base="lms.envs.common")

# DIAGNOSTIC — remove after root-cause confirmed.
import sys as _sys  # noqa: PLC0415, E402

_aqueduct_mod = _sys.modules.get(__name__)
if _aqueduct_mod is not None:
    _has_survey = "SURVEY_REPORT_ENABLE" in _aqueduct_mod.__dict__
    _n_upper = sum(1 for k in _aqueduct_mod.__dict__ if k.isupper())
    _sys.stderr.write(
        f"[lehrer] aqueduct diag: SURVEY_REPORT_ENABLE={_has_survey} "
        f"uppercase_keys={_n_upper}\n"
    )
