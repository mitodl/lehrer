from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from lehrer.cli import compat

MANIFEST = """\
version: 1
release_python:
  master: '3.12'
cells:
- release: master
  deployment: mitxonline
  packages:
  - ol-openedx-logging==0.3.5
- release: master
  deployment: mitx
  packages:
  - ol-openedx-logging==0.3.5
- release: ulmo
  deployment: xpro
  packages:
  - ol-openedx-logging==0.3.5
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    group_dir = tmp_path / "deployments" / "mit-ol"
    group_dir.mkdir(parents=True)
    (group_dir / "build_manifest.yaml").write_text(MANIFEST)
    # Clear the module-level manifest-file cache so each tmp repo is read fresh.
    compat._manifest_file.cache_clear()
    return tmp_path


def _keys(
    cells: Sequence[Mapping[str, object]],
) -> set[tuple[object, object, object]]:
    return {(c["group"], c["release"], c["deployment"]) for c in cells}


def test_txt_change_maps_to_single_cell(repo: Path) -> None:
    cells = compat.affected_cells(
        ["deployments/mit-ol/pip_package_lists/master/mitxonline.txt"], repo
    )
    assert _keys(cells) == {("mit-ol", "master", "mitxonline")}
    assert cells[0]["manifest"] == "deployments/mit-ol/build_manifest.yaml"


def test_overrides_change_maps_to_single_cell(repo: Path) -> None:
    cells = compat.affected_cells(
        ["deployments/mit-ol/pip_package_overrides/ulmo/xpro.txt"], repo
    )
    assert _keys(cells) == {("mit-ol", "ulmo", "xpro")}


def test_manifest_change_expands_to_all_cells(repo: Path) -> None:
    cells = compat.affected_cells(["deployments/mit-ol/build_manifest.yaml"], repo)
    assert _keys(cells) == {
        ("mit-ol", "master", "mitxonline"),
        ("mit-ol", "master", "mitx"),
        ("mit-ol", "ulmo", "xpro"),
    }


def test_txt_for_nonexistent_cell_is_skipped(repo: Path) -> None:
    cells = compat.affected_cells(
        ["deployments/mit-ol/pip_package_lists/master/nope.txt"], repo
    )
    assert cells == []


def test_unrelated_paths_ignored(repo: Path) -> None:
    cells = compat.affected_cells(
        [
            "src/lehrer/core/platform.py",
            "README.md",
            "deployments/mit-ol/settings/lms/models/aqueduct.py",
        ],
        repo,
    )
    assert cells == []


def test_dedupes_txt_and_manifest_overlap(repo: Path) -> None:
    cells = compat.affected_cells(
        [
            "deployments/mit-ol/build_manifest.yaml",
            "deployments/mit-ol/pip_package_lists/master/mitxonline.txt",
        ],
        repo,
    )
    assert len(cells) == 3
    assert _keys(cells) == {
        ("mit-ol", "master", "mitxonline"),
        ("mit-ol", "master", "mitx"),
        ("mit-ol", "ulmo", "xpro"),
    }


def test_all_cells(repo: Path) -> None:
    cells = compat.all_cells(repo)
    assert _keys(cells) == {
        ("mit-ol", "master", "mitxonline"),
        ("mit-ol", "master", "mitx"),
        ("mit-ol", "ulmo", "xpro"),
    }


def test_yml_extension_manifest_is_honored(tmp_path: Path) -> None:
    group_dir = tmp_path / "deployments" / "acme"
    group_dir.mkdir(parents=True)
    (group_dir / "build_manifest.yml").write_text(MANIFEST)
    compat._manifest_file.cache_clear()

    # Discovered by both the full-matrix glob and per-path attribution.
    all_keys = _keys(compat.all_cells(tmp_path))
    assert ("acme", "master", "mitxonline") in all_keys

    affected = compat.affected_cells(["deployments/acme/build_manifest.yml"], tmp_path)
    assert _keys(affected) == all_keys
    # The emitted manifest path points at the real .yml file, not a .yaml guess.
    assert affected[0]["manifest"] == "deployments/acme/build_manifest.yml"


# ── settings-verify matrix ────────────────────────────────────────────────────

# Every cell declares django-aqueduct: the settings-verify matrix only covers
# cells that actually use the aqueduct settings mechanism (see _uses_aqueduct).
SETTINGS_MANIFEST = MANIFEST.replace(
    "cells:\n", "settings_model_release: master\ncells:\n", 1
).replace(
    "  - ol-openedx-logging==0.3.5\n",
    "  - ol-openedx-logging==0.3.5\n  - django-aqueduct==0.10.0\n",
)


@pytest.fixture
def settings_repo(tmp_path: Path) -> Path:
    """A repo with two groups: one shipping a settings tree, one not."""
    with_settings = tmp_path / "deployments" / "mit-ol"
    with_settings.mkdir(parents=True)
    (with_settings / "build_manifest.yaml").write_text(SETTINGS_MANIFEST)
    (with_settings / "settings" / "lms" / "models").mkdir(parents=True)

    # No settings/ directory — a group that builds but ships no aqueduct tree
    # must never appear in the matrix, or the dagger call has nothing to mount.
    without_settings = tmp_path / "deployments" / "bare"
    without_settings.mkdir(parents=True)
    (without_settings / "build_manifest.yaml").write_text(MANIFEST)

    compat._manifest_file.cache_clear()
    return tmp_path


def test_settings_change_expands_to_every_cell_in_group(settings_repo: Path) -> None:
    cells = compat.affected_settings_cells(
        ["deployments/mit-ol/settings/lms/aqueduct.py"], settings_repo
    )
    assert _keys(cells) == {
        ("mit-ol", "master", "mitxonline"),
        ("mit-ol", "master", "mitx"),
        ("mit-ol", "ulmo", "xpro"),
    }
    assert all(c["settings"] == "deployments/mit-ol/settings" for c in cells)


def test_core_settings_change_expands_to_every_group(settings_repo: Path) -> None:
    # ProductionSettingsMixin is injected into every build, so a change to it
    # must re-verify every group — not only the one that happened to be edited.
    cells = compat.affected_settings_cells(
        ["src/lehrer/settings/base.py"], settings_repo
    )
    assert {c["group"] for c in cells} == {"mit-ol"}
    assert len(cells) == 3


def test_group_without_settings_tree_is_excluded(settings_repo: Path) -> None:
    assert (
        compat.affected_settings_cells(
            ["deployments/bare/build_manifest.yaml"], settings_repo
        )
        == []
    )
    assert {c["group"] for c in compat.all_settings_cells(settings_repo)} == {"mit-ol"}


def test_drift_only_set_for_the_model_release(settings_repo: Path) -> None:
    cells = compat.all_settings_cells(settings_repo)
    drift = {(c["release"], c["drift"]) for c in cells}
    assert ("master", True) in drift
    assert ("ulmo", False) in drift


def test_drift_never_set_without_settings_model_release(tmp_path: Path) -> None:
    group_dir = tmp_path / "deployments" / "mit-ol"
    group_dir.mkdir(parents=True)
    (group_dir / "build_manifest.yaml").write_text(MANIFEST)
    (group_dir / "settings").mkdir()
    compat._manifest_file.cache_clear()

    assert all(c["drift"] is False for c in compat.all_settings_cells(tmp_path))


def test_unrelated_paths_yield_no_settings_cells(settings_repo: Path) -> None:
    assert (
        compat.affected_settings_cells(
            ["README.md", "src/lehrer/core/platform.py"], settings_repo
        )
        == []
    )


def test_cell_without_django_aqueduct_is_excluded(tmp_path: Path) -> None:
    # Shipping a settings tree is group-level; *using* it is per-cell. A cell
    # that never installs the framework would fail verification with a
    # ModuleNotFoundError that says nothing about the deployment's health.
    # (This is exactly what mit-ol/ulmo/xpro did on the PR that added this.)
    manifest = SETTINGS_MANIFEST.replace(
        "- release: ulmo\n  deployment: xpro\n  packages:\n"
        "  - ol-openedx-logging==0.3.5\n  - django-aqueduct==0.10.0\n",
        "- release: ulmo\n  deployment: xpro\n  packages:\n"
        "  - ol-openedx-logging==0.3.5\n",
    )
    group_dir = tmp_path / "deployments" / "mit-ol"
    group_dir.mkdir(parents=True)
    (group_dir / "build_manifest.yaml").write_text(manifest)
    (group_dir / "settings").mkdir()
    compat._manifest_file.cache_clear()

    cells = compat.all_settings_cells(tmp_path)
    assert ("mit-ol", "ulmo", "xpro") not in _keys(cells)
    assert _keys(cells) == {
        ("mit-ol", "master", "mitxonline"),
        ("mit-ol", "master", "mitx"),
    }


def test_aqueduct_detected_in_overrides_too(tmp_path: Path) -> None:
    # The pin can legitimately live in overrides rather than packages.
    manifest = SETTINGS_MANIFEST.replace(
        "  - ol-openedx-logging==0.3.5\n  - django-aqueduct==0.10.0\n",
        "  - ol-openedx-logging==0.3.5\n  overrides:\n  - django-aqueduct==0.10.0\n",
    )
    group_dir = tmp_path / "deployments" / "mit-ol"
    group_dir.mkdir(parents=True)
    (group_dir / "build_manifest.yaml").write_text(manifest)
    (group_dir / "settings").mkdir()
    compat._manifest_file.cache_clear()

    assert len(compat.all_settings_cells(tmp_path)) == 3
