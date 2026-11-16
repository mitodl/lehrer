from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from lehrer.bootstrap import __main__ as runner
from lehrer.bootstrap.spec import BootstrapSpec, check_fragment, load, merge

DEPLOYMENTS = Path(__file__).parents[2] / "deployments"


def _app(name: str, client_id_env: str = "A_ID", **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "user": "svc",
        "grant_type": "client-credentials",
        "client_id_env": client_id_env,
        "client_secret_env": f"{client_id_env}_SECRET",
        **extra,
    }


def _token(username: str, application_name: str) -> dict[str, Any]:
    return {
        "username": username,
        "email": f"{username}@example.invalid",
        "token_env": "TOKEN",
        "application_name": application_name,
    }


def _spec(**fields: Any) -> BootstrapSpec:
    return BootstrapSpec.model_validate(fields)


@pytest.mark.parametrize(
    "spec",
    sorted(DEPLOYMENTS.glob("*/provision/bootstrap.yaml")),
    ids=lambda p: p.parts[-3],
)
def test_shipped_base_specs_still_validate(spec: Path) -> None:
    load(spec)


class TestIdentities:
    def test_identical_repeats_collapse(self) -> None:
        flag = {"name": "a.b", "everyone": True}
        assert len(_spec(waffle_flags=[flag, flag]).waffle_flags) == 1

    @pytest.mark.parametrize(
        ("field", "first", "second"),
        [
            ("waffle_flags", {"name": "a.b", "everyone": True}, {"name": "a.b"}),
            (
                "users",
                {"username": "u", "email": "a@example.invalid"},
                {"username": "u", "email": "b@example.invalid"},
            ),
            ("oauth_applications", _app("x"), _app("x", scopes=["user_id"])),
            (
                "third_party_auth_providers",
                {
                    "backend_name": "idp",
                    "slug": "one",
                    "name": "One",
                    "client_id_env": "I",
                    "client_secret_env": "S",
                    "other_settings_env": "O",
                },
                {
                    "backend_name": "idp",
                    "slug": "two",
                    "name": "Two",
                    "client_id_env": "I",
                    "client_secret_env": "S",
                    "other_settings_env": "O",
                },
            ),
        ],
    )
    def test_differing_entries_with_one_identity_conflict(
        self, field: str, first: dict[str, Any], second: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError, match="differ"):
            _spec(**{field: [first, second]})

    def test_client_id_env_is_unique_across_applications(self) -> None:
        with pytest.raises(ValidationError, match="client_id_env"):
            _spec(oauth_applications=[_app("a"), _app("b")])

    def test_token_application_cannot_be_an_oauth_application(self) -> None:
        with pytest.raises(ValidationError, match="oauth_applications also"):
            _spec(
                oauth_applications=[_app("x")], service_access_tokens=[_token("t", "x")]
            )

    def test_two_tokens_cannot_share_an_application(self) -> None:
        with pytest.raises(ValidationError, match="application_name"):
            _spec(service_access_tokens=[_token("t1", "x"), _token("t2", "x")])

    def test_token_account_cannot_also_be_a_user(self) -> None:
        with pytest.raises(ValidationError, match="also declared under users"):
            _spec(
                users=[{"username": "t", "email": "t@example.invalid"}],
                service_access_tokens=[_token("t", "x")],
            )


class TestPlaceholders:
    def test_allowlisted_bare_names_pass(self) -> None:
        _spec(
            oauth_applications=[
                _app("{EDXNOTES_CLIENT_NAME}", redirect_uris=["{LMS_ROOT_URL}/x"])
            ]
        )

    @pytest.mark.parametrize(
        "template",
        [
            "{SECRET_KEY}",
            "{LMS_ROOT_URL.x}",
            "{LMS_ROOT_URL!r}",
            "{LMS_ROOT_URL:>9}",
            "{",
        ],
    )
    def test_anything_else_is_refused(self, template: str) -> None:
        with pytest.raises(ValidationError):
            _spec(oauth_applications=[_app("x", redirect_uris=[template])])


class TestMerge:
    def test_lists_concatenate_in_order(self) -> None:
        merged = merge(
            _spec(waffle_flags=[{"name": "a.one"}]),
            _spec(waffle_flags=[{"name": "b.two"}, {"name": "a.one"}]),
        )
        assert [f.name for f in merged.waffle_flags] == ["a.one", "b.two"]

    def test_conflicts_across_specs_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="differ"):
            merge(
                _spec(waffle_flags=[{"name": "a.one", "everyone": True}]),
                _spec(waffle_flags=[{"name": "a.one", "everyone": False}]),
            )

    def test_demo_course_must_agree(self) -> None:
        assert merge(_spec(demo_course={}), _spec()).demo_course is not None
        with pytest.raises(ValueError, match="demo_course"):
            merge(_spec(demo_course={}), _spec(demo_course={"branch": "x"}))


class TestFragment:
    def test_service_data_is_allowed(self) -> None:
        check_fragment(
            _spec(
                users=[
                    {"username": "svc", "email": "s@example.invalid", "staff": True}
                ],
                waffle_flags=[{"name": "a.b"}],
            )
        )

    @pytest.mark.parametrize(
        "user",
        [
            {"username": "u", "email": "u@example.invalid", "superuser": True},
            {"username": "u", "email": "u@example.invalid", "password_env": "P"},
        ],
    )
    def test_operator_privileges_are_refused(self, user: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="base spec"):
            check_fragment(_spec(users=[user]))

    @pytest.mark.parametrize(
        "fields", [{"migrate": [{"service": "lms"}]}, {"demo_course": {}}]
    )
    def test_operator_steps_are_refused(self, fields: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="may not declare"):
            check_fragment(_spec(**fields))


class TestRunner:
    def test_main_merges_every_spec(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: list[BootstrapSpec] = []
        monkeypatch.setitem(runner.APPLY, "waffle_flags", lambda s, _: seen.append(s))
        monkeypatch.setitem(sys.modules, "django", SimpleNamespace(setup=lambda: None))
        monkeypatch.setitem(sys.modules, "django.conf", SimpleNamespace(settings=None))
        base = tmp_path / "base.yaml"
        base.write_text("waffle_flags: [{name: a.one}]\n")
        fragment = tmp_path / "features.yaml"
        fragment.write_text("waffle_flags: [{name: b.two}]\n")
        runner.main([str(base), str(fragment), "--steps", "waffle_flags"])
        assert [f.name for f in seen[0].waffle_flags] == ["a.one", "b.two"]

    def test_resolved_oauth_names_must_not_collide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("A_ID", "one")
        monkeypatch.setenv("B_ID", "two")
        spec = _spec(
            oauth_applications=[
                _app("{EDXNOTES_CLIENT_NAME}", "A_ID"),
                _app("notes", "B_ID"),
            ]
        )
        settings = SimpleNamespace(EDXNOTES_CLIENT_NAME="notes")
        with pytest.raises(ValueError, match="application name 'notes'"):
            runner.check_resolved_collisions(spec, settings, ["oauth_applications"])

    def test_client_ids_must_not_collide(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A_ID", "same")
        monkeypatch.setenv("B_ID", "same")
        spec = _spec(oauth_applications=[_app("a", "A_ID"), _app("b", "B_ID")])
        with pytest.raises(ValueError, match="client ID"):
            runner.check_resolved_collisions(spec, None, ["oauth_applications"])

    def test_a_required_token_fails_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TOKEN", raising=False)
        for name in (
            "django.contrib.auth",
            "django.utils",
            "common.djangoapps.student.models",
            "oauth2_provider.models",
        ):
            monkeypatch.setitem(
                sys.modules,
                name,
                SimpleNamespace(
                    get_user_model=lambda: None,
                    timezone=None,
                    UserProfile=None,
                    get_access_token_model=lambda: None,
                    get_application_model=lambda: None,
                ),
            )
        spec = _spec(service_access_tokens=[{**_token("t", "x"), "optional": False}])
        with pytest.raises(ValueError, match="not optional"):
            runner.apply_service_access_tokens(spec, None)
