"""``lehrer compat`` — enumerate plugin-compat matrix cells.

The plugin-compat CI workflow verifies that each ``(release, deployment)``
build cell's pinned requirement set still installs and imports against its
matching edx-platform branch.  Running the *whole* cross-product on every PR
is wasteful, so on a PR we run only the cells a diff actually touches; on the
weekly schedule we run the full matrix.

This module turns a set of changed file paths into that list of cells and
emits it as JSON for a GitHub Actions ``matrix``.  A change is attributed to a
cell three ways:

* ``deployments/<group>/pip_package_lists/<release>/<deployment>.txt`` — the
  single cell named by the path.
* ``deployments/<group>/pip_package_overrides/<release>/<deployment>.txt`` —
  same.
* ``deployments/<group>/build_manifest.yaml`` — every cell in that manifest
  (a manifest edit is not attributable to one cell from the path alone, and
  Renovate now bumps pinned versions inside the manifest too).

Every emitted cell is validated against its group's on-disk manifest, so the
downstream ``dagger call platform check-deployment --build-manifest ...`` is
always given a cell the manifest actually defines.

``settings-matrix`` is the sibling command for the settings-verify workflow
(``dagger call platform verify-settings``).  It answers a coarser question —
which cells' *settings trees* need re-booting — so its attribution rules
differ; see :func:`affected_settings_cells`.
"""

from __future__ import annotations

import json
import sys
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Annotated

import cyclopts

from lehrer.cli import _paths
from lehrer.core.build_manifest import BuildManifest, Cell, load_manifest

app = cyclopts.App(
    name="compat",
    help="Enumerate plugin-compatibility matrix cells for CI.",
)

_DEPLOYMENTS = "deployments"
_MANIFEST_NAMES = ("build_manifest.yaml", "build_manifest.yml")
_LIST_DIRS = ("pip_package_lists", "pip_package_overrides")


@cache
def _manifest_file(repo_root: Path, group: str) -> Path | None:
    """Return the group's existing ``build_manifest.{yaml,yml}``, or ``None``.

    Both extensions in ``_MANIFEST_NAMES`` are honoured so an operator on
    ``.yml`` is not silently ignored.
    """
    for name in _MANIFEST_NAMES:
        path = repo_root / _DEPLOYMENTS / group / name
        if path.exists():
            return path
    return None


def _manifest_rel_path(repo_root: Path, group: str) -> str:
    """POSIX repo-relative path of the group's manifest (``.yaml`` if absent)."""
    path = _manifest_file(repo_root, group)
    if path is None:
        return f"{_DEPLOYMENTS}/{group}/build_manifest.yaml"
    return path.relative_to(repo_root).as_posix()


def _load_group_manifest(repo_root: Path, group: str) -> BuildManifest | None:
    """Load the group's ``build_manifest.{yaml,yml}``, or ``None`` if absent."""
    path = _manifest_file(repo_root, group)
    if path is None:
        return None
    return load_manifest(path)


def _cell(repo_root: Path, group: str, release: str, deployment: str) -> dict[str, str]:
    return {
        "group": group,
        "release": release,
        "deployment": deployment,
        "manifest": _manifest_rel_path(repo_root, group),
    }


def _manifest_cells(repo_root: Path, group: str) -> list[dict[str, str]]:
    manifest = _load_group_manifest(repo_root, group)
    if manifest is None:
        return []
    return [_cell(repo_root, group, c.release, c.deployment) for c in manifest.cells]


def _cell_exists(repo_root: Path, group: str, release: str, deployment: str) -> bool:
    manifest = _load_group_manifest(repo_root, group)
    if manifest is None:
        return False
    return any(
        c.release == release and c.deployment == deployment for c in manifest.cells
    )


def _cells_for_path(path: str, repo_root: Path) -> list[dict[str, str]]:
    """Return the matrix cell(s) a single changed path maps to (may be empty)."""
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != _DEPLOYMENTS:  # noqa: PLR2004
        return []
    group = parts[1]

    # A manifest edit → every cell in that group's manifest.
    if len(parts) == 3 and parts[2] in _MANIFEST_NAMES:  # noqa: PLR2004
        return _manifest_cells(repo_root, group)

    # A requirements .txt edit → the single cell named by the path:
    #   deployments/<group>/<list_dir>/<release>/<deployment>.txt
    if (
        len(parts) == 5  # noqa: PLR2004
        and parts[2] in _LIST_DIRS
        and parts[4].endswith(".txt")
    ):
        release = parts[3]
        deployment = PurePosixPath(parts[4]).stem
        if _cell_exists(repo_root, group, release, deployment):
            return [_cell(repo_root, group, release, deployment)]
        sys.stderr.write(
            f"compat: skipping {path} — no ({release}, {deployment}) cell in "
            f"{_manifest_rel_path(repo_root, group)}\n"
        )
    return []


def _dedupe(cells: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: dict[tuple[str, str, str], dict[str, str]] = {}
    for cell in cells:
        seen.setdefault((cell["group"], cell["release"], cell["deployment"]), cell)
    return list(seen.values())


def affected_cells(changed_paths: list[str], repo_root: Path) -> list[dict[str, str]]:
    """Map changed file paths to the plugin-compat cells they affect."""
    cells: list[dict[str, str]] = []
    for path in changed_paths:
        cells.extend(_cells_for_path(path.strip(), repo_root))
    return _dedupe(cells)


def all_cells(repo_root: Path) -> list[dict[str, str]]:
    """Every cell across all ``deployments/*/build_manifest.{yaml,yml}`` manifests."""
    manifest_paths: list[Path] = []
    for name in _MANIFEST_NAMES:
        manifest_paths.extend(repo_root.glob(f"{_DEPLOYMENTS}/*/{name}"))
    cells: list[dict[str, str]] = []
    for manifest_path in sorted(manifest_paths):
        group = manifest_path.parent.name
        cells.extend(_manifest_cells(repo_root, group))
    return _dedupe(cells)


def _input_paths(changed_paths: list[str] | None) -> list[str]:
    """Changed paths from argv, else from a piped stdin, else empty.

    Guard on ``isatty`` so an interactive invocation returns an empty matrix
    instead of blocking forever on a read that will never receive EOF.
    """
    if changed_paths:
        return changed_paths
    if not sys.stdin.isatty():
        return sys.stdin.read().splitlines()
    return []


_SETTINGS_DIR = "settings"
# Injected into every build's settings tree from lehrer core
# (``inject_aqueduct_settings``), so a change here affects every cell in every
# group — not just the group whose files were edited.
_CORE_SETTINGS_PREFIX = "src/lehrer/settings/"
# Distribution whose presence in a cell means that cell uses the aqueduct
# settings mechanism at all (see _uses_aqueduct).
_AQUEDUCT_DIST = "django-aqueduct"


def _settings_cell(
    repo_root: Path, group: str, release: str, deployment: str, *, drift: bool
) -> dict[str, str | bool]:
    cell = _cell(repo_root, group, release, deployment)
    return {
        **cell,
        "settings": f"{_DEPLOYMENTS}/{group}/{_SETTINGS_DIR}",
        "drift": drift,
    }


def _has_settings_tree(repo_root: Path, group: str) -> bool:
    return (repo_root / _DEPLOYMENTS / group / _SETTINGS_DIR).is_dir()


def _uses_aqueduct(cell: Cell) -> bool:
    """Whether a cell installs django-aqueduct, i.e. uses the aqueduct settings.

    Shipping a settings tree is a *group*-level fact, but using it is per-cell:
    a group can have cells still on an older settings mechanism that never
    install the framework.  Verifying those would import
    ``<svc>.envs.aqueduct`` in a container where ``django_aqueduct`` does not
    exist and fail with a ModuleNotFoundError that says nothing about the
    deployment's actual health.  Deriving the predicate from the cell's own
    requirement lines keeps it self-maintaining — a cell starts being verified
    the moment it adopts the framework, with no second list to update.
    """
    return any(_AQUEDUCT_DIST in line for line in (*cell.packages, *cell.overrides))


def _settings_cells_for_group(
    repo_root: Path, group: str
) -> list[dict[str, str | bool]]:
    """Settings-verify cells for a group: those that ship *and* use a settings tree."""
    manifest = _load_group_manifest(repo_root, group)
    if manifest is None or not _has_settings_tree(repo_root, group):
        return []
    drift_release = manifest.settings_model_release
    return [
        _settings_cell(
            repo_root,
            group,
            c.release,
            c.deployment,
            drift=drift_release is not None and c.release == drift_release,
        )
        for c in manifest.cells
        if _uses_aqueduct(c)
    ]


def _all_settings_groups(repo_root: Path) -> list[str]:
    groups: list[str] = []
    for name in _MANIFEST_NAMES:
        groups.extend(
            path.parent.name for path in repo_root.glob(f"{_DEPLOYMENTS}/*/{name}")
        )
    return sorted(set(groups))


def affected_settings_cells(
    changed_paths: list[str], repo_root: Path
) -> list[dict[str, str | bool]]:
    """Map changed paths to the settings-verify cells they affect.

    Attribution is deliberately coarse — a settings change is not attributable
    to one cell from the path alone, and an under-broad matrix here means a
    broken settings tree merges unverified:

    * ``deployments/<group>/settings/**`` — every cell in that group.
    * ``deployments/<group>/build_manifest.{yaml,yml}`` — every cell in that
      group; a plugin bump changes the apps the settings overlay resolves over.
    * ``src/lehrer/settings/**`` — every cell in every group, since
      ``ProductionSettingsMixin`` is injected into all of them.
    """
    groups: set[str] = set()
    all_groups = False
    for raw in changed_paths:
        path = raw.strip()
        if path.startswith(_CORE_SETTINGS_PREFIX):
            all_groups = True
            continue
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != _DEPLOYMENTS:  # noqa: PLR2004
            continue
        if parts[2] == _SETTINGS_DIR or parts[2] in _MANIFEST_NAMES:
            groups.add(parts[1])

    selected = _all_settings_groups(repo_root) if all_groups else sorted(groups)
    cells: list[dict[str, str | bool]] = []
    for group in selected:
        cells.extend(_settings_cells_for_group(repo_root, group))
    return cells


def all_settings_cells(repo_root: Path) -> list[dict[str, str | bool]]:
    """Every settings-verify cell across all groups that ship a settings tree."""
    cells: list[dict[str, str | bool]] = []
    for group in _all_settings_groups(repo_root):
        cells.extend(_settings_cells_for_group(repo_root, group))
    return cells


@app.command
def matrix(
    changed_paths: Annotated[
        list[str] | None,
        cyclopts.Parameter(
            help=(
                "Changed file paths (repo-relative). If omitted and --all is "
                "not set, paths are read from a non-tty stdin, one per line."
            )
        ),
    ] = None,
    *,
    all_cells_flag: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--all"],
            help="Emit the full matrix (every cell) instead of diff-affected cells.",
        ),
    ] = False,
) -> None:
    """Print the plugin-compat matrix as JSON for a GitHub Actions job.

    Output shape: ``{"any": <bool>, "cells": [{group, release, deployment,
    manifest}, ...]}``.  ``any`` lets the workflow skip the matrix job cleanly
    when a diff touched no requirements (GitHub Actions errors on an empty
    matrix), and the job summary can log exactly which cells ran.
    """
    repo_root = _paths.repo_root()
    cells = (
        all_cells(repo_root)
        if all_cells_flag
        else affected_cells(_input_paths(changed_paths), repo_root)
    )
    print(json.dumps({"any": bool(cells), "cells": cells}))  # noqa: T201


@app.command
def settings_matrix(
    changed_paths: Annotated[
        list[str] | None,
        cyclopts.Parameter(
            help=(
                "Changed file paths (repo-relative). If omitted and --all is "
                "not set, paths are read from a non-tty stdin, one per line."
            )
        ),
    ] = None,
    *,
    all_cells_flag: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--all"],
            help="Emit the full matrix (every cell) instead of diff-affected cells.",
        ),
    ] = False,
) -> None:
    """Print the settings-verify matrix as JSON for a GitHub Actions job.

    Feeds ``dagger call platform verify-settings``, which boots each group's
    committed aqueduct settings tree against a cell's pinned plugin set.

    Output shape: ``{"any": <bool>, "cells": [{group, release, deployment,
    manifest, settings, drift}, ...]}`` — ``settings`` is the group's settings
    directory and ``drift`` says whether that cell's release matches the
    manifest's ``settings_model_release`` (only then can the committed model be
    compared against a fresh render).
    """
    repo_root = _paths.repo_root()
    cells = (
        all_settings_cells(repo_root)
        if all_cells_flag
        else affected_settings_cells(_input_paths(changed_paths), repo_root)
    )
    print(json.dumps({"any": bool(cells), "cells": cells}))  # noqa: T201
