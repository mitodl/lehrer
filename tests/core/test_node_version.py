from __future__ import annotations

import pytest

from lehrer.core.platform import _pick_latest_node_version, resolve_node_version

# A representative slice of the nodejs release index (newest-first, as served),
# spanning two major lines to exercise prefix matching.
AVAILABLE = [
    "v25.1.0",
    "v25.0.0",
    "v24.18.0",
    "v24.9.0",
    "v24.10.0",
    "v22.14.1",
    "v20.18.0",
]


def test_full_version_is_returned_verbatim_without_lookup() -> None:
    # available omitted on purpose: a full version must never hit the network.
    assert resolve_node_version("24.9.0") == "24.9.0"


def test_bare_major_resolves_to_latest_patch() -> None:
    assert resolve_node_version("24", AVAILABLE) == "24.18.0"


def test_major_minor_prefix_resolves_within_the_minor_line() -> None:
    # 24.10 must not be shadowed by the numerically-larger 24.18.
    assert resolve_node_version("24.10", AVAILABLE) == "24.10.0"


def test_pick_latest_sorts_numerically_not_lexically() -> None:
    # "24.9.0" > "24.18.0" lexically; the numeric key must prefer 24.18.0.
    assert _pick_latest_node_version("24", AVAILABLE) == "24.18.0"


def test_unmatched_prefix_raises() -> None:
    with pytest.raises(ValueError, match="no released Node version matches"):
        resolve_node_version("19", AVAILABLE)
