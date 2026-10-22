from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field

from lehrer.settings.base import (
    ProductionSettingsMixin,
    StudioSettingsMixin,
    apply_base_post_configure,
    ensure_celery_router_inputs,
    merge_jwt_signing_keys,
    spectacular_with_servers,
    spectacular_without_undefined_hooks,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CACHE_REDIS_DB",
        "CELERY_BROKER_HOSTNAME",
        "CELERY_BROKER_PASSWORD",
        "CELERY_BROKER_TRANSPORT",
        "CELERY_BROKER_USER",
        "CELERY_BROKER_VHOST",
        "CACHES",
        "CMS_BASE_URL",
        "COMPREHENSIVE_THEME_DIRS",
        "CORS_ALLOW_CREDENTIALS",
        "CORS_ORIGIN_ALLOW_ALL",
        "CORS_ORIGIN_WHITELIST",
        "CELERY_TIMEZONE",
        "LANGUAGES",
        "TIME_ZONE",
        "AUTHORING_API_URL",
        "SPECTACULAR_SETTINGS",
        "LMS_BASE_URL",
        "LMS_ROOT_URL",
        "JWT_PRIVATE_SIGNING_JWK",
        "JWT_PUBLIC_SIGNING_JWK_SET",
        "SESSION_COOKIE_NAME",
        "SOCIAL_AUTH_REDIRECT_IS_HTTPS",
        "SOCIAL_AUTH_EDX_OAUTH2_KEY",
        "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)


class TestDeriveCaches:
    def test_left_alone_without_a_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "redis")
        monkeypatch.setenv("CELERY_BROKER_HOSTNAME", "valkey")
        assert getattr(ProductionSettingsMixin(), "CACHES", None) is None

    def test_every_alias_shares_the_broker_host_under_its_own_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "redis")
        monkeypatch.setenv("CELERY_BROKER_HOSTNAME", "valkey.local-infra")
        monkeypatch.setenv("CACHE_REDIS_DB", "1")
        caches = ProductionSettingsMixin().CACHES  # type: ignore[attr-defined]
        assert {c["LOCATION"] for c in caches.values()} == {
            "redis://:@valkey.local-infra/1"
        }
        prefixes = [c["KEY_PREFIX"] for c in caches.values()]
        assert len(prefixes) == len(set(prefixes))
        # The cache-backed session engine reads this one.
        assert "default" in caches

    def test_follows_the_broker_scheme_and_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "rediss")
        monkeypatch.setenv("CELERY_BROKER_HOSTNAME", "cache.example")
        monkeypatch.setenv("CELERY_BROKER_USER", "default")
        monkeypatch.setenv("CELERY_BROKER_PASSWORD", "p@ss")
        monkeypatch.setenv("CACHE_REDIS_DB", "3")
        caches = ProductionSettingsMixin().CACHES  # type: ignore[attr-defined]
        assert (
            caches["default"]["LOCATION"]
            == "rediss://default:p%40ss@cache.example/3"  # pragma: allowlist secret
        )

    def test_follows_the_broker_tls_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Celery keeps the transport at "redis" and carries TLS in
        # CELERY_BROKER_USE_SSL; redis-py needs the rediss scheme and the
        # options on the connection.
        monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "redis")
        monkeypatch.setenv("CELERY_BROKER_HOSTNAME", "cache.example")
        monkeypatch.setenv("CACHE_REDIS_DB", "3")
        monkeypatch.setenv(
            "CELERY_BROKER_USE_SSL", '{"ssl_cert_reqs": "CERT_OPTIONAL"}'
        )
        caches = ProductionSettingsMixin().CACHES  # type: ignore[attr-defined]
        assert caches["default"]["LOCATION"] == "rediss://:@cache.example/3"
        assert caches["default"]["OPTIONS"] == {"ssl_cert_reqs": "CERT_OPTIONAL"}

    def test_plaintext_broker_gets_no_tls_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "redis")
        monkeypatch.setenv("CELERY_BROKER_HOSTNAME", "cache.example")
        monkeypatch.setenv("CACHE_REDIS_DB", "3")
        caches = ProductionSettingsMixin().CACHES  # type: ignore[attr-defined]
        assert caches["default"]["LOCATION"] == "redis://:@cache.example/3"
        assert "OPTIONS" not in caches["default"]

    def test_refuses_a_db_without_a_broker_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CACHE_REDIS_DB", "1")
        with pytest.raises(
            ValueError, match="CELERY_BROKER_TRANSPORT or CELERY_BROKER_HOSTNAME"
        ):
            ProductionSettingsMixin()


class TestStudioSettings:
    def test_oauth2_settings_arrive_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOCIAL_AUTH_EDX_OAUTH2_KEY", "cms-sso")
        monkeypatch.setenv("SESSION_COOKIE_NAME", "studio_sessionid")
        settings = StudioSettingsMixin()
        assert settings.SOCIAL_AUTH_EDX_OAUTH2_KEY == "cms-sso"
        assert settings.SESSION_COOKIE_NAME == "studio_sessionid"

    def test_public_url_root_defaults_to_the_lms_root_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMS_BASE_URL", "http://localhost:8000")
        settings = StudioSettingsMixin()
        assert (
            settings.SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT == "http://localhost:8000"
        )

    def test_an_explicit_public_url_root_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMS_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv(
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT", "https://lms.example.com"
        )
        settings = StudioSettingsMixin()
        assert (
            settings.SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT == "https://lms.example.com"
        )

    def test_the_lms_does_not_pick_up_studio_sso_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # openedx-secrets feeds both services the same keys; only Studio reads them.
        monkeypatch.setenv("SOCIAL_AUTH_EDX_OAUTH2_KEY", "cms-sso")
        assert not hasattr(ProductionSettingsMixin(), "SOCIAL_AUTH_EDX_OAUTH2_KEY")


class _StudioWithAuthoringSchema(StudioSettingsMixin):
    """The mixin plus the two fields the generated CMS model contributes."""

    AUTHORING_API_URL: str = Field(default="")
    SPECTACULAR_SETTINGS: dict[str, Any] = Field(
        default_factory=lambda: {
            "SCHEMA_PATH_PREFIX": "/api/contentstore",
            "SCHEMA_PATH_PREFIX_TRIM": "/api/contentstore",
        }
    )


def test_spectacular_servers_put_the_trimmed_prefix_back() -> None:
    # The shape of the LMS Enrollment API schema: every path is under the prefix.
    enrollment = {
        "TITLE": "LMS",
        "SCHEMA_PATH_PREFIX": "/api/enrollment",
        "SCHEMA_PATH_PREFIX_TRIM": "/api/enrollment",
    }
    derived = spectacular_with_servers(
        enrollment, "https://lms.example.com/", "LMS-enrollment"
    )
    assert derived["SERVERS"] == [
        {
            "url": "https://lms.example.com/api/enrollment",
            "description": "LMS-enrollment",
        },
        {"url": "https://lms.example.com", "description": "Local"},
    ]
    assert derived["TITLE"] == "LMS"
    # A copy, so the caller has to assign it for the overlay to keep it.
    assert "SERVERS" not in enrollment


def test_spectacular_servers_read_the_prefix_not_the_trim_flag() -> None:
    # drf-spectacular documents SCHEMA_PATH_PREFIX_TRIM as a bool.
    derived = spectacular_with_servers(
        {"SCHEMA_PATH_PREFIX": "/api/contentstore", "SCHEMA_PATH_PREFIX_TRIM": True},
        "https://studio.example.com",
        "CMS-contentstore",
    )
    assert [server["url"] for server in derived["SERVERS"]] == [
        "https://studio.example.com/api/contentstore",
        "https://studio.example.com",
    ]


@pytest.mark.parametrize(
    "spectacular",
    [
        {"SCHEMA_PATH_PREFIX": "/api/contentstore", "SCHEMA_PATH_PREFIX_TRIM": False},
        {"SCHEMA_PATH_PREFIX": "/api/contentstore"},
        {"SCHEMA_PATH_PREFIX": None, "SCHEMA_PATH_PREFIX_TRIM": True},
    ],
)
def test_spectacular_servers_without_a_trimmed_prefix_offer_only_the_root(
    spectacular: dict[str, Any],
) -> None:
    derived = spectacular_with_servers(spectacular, "https://studio.example.com", "x")
    assert derived["SERVERS"] == [
        {"url": "https://studio.example.com", "description": "Local"}
    ]


@pytest.fixture
def release_spectacular(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """An older release's ``lib/spectacular.py``: one hook, unsafe to import."""
    unsafe = "raise RuntimeError('imported while settings were being built')\n"
    package = tmp_path / "older_release"
    package.mkdir()
    (package / "__init__.py").write_text(unsafe)
    (package / "spectacular.py").write_text(f"{unsafe}def api_filter(endpoints): ...\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "older_release.spectacular"


class TestSpectacularHooks:
    def test_hooks_the_release_does_not_define_are_dropped(
        self, release_spectacular: str
    ) -> None:
        # The master model names hooks that verawood's cms/lib/spectacular.py
        # lacks; drf-spectacular fails to import them when the schema is requested.
        pruned = spectacular_without_undefined_hooks(
            {
                "TITLE": "Authoring API",
                "PREPROCESSING_HOOKS": [f"{release_spectacular}.api_filter"],
                "POSTPROCESSING_HOOKS": [
                    "json.dumps",
                    f"{release_spectacular}.mark_superseded_paths",
                    "no_such_package.spectacular.hook",
                ],
            }
        )
        assert pruned == {
            "TITLE": "Authoring API",
            "PREPROCESSING_HOOKS": [f"{release_spectacular}.api_filter"],
            "POSTPROCESSING_HOOKS": ["json.dumps"],
        }

    def test_settings_without_hooks_gain_none(self) -> None:
        assert spectacular_without_undefined_hooks({"TITLE": "LMS"}) == {"TITLE": "LMS"}

    def test_deriving_servers_drops_them_too(self, release_spectacular: str) -> None:
        derived = spectacular_with_servers(
            {"POSTPROCESSING_HOOKS": [f"{release_spectacular}.mark_migrated_paths"]},
            "https://studio.example.com",
            "x",
        )
        assert derived["POSTPROCESSING_HOOKS"] == []


class TestSpectacularServers:
    def test_a_trimmed_path_resolves_to_its_real_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CMS_BASE_URL", "https://studio.example.com/")
        settings = _StudioWithAuthoringSchema()
        servers = settings.SPECTACULAR_SETTINGS["SERVERS"]
        # Swagger requests servers[0] + the published (trimmed) path.
        assert (
            servers[0]["url"] + "/v0/xblock/abc"
            == "https://studio.example.com/api/contentstore/v0/xblock/abc"
        )
        # Paths outside the trimmed prefix are published whole.
        assert (
            servers[1]["url"] + "/api/courses/x/bulk_enable_disable_discussions"
            == "https://studio.example.com/api/courses/x/bulk_enable_disable_discussions"
        )
        assert len(servers) == 2

    def test_the_derived_value_overrides_the_base(self) -> None:
        # django-aqueduct lets a field the base also carries through only when
        # it is in model_fields_set.
        assert "SPECTACULAR_SETTINGS" in _StudioWithAuthoringSchema().model_fields_set

    def test_a_public_authoring_api_url_is_offered_last(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTHORING_API_URL", "https://api.example.com/authoring")
        servers = _StudioWithAuthoringSchema().SPECTACULAR_SETTINGS["SERVERS"]
        assert [server["description"] for server in servers] == [
            "CMS-contentstore",
            "Local",
            "Public",
        ]

    def test_operator_supplied_servers_are_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        supplied = {"SERVERS": [{"url": "https://elsewhere.example.com"}]}
        monkeypatch.setenv("SPECTACULAR_SETTINGS", json.dumps(supplied))
        assert _StudioWithAuthoringSchema().SPECTACULAR_SETTINGS == supplied

    def test_a_model_without_the_setting_is_untouched(self) -> None:
        assert not hasattr(StudioSettingsMixin(), "SPECTACULAR_SETTINGS")


class TestCorsSettings:
    def test_the_whitelist_arrives_from_env_as_a_json_array(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CORS_ORIGIN_WHITELIST",
            '["https://studio.mit.test", "https://learn.mit.test"]',
        )
        assert ProductionSettingsMixin().CORS_ORIGIN_WHITELIST == [
            "https://studio.mit.test",
            "https://learn.mit.test",
        ]

    def test_a_false_flag_from_env_is_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ORIGIN_ALLOW_ALL", "false")
        assert ProductionSettingsMixin().CORS_ORIGIN_ALLOW_ALL is False

    def test_credentials_default_to_a_bool(self) -> None:
        # django-cors-headers' own default; None would fail its bool check.
        assert ProductionSettingsMixin().CORS_ALLOW_CREDENTIALS is False


def test_theme_dirs_arrive_from_env_colon_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPREHENSIVE_THEME_DIRS", "/openedx/themes:/extra/themes")
    assert ProductionSettingsMixin().COMPREHENSIVE_THEME_DIRS == [
        "/openedx/themes",
        "/extra/themes",
    ]


class _WithGeneratedDefaults(ProductionSettingsMixin):
    """The generated declarations the timezone and language validators read."""

    CELERY_TIMEZONE: str = Field(default="UTC")
    TIME_ZONE: str = Field(default="UTC")
    LANGUAGES: list[Any] = Field(default_factory=lambda: [("en", "English")])
    LANGUAGE_DICT: Any = Field(default=None)


class TestTimezone:
    def test_a_supplied_celery_timezone_sets_time_zone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CELERY_TIMEZONE", "America/New_York")
        assert _WithGeneratedDefaults().TIME_ZONE == "America/New_York"

    def test_the_celery_default_does_not_override_time_zone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TIME_ZONE", "America/New_York")
        assert _WithGeneratedDefaults().TIME_ZONE == "America/New_York"


class TestLanguageDict:
    def test_follows_supplied_languages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGUAGES", '[["fr", "French"]]')
        assert _WithGeneratedDefaults().LANGUAGE_DICT == {"fr": "French"}

    def test_is_left_to_the_base_while_languages_is_unset(self) -> None:
        assert "LANGUAGE_DICT" not in _WithGeneratedDefaults().model_fields_set


_DEPLOYMENTS = Path(__file__).parents[2] / "deployments"
_MIT_OL_CMS_ENTRY = _DEPLOYMENTS / "mit-ol/settings/cms/aqueduct.py"
_MIT_OL_LMS_MODEL = _DEPLOYMENTS / "mit-ol/settings/lms/models/aqueduct.py"
_MIT_OL_CMS_MODEL = _DEPLOYMENTS / "mit-ol/settings/cms/models/aqueduct.py"


def _declared_field(path: Path, name: str) -> tuple[str, dict[str, Any]]:
    """Return ``(annotation, {kwarg: literal})`` for *name*'s ``Field()`` in *path*.

    Read by AST rather than imported: an entry module calls
    ``configure_django_settings`` at import time and a generated model imports
    edx-platform symbols, neither of which this suite has. Keywords whose value
    is not a literal (``default_factory=lambda: ...``) are omitted.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            kwargs: dict[str, Any] = {}
            for kw in getattr(node.value, "keywords", []):
                try:
                    kwargs[str(kw.arg)] = ast.literal_eval(kw.value)
                except ValueError:
                    continue
            return ast.unparse(node.annotation), kwargs
    pytest.fail(f"{name} is not declared in {path}")


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (_MIT_OL_CMS_MODEL, "COURSE_AUTHORING_MICROFRONTEND_URL"),
        (_MIT_OL_LMS_MODEL, "LEARNING_MICROFRONTEND_URL"),
    ],
)
def test_the_model_declares_settings_only_openedx_envs_common_assigns(
    model: Path, name: str
) -> None:
    # Reached only through a star-import; see _aqueduct_codegen_cmd.
    _declared_field(model, name)


class TestDeclarationAdmitsTheEnvVar:
    """The invariant every hand-written or plugin declaration here rests on.

    pydantic-settings' env source collects values *per declared field*: it
    walks ``model_fields``, not ``os.environ``. So an undeclared name is not
    loosely typed, it is absent -- which is why these gaps fail silently rather
    than with a bad value, and why declaring the field is the fix rather than
    coercing a string somewhere downstream.
    """

    def test_an_undeclared_var_never_reaches_the_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MITX_REDIRECT_ENABLED", "false")
        settings = ProductionSettingsMixin()
        # Not the string "false" (which would be truthy), not False -- absent.
        # MITX_* is declared by openedx-companion-auth's plugin_settings(), so
        # the generated model only carries it where that plugin is installed.
        assert not hasattr(settings, "MITX_REDIRECT_ENABLED")
        # Not in extras either: extra="allow" keeps values a *validator*
        # assigns, it does not open the env source up to undeclared names.
        assert "MITX_REDIRECT_ENABLED" not in (settings.model_extra or {})

    def test_a_declared_bool_parses_the_false_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _WithFlag(ProductionSettingsMixin):
            MITX_REDIRECT_ENABLED: bool = Field(default=True)

        monkeypatch.setenv("MITX_REDIRECT_ENABLED", "false")
        assert _WithFlag().MITX_REDIRECT_ENABLED is False

    def test_a_declared_list_parses_a_json_array(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _WithList(ProductionSettingsMixin):
            MITX_REDIRECT_ALLOW_RE_LIST: list[str] = Field(default_factory=list)

        monkeypatch.setenv("MITX_REDIRECT_ALLOW_RE_LIST", '["^/heartbeat", "^/admin"]')
        assert _WithList().MITX_REDIRECT_ALLOW_RE_LIST == ["^/heartbeat", "^/admin"]

    def test_a_plugin_field_records_the_distribution_that_supplies_it(self) -> None:
        # The other half of scoping these to the deployments that pin the
        # plugin. One generated model serves six mit-ol cells and only
        # mitxonline installs openedx-companion-auth, so a bare
        # `default=True` would tell master/mitx -- which has no redirect
        # middleware -- that the redirect is on. The marker is what makes
        # django-aqueduct withhold the default where the distribution is
        # absent (>= 0.15.0); the field itself stays, so an operator who sets
        # the variable is still obeyed.
        annotation, kwargs = _declared_field(_MIT_OL_LMS_MODEL, "MITX_REDIRECT_ENABLED")
        assert annotation == "bool"
        assert kwargs["default"] is True
        assert kwargs["json_schema_extra"] == {
            "aqueduct_plugin": "openedx-companion-auth"
        }


class TestBulkEmailDefaults:
    def test_not_declared_in_lehrer_core(self) -> None:
        # They live on mit-ol's CMSProductionSettings: nothing but a plugin only
        # mit-ol cells pin (ol-openedx-canvas-integration's cms.djangoapp entry
        # point) makes the CMS need them, so lehrer core must not carry them
        # into every deployment group.
        mixin_fields = StudioSettingsMixin.model_fields
        assert "BULK_EMAIL_DEFAULT_RETRY_DELAY" not in mixin_fields
        assert "BULK_EMAIL_MAX_RETRIES" not in mixin_fields

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("BULK_EMAIL_DEFAULT_RETRY_DELAY", 30), ("BULK_EMAIL_MAX_RETRIES", 5)],
    )
    def test_mit_ol_cms_declares_the_upstream_default(
        self, name: str, expected: int
    ) -> None:
        # bulk_email.tasks reads both at decorator-evaluation time, so a wrong
        # type here is an import-time crash in the CMS, not a runtime surprise.
        # Read by AST: the entry module calls configure_django_settings at
        # import time and needs the built platform, which this suite has not.
        annotation, kwargs = _declared_field(_MIT_OL_CMS_ENTRY, name)
        assert annotation == "int"
        assert kwargs["default"] == expected


class TestMergeJwtSigningKeys:
    def test_merges_into_the_overlaid_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_PRIVATE_SIGNING_JWK", '{"kid": "k"}')
        monkeypatch.setenv("JWT_PUBLIC_SIGNING_JWK_SET", '{"keys": []}')
        merged = {"JWT_AUTH": {"JWT_ISSUER": "http://lms/oauth2"}}
        merge_jwt_signing_keys(merged, ProductionSettingsMixin())
        assert merged["JWT_AUTH"] == {
            "JWT_ISSUER": "http://lms/oauth2",
            "JWT_PRIVATE_SIGNING_JWK": '{"kid": "k"}',
            "JWT_PUBLIC_SIGNING_JWK_SET": '{"keys": []}',
        }

    def test_leaves_yaml_supplied_keys_alone_when_unset(self) -> None:
        jwt_auth = {"JWT_PRIVATE_SIGNING_JWK": "from-yaml"}
        merged = {"JWT_AUTH": jwt_auth}
        merge_jwt_signing_keys(merged, ProductionSettingsMixin())
        assert merged["JWT_AUTH"] is jwt_auth


class TestEnsureCeleryRouterInputs:
    def test_supplies_both_router_settings(self) -> None:
        # route_task reads both unconditionally; common.py defines neither,
        # so without this every apply_async raises AttributeError.
        merged: dict = {}
        ensure_celery_router_inputs(merged)
        assert merged["EXPLICIT_QUEUES"] == {}
        assert merged["ALTERNATE_ENV_TASKS"] == {}

    def test_leaves_yaml_supplied_routing_alone(self) -> None:
        supplied = {"some.task": {"queue": "edx.lms.core.high_mem"}}
        merged: dict = {"EXPLICIT_QUEUES": supplied}
        ensure_celery_router_inputs(merged)
        assert merged["EXPLICIT_QUEUES"] is supplied

    def test_base_post_configure_does_both_jobs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_PRIVATE_SIGNING_JWK", '{"kid": "k"}')
        merged: dict = {"JWT_AUTH": {"JWT_ISSUER": "http://lms/oauth2"}}
        apply_base_post_configure(merged, ProductionSettingsMixin())
        assert merged["JWT_AUTH"]["JWT_PRIVATE_SIGNING_JWK"] == '{"kid": "k"}'
        assert merged["EXPLICIT_QUEUES"] == {}


def test_redirect_is_https_parses_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCIAL_AUTH_REDIRECT_IS_HTTPS", "false")
    assert StudioSettingsMixin().SOCIAL_AUTH_REDIRECT_IS_HTTPS is False


def test_redirect_is_https_defaults_to_the_auth_backends_default() -> None:
    assert StudioSettingsMixin().SOCIAL_AUTH_REDIRECT_IS_HTTPS is True


def test_broker_url_is_built_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_BROKER_TRANSPORT", "redis")
    monkeypatch.setenv(
        "CELERY_BROKER_HOSTNAME", "redis-valkey.openedx.svc.cluster.local"
    )
    settings = ProductionSettingsMixin()
    assert settings.BROKER_URL == (  # type: ignore[attr-defined]
        "redis://:@redis-valkey.openedx.svc.cluster.local/"
    )
