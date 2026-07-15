from __future__ import annotations

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


def _keys(cells: list[dict[str, str]]) -> set[tuple[str, str, str]]:
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
