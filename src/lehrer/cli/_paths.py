"""Locate the lehrer repository checkout and its local-dev assets.

The CLI is installed as a console script, so it cannot assume that the current
working directory is the repo root.  It also cannot assume that ``__file__``
lives inside the repo (an editable ``uv`` install keeps it in ``src/`` but a
wheel install would not).  We therefore search upward from both the working
directory and this module for the unambiguous marker
``local-dev/k3d-config.yaml``, and allow an explicit override via the
``LEHRER_REPO_ROOT`` environment variable.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

_MARKER = Path("local-dev") / "k3d-config.yaml"


class RepoNotFoundError(RuntimeError):
    """Raised when the lehrer checkout cannot be located."""

    def __init__(self) -> None:
        super().__init__(
            "could not locate the lehrer repository "
            f"(looked for {_MARKER}). Run from inside the checkout or set "
            "LEHRER_REPO_ROOT."
        )


def _search_from(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / _MARKER).is_file():
            return candidate
    return None


@cache
def repo_root() -> Path:
    """Return the absolute path to the lehrer checkout root."""
    override = os.environ.get("LEHRER_REPO_ROOT")
    if override:
        root = Path(override).resolve()
        if (root / _MARKER).is_file():
            return root
        raise RepoNotFoundError()

    for start in (Path.cwd(), Path(__file__).parent):
        found = _search_from(start)
        if found is not None:
            return found
    raise RepoNotFoundError()


def local_dev_dir() -> Path:
    """Return ``<repo>/local-dev``."""
    return repo_root() / "local-dev"


def tiltfile() -> Path:
    """Return the path to the standalone Tiltfile."""
    return local_dev_dir() / "Tiltfile"


def k3d_config() -> Path:
    """Return the path to the k3d cluster config."""
    return local_dev_dir() / "k3d-config.yaml"


def namespace_manifest() -> Path:
    """Return the path to the openedx namespace manifest."""
    return local_dev_dir() / "manifests" / "namespace.yaml"
