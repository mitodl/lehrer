"""Derive the plugin distributions to smoke-import from a build cell.

The plugin-compat matrix installs a cell's pinned requirement set against the
matching edx-platform branch, then imports every plugin package to catch a
version that resolves but fails at import time.  This module answers the
question *which* distributions are worth importing — the pure, host-side half
of that check.  The distribution → import-module resolution is deliberately
left to runtime (``importlib.metadata`` inside the built container reads each
installed distribution's top-level modules) so no fragile hand-maintained
``dist → module`` mapping can drift and fail a healthy plugin.

A "plugin-like" distribution is one whose normalized name starts with a known
plugin prefix (``ol-``, ``openedx-``, ``edx-``), ends with ``-xblock``, or is
in an explicit include set.  Bare libraries (``granian``, ``django-redis``)
and VCS/URL requirements (``git+https://...``) are skipped: the former carry no
compatibility signal specific to this repo, the latter pin an exact commit that
this matrix is not the right gate for.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Distributions to import even though they do not match a plugin prefix/suffix.
_EXTRA_PLUGIN_DISTS = frozenset(
    {
        "rapid-response-xblock",
        "invideoquiz-xblock",
    }
)

_PLUGIN_PREFIXES = ("ol-", "openedx-", "edx-")
_PLUGIN_SUFFIXES = ("-xblock",)

# Requirement-line lead-ins that are not a plain PyPI distribution spec.
_NON_PYPI_PREFIXES = ("-", "#", "git+", "http://", "https://")

# Characters that terminate the distribution name in a requirement line.
_NAME_TERMINATORS = re.compile(r"[\s\[<>=!~;@#]")


def _distribution_name(line: str) -> str | None:
    """Extract the normalized distribution name from a requirement line.

    Returns ``None`` for blank lines, comments, and VCS/URL requirements.
    Normalization matches PEP 503: lower-cased with runs of ``-``, ``_`` and
    ``.`` collapsed to a single ``-``.
    """
    stripped = line.strip()
    if not stripped:
        return None
    if any(stripped.startswith(prefix) for prefix in _NON_PYPI_PREFIXES):
        return None
    if "://" in stripped:
        return None
    name = _NAME_TERMINATORS.split(stripped, maxsplit=1)[0]
    if not name:
        return None
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_plugin(dist: str) -> bool:
    return (
        dist.startswith(_PLUGIN_PREFIXES)
        or dist.endswith(_PLUGIN_SUFFIXES)
        or dist in _EXTRA_PLUGIN_DISTS
    )


def plugin_distributions(lines: Iterable[str]) -> list[str]:
    """Return the ordered, de-duplicated plugin distribution names in ``lines``.

    ``lines`` are verbatim pip-requirements lines (a cell's ``packages`` +
    ``overrides``, or the contents of a ``pip_package_lists``/
    ``pip_package_overrides`` ``.txt`` file).  Order of first appearance is
    preserved so a failing import points at a predictable position.
    """
    seen: dict[str, None] = {}
    for line in lines:
        dist = _distribution_name(line)
        if dist is not None and _is_plugin(dist) and dist not in seen:
            seen[dist] = None
    return list(seen)
