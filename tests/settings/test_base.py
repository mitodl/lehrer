from __future__ import annotations

import pytest

from lehrer.settings.base import (
    ProductionSettingsMixin,
    StudioSettingsMixin,
    merge_jwt_signing_keys,
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
