from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lehrer.bootstrap import __main__ as runner
from lehrer.bootstrap.spec import (
    BootstrapSpec,
    WaffleFlag,
    from_env,
    json_schema,
    resolve,
)

PACKAGE = Path(runner.__file__).parent


class TestWaffleFlag:
    @pytest.mark.parametrize(
        ("flag", "argv"),
        [
            (
                WaffleFlag(name="f", everyone=True),
                ["f", "--everyone", "--create"],
            ),
            (
                WaffleFlag(name="f", everyone=False, create=False),
                ["f", "--deactivate"],
            ),
            (
                WaffleFlag(name="f", superusers=True, staff=True, authenticated=True),
                ["f", "--superusers", "--staff", "--authenticated", "--create"],
            ),
            (
                WaffleFlag(name="f", percent=12.5, rollout=True, testing=True),
                ["f", "--rollout", "--testing", "--percent", "12.5", "--create"],
            ),
        ],
    )
    def test_argv(self, flag: WaffleFlag, argv: list[str]) -> None:
        assert flag.argv() == argv

    def test_unset_everyone_passes_neither_switch(self) -> None:
        argv = WaffleFlag(name="f").argv()
        assert "--everyone" not in argv
        assert "--deactivate" not in argv

    # Every option ol-infrastructure's edxapp:waffle_flags lists use today.
    @pytest.mark.parametrize(
        "argv",
        [
            ["a", "--create", "--everyone"],
            ["a", "--create", "--deactivate"],
            ["a", "--create", "--superusers"],
            ["a", "--create", "--staff", "--authenticated"],
            ["a", "--percent", "50", "--rollout"],
        ],
    )
    def test_from_argv_round_trips(self, argv: list[str]) -> None:
        flag = WaffleFlag.from_argv(argv)
        assert sorted(WaffleFlag.from_argv(flag.argv()).argv()) == sorted(flag.argv())
        assert set(flag.argv()) - {"50.0"} == set(argv) - {"50"}

    def test_from_argv_refuses_what_it_cannot_express(self) -> None:
        with pytest.raises(ValueError, match="--group"):
            WaffleFlag.from_argv(["a", "--group", "staff"])

    def test_percent_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            WaffleFlag(name="f", percent=101)


class TestSpec:
    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            BootstrapSpec.model_validate({"waffles": []})

    def test_secrets_are_referenced_by_env_name(self) -> None:
        properties = json_schema()["$defs"]["OAuthApplication"]["properties"]
        assert "client_secret_env" in properties
        assert "client_secret" not in properties


class TestResolve:
    def test_substitutes_settings(self) -> None:
        settings = SimpleNamespace(CMS_ROOT_URL="http://localhost:8010")
        assert (
            resolve("{CMS_ROOT_URL}/complete/edx-oauth2/", settings)
            == "http://localhost:8010/complete/edx-oauth2/"
        )

    def test_names_a_missing_setting(self) -> None:
        with pytest.raises(ValueError, match="CMS_ROOT_URL"):
            resolve("{CMS_ROOT_URL}/x", SimpleNamespace())


def test_from_env_names_a_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEHRER_TEST_UNSET", raising=False)
    with pytest.raises(ValueError, match="LEHRER_TEST_UNSET"):
        from_env("LEHRER_TEST_UNSET")


def test_steps_are_validated() -> None:
    with pytest.raises(SystemExit):
        runner.main(["spec.yaml", "--steps", "users,nope"])


def test_the_image_package_imports_only_what_the_image_has() -> None:
    # The platform image carries this package as lehrer_bootstrap, beside no
    # other part of lehrer. At module level it may import the stdlib, pydantic,
    # PyYAML and itself (relatively); Django and edx-platform are imported
    # inside the functions that run after django.setup().
    allowed = set(sys.stdlib_module_names) | {"pydantic", "yaml", "__future__"}
    for module in PACKAGE.glob("*.py"):
        tree = ast.parse(module.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert roots <= allowed, f"{module.name} imports {roots - allowed}"
