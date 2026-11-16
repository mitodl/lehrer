from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from lehrer.bootstrap.spec import BootstrapSpec
from lehrer.core import mfe
from lehrer.core.feature_artifacts import emit, write
from lehrer.core.feature_manifest import FeatureManifestError, Group
from test_feature_manifest import AI_DRAWER, _definition, _group

CHAT = _definition(
    feature="course-chat",
    origin="plugin",
    provided_by="ol-openedx-chat",
    frontend_paths=["legacy"],
    parameters={"limit": {"type": "integer", "default": 20}},
    requires={
        "plugins": ["ol-openedx-chat"],
        "frontends": ["learning"],
        "services": ["notes"],
        "secret_settings": ["CHAT_API_KEY"],
    },
    operations={
        "settings": {"lms": {"ENABLE_AUTHN_MICROFRONTEND": True}},
        "features": {"lms": {"ENABLE_COURSE_SORTING_BY_START_DATE": True, "CHAT_X": 1}},
        "site_config": {
            "frontend_site_config": {"commonAppConfig": {"chat": {"limit": "${limit}"}}}
        },
        "bootstrap": {
            "waffle_flags": [{"name": "course_chat.enabled", "everyone": True}],
            "service_access_tokens": [
                {
                    "username": "chat_svc",
                    "email": "chat@example.invalid",
                    "token_env": "CHAT_TOKEN",
                    "application_name": "chat",
                }
            ],
        },
        "mfe_assets": {
            "learning": {
                "extra_slot_files": ["Footer.jsx:ChatFooter.jsx"],
                "extra_npm_bundles": ["@example/chat@^1|public/static/chat"],
            }
        },
        "commands": [{"id": "backfill", "service": "lms", "argv": ["manage.py", "x"]}],
    },
)


def _emitted(group: Group, scope: str = "mxo-ci") -> dict[str, str]:
    return emit(group, group.resolve(scope), "mit-ol")


@pytest.fixture
def group() -> Group:
    return _group(
        [AI_DRAWER, CHAT],
        {
            "mxo-ci": {
                "ai-drawer": {"implementation": "slot"},
                "course-chat": {"limit": 50},
            }
        },
    )


def test_output_is_byte_stable(group: Group) -> None:
    assert _emitted(group) == _emitted(group)


def test_settings_fragment(group: Group) -> None:
    lms = yaml.safe_load(_emitted(group)["settings/lms.yaml"])
    # Aliased setting under the key pydantic-settings reads.
    assert lms["EDXAPP_ENABLE_AUTHN_MFE"] is True
    # An inventoried FEATURES key goes to both places; an unknown one to FEATURES only.
    assert lms["ENABLE_COURSE_SORTING_BY_START_DATE"] is True
    assert lms["FEATURES"] == {"ENABLE_COURSE_SORTING_BY_START_DATE": True, "CHAT_X": 1}
    assert "CHAT_X" not in lms
    assert lms["FRONTEND_SITE_CONFIG"] == {"commonAppConfig": {"chat": {"limit": 50}}}
    assert yaml.safe_load(_emitted(group)["settings/cms.yaml"]) == {}


def test_bootstrap_holds_feature_entries_as_required(group: Group) -> None:
    spec = BootstrapSpec.model_validate(
        yaml.safe_load(_emitted(group)["bootstrap.yaml"])
    )
    assert [f.name for f in spec.waffle_flags] == ["course_chat.enabled"]
    assert spec.service_access_tokens[0].optional is False


def test_legacy_build_inputs(group: Group) -> None:
    files = _emitted(group)
    assert files["mfe_build_env/learning.env"] == "ENABLE_AI_DRAWER_SLOT=true\n"
    assets = yaml.safe_load(files["mfe_assets/learning.yaml"])
    assert assets == {
        "contract_version": 1,
        "extra_slot_files": [{"source": "Footer.jsx", "dest": "ChatFooter.jsx"}],
        "extra_npm_bundles": [
            {"spec": "@example/chat@^1", "target": "public/static/chat"}
        ],
    }


def test_checklist_and_manifest(group: Group) -> None:
    files = _emitted(group)
    checklist = yaml.safe_load(files["checklist.yaml"])
    assert checklist["services"] == ["notes"]
    assert checklist["plugins"] == ["ol-openedx-chat"]
    assert checklist["commands"][0]["id"] == "backfill"
    assert checklist["runtime_config_api"]["features"] == ["course-chat"]
    manifest = json.loads(files["manifest.json"])
    assert manifest["contract_version"] == 1
    assert manifest["bootstrap_env"] == ["CHAT_TOKEN"]
    assert manifest["secret_settings"] == ["CHAT_API_KEY"]
    assert set(manifest["build_digest"]) == {"learning"}
    assert manifest["generated_from"]["features"]["course-chat"] == {"limit": 50}


def test_write_replaces_a_previous_compile(group: Group, tmp_path: Path) -> None:
    out = tmp_path / "out"
    write({**_emitted(group), "mfe_build_env/gone.env": "X=1\n"}, out)
    write(_emitted(group), out)
    assert not (out / "mfe_build_env" / "gone.env").exists()
    assert (out / "manifest.json").is_file()


def test_write_refuses_a_foreign_directory(group: Group, tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(FeatureManifestError, match="refusing"):
        write(_emitted(group), tmp_path)
    assert (tmp_path / "keep.txt").exists()


class TestMfeBuildInputs:
    def test_resolves_one_mfe(self, group: Group) -> None:
        inputs = group.mfe_build_inputs("mxo-ci", "learning", "master", "mitxonline")
        assert inputs.env_vars() == ["ENABLE_AI_DRAWER_SLOT=true"]
        assert inputs.slot_specs() == ["Footer.jsx:ChatFooter.jsx"]
        assert inputs.bundle_specs() == ["@example/chat@^1|public/static/chat"]

    def test_needs_no_build_manifest(self, group: Group) -> None:
        group.manifest = None
        group.mfe_build_inputs("mxo-ci", "learning", "master", "mitxonline")

    def test_refuses_a_different_cell(self, group: Group) -> None:
        with pytest.raises(FeatureManifestError, match="this build is master/mitx"):
            group.mfe_build_inputs("mxo-ci", "learning", "master", "mitx")

    def test_refuses_a_site_project_mfe(self) -> None:
        group = _group([], {})
        with pytest.raises(FeatureManifestError, match="Site Project"):
            group.mfe_build_inputs("site-ci", "learning", "master", "mitxonline")


class _Dir:
    """Just enough of dagger.Directory: glob, file().contents(), exists()."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    async def glob(self, pattern: str) -> list[str]:
        # Strict about **: here it needs at least one directory, the case the
        # caller has to cope with.
        if pattern == "*.yaml":
            return sorted(p for p in self.files if "/" not in p and p.endswith(".yaml"))
        return sorted(p for p in self.files if "/" in p and p.endswith(".yaml"))

    def file(self, path: str) -> Any:
        text = self.files[path]

        class _File:
            async def contents(self) -> str:
                return text

        return _File()

    async def exists(self, path: str) -> bool:
        return path in self.files


def _features_tree(adoption: dict[str, Any]) -> _Dir:
    return _Dir(
        {
            "scopes.yaml": yaml.safe_dump(
                {
                    "version": 1,
                    "scopes": {
                        "qa": {
                            "cell": {"release": "master", "deployment": "mitxonline"},
                            "frontends": {"learning": "legacy"},
                        }
                    },
                }
            ),
            "adoption.yaml": yaml.safe_dump({"version": 1, "adoption": adoption}),
            "definitions/ai-drawer.yaml": yaml.safe_dump(AI_DRAWER),
        }
    )


def _build(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_build_legacy(self: Any, **build: Any) -> str:
        captured.update(build)
        return "built"

    monkeypatch.setattr(
        mfe.OpenedxMfe, "build_legacy", fake_build_legacy, raising=False
    )
    slot_config = _Dir({"build_config.yaml": "{}\n"})
    asyncio.run(
        mfe.OpenedxMfe.build_legacy_configured(
            mfe.OpenedxMfe(),
            mfe_name="learning",
            slot_config=slot_config,  # type: ignore[arg-type]
            deployment_name="mitxonline",
            release_name="master",
            **kwargs,
        )
    )
    return captured


class TestBuildLegacyConfigured:
    def test_without_features_nothing_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        build = _build(monkeypatch, env_vars=["A=1"])
        assert build["env_vars"] == ["A=1"]
        assert build["extra_slot_files"] == []

    def test_scope_adds_its_build_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tree = _features_tree({"qa": {"ai-drawer": {"implementation": "slot"}}})
        build = _build(monkeypatch, env_vars=["A=1"], features=tree, scope="qa")
        assert build["env_vars"] == ["A=1", "ENABLE_AI_DRAWER_SLOT=true"]

    def test_explicit_env_var_must_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tree = _features_tree({"qa": {"ai-drawer": {"implementation": "slot"}}})
        with pytest.raises(ValueError, match="ENABLE_AI_DRAWER_SLOT"):
            _build(
                monkeypatch,
                env_vars=["ENABLE_AI_DRAWER_SLOT=false"],
                features=tree,
                scope="qa",
            )

    def test_features_and_scope_go_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValueError, match="used together"):
            _build(monkeypatch, scope="qa")
