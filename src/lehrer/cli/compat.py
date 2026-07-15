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
"""

from __future__ import annotations

import json
import sys
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Annotated

import cyclopts

from lehrer.cli import _paths
from lehrer.core.build_manifest import BuildManifest, load_manifest

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
    if all_cells_flag:
        cells = all_cells(repo_root)
    else:
        if changed_paths:
            paths = changed_paths
        elif not sys.stdin.isatty():
            # No args and piped input: read paths from stdin. Guard on isatty so
            # an interactive invocation returns an empty matrix instead of
            # blocking forever on a read that will never receive EOF.
            paths = sys.stdin.read().splitlines()
        else:
            paths = []
        cells = affected_cells(paths, repo_root)
    print(json.dumps({"any": bool(cells), "cells": cells}))  # noqa: T201
