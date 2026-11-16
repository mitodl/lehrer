from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from lehrer.cli import _paths, features

MIT_OL = Path(__file__).parents[2] / "deployments" / "mit-ol"

DRAWER = {
    "version": 1,
    "feature": "ai-drawer",
    "summary": "Drawer.",
    "origin": "plugin",
    "provided_by": "ol-openedx-chat",
    "frontend_paths": ["legacy"],
    "parameters": {
        "implementation": {
            "type": "enum",
            "choices": ["slot", "standalone"],
            "default": "standalone",
        }
    },
    "requires": {"frontends": ["learning"]},
    "operations": {
        "mfe_build_env": {
            "learning": {
                "ENABLE_AI_DRAWER_SLOT": {
                    "by_parameter": "implementation",
                    "cases": {"slot": "true", "standalone": "false"},
                }
            }
        },
        "bootstrap": {
            "service_access_tokens": [
                {
                    "username": "drawer_svc",
                    "email": "drawer@example.invalid",
                    "token_env": "DRAWER_TOKEN",
                    "application_name": "drawer",
                }
            ]
        },
    },
}


@pytest.fixture
def group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "deployments" / "test-group"
    (root / "features" / "definitions").mkdir(parents=True)
    shutil.copy(MIT_OL / "build_manifest.yaml", root / "build_manifest.yaml")
    (root / "features" / "definitions" / "ai-drawer.yaml").write_text(
        yaml.safe_dump(DRAWER)
    )
    (root / "features" / "scopes.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "scopes": {
                    "qa": {
                        "cell": {"release": "master", "deployment": "mitxonline"},
                        "frontends": {"learning": "legacy"},
                    }
                },
            }
        )
    )
    (root / "features" / "adoption.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "adoption": {"qa": {"ai-drawer": {"implementation": "slot"}}},
            }
        )
    )
    monkeypatch.setattr(_paths, "repo_root", lambda: tmp_path)
    return root


def test_check_passes_a_valid_group(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    features.check("test-group")
    assert "1 scopes, 1 definitions OK" in capsys.readouterr().out


def test_check_reports_and_fails(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adoption = group / "features" / "adoption.yaml"
    adoption.write_text(
        yaml.safe_dump({"version": 1, "adoption": {"qa": {"ai-drawer": {"x": 1}}}})
    )
    with pytest.raises(SystemExit):
        features.check("test-group")
    assert "no parameter 'x'" in capsys.readouterr().err


def test_check_merges_with_a_base_spec(
    group: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        yaml.safe_dump(
            {"users": [{"username": "drawer_svc", "email": "x@example.invalid"}]}
        )
    )
    with pytest.raises(SystemExit):
        features.check("test-group", base_spec=base)
    assert "also declared under users" in capsys.readouterr().err


def test_adopted_shows_resolved_values(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    features.adopted("test-group", "qa")
    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown == {"ai-drawer": {"params": {"implementation": "slot"}, "via": ["qa"]}}


def test_explain_with_a_scope_lists_privilege(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    features.explain("ai-drawer", group="test-group", scope="qa")
    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["mfe_build_env"] == {"learning": {"ENABLE_AI_DRAWER_SLOT": "true"}}
    assert shown["privilege"] == [
        "service account drawer_svc (staff) with a 3650-day token from DRAWER_TOKEN"
    ]


def test_explain_without_a_scope_keeps_placeholders(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    features.explain("ai-drawer", group="test-group")
    shown = yaml.safe_load(capsys.readouterr().out)
    lookup = shown["operations"]["mfe_build_env"]["learning"]["ENABLE_AI_DRAWER_SLOT"]
    assert lookup["by_parameter"] == "implementation"


def test_catalog_lists_group_definitions(
    group: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    features.catalog("test-group")
    (entry,) = yaml.safe_load(capsys.readouterr().out)
    assert entry["feature"] == "ai-drawer"
    assert entry["parameters"]["implementation"]["default"] == "standalone"
