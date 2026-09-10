from __future__ import annotations

from pathlib import Path

import pytest

from lehrer.cli import upstream
from lehrer.cli.upstream import advice
from lehrer.core.upstream import Landing, RepoState, classify, legacy_build_ref

# Shapes observed upstream on 2026-09-01.
LANDED = RepoState(
    repo="openedx/frontend-app-authn",
    default_branch="master",
    version="0.0.0-dev",
    build_script="make build",
    has_exports=True,
    release_annotation="legacy-mfe",
    release_annotation_present=True,
    legacy_mfe_branch=True,
    npm_dist_tags={"latest": "1.0.0", "alpha": "2.0.0-alpha.2"},
)

# frontend-app-notifications: landed, but no supported release ships the MFE,
# so upstream cut no legacy-mfe branch.
LANDED_NO_BRANCH = RepoState(
    repo="openedx/frontend-app-notifications",
    default_branch="master",
    version="0.0.0-dev",
    build_script="make build",
    has_exports=True,
    release_annotation=None,
    release_annotation_present=True,
    legacy_mfe_branch=False,
)

# The window between the branch cut and the merge.
BRANCH_CUT = RepoState(
    repo="openedx/frontend-app-catalog",
    default_branch="master",
    version="0.1.0",
    build_script="fedx-scripts webpack",
    has_exports=False,
    legacy_mfe_branch=True,
)

STILL_LEGACY = RepoState(
    repo="openedx/frontend-app-learning",
    default_branch="master",
    version="0.1.0",
    build_script="fedx-scripts webpack",
    has_exports=False,
    legacy_mfe_branch=False,
)


def test_module_library_on_default_branch_is_landed() -> None:
    assert classify(LANDED) is Landing.LANDED


def test_landing_is_detected_without_a_legacy_mfe_branch() -> None:
    """The branch is cut only when a supported release still ships the MFE."""
    assert classify(LANDED_NO_BRANCH) is Landing.LANDED


def test_legacy_mfe_branch_alone_is_not_a_landing() -> None:
    """Upstream cuts the branch days before the merge; it is a warning, not a landing."""
    assert classify(BRANCH_CUT) is Landing.BRANCH_CUT


def test_untouched_repo_is_legacy() -> None:
    assert classify(STILL_LEGACY) is Landing.LEGACY


def test_exports_without_a_module_build_is_not_a_landing() -> None:
    """A micro-frontend may declare exports for its own consumers."""
    state = RepoState(
        repo="openedx/frontend-app-x",
        default_branch="master",
        build_script="fedx-scripts webpack",
        has_exports=True,
    )
    assert classify(state) is Landing.LEGACY


def test_legacy_build_ref_tracks_the_surviving_branch() -> None:
    assert legacy_build_ref(STILL_LEGACY) == "master"
    assert legacy_build_ref(BRANCH_CUT) == "legacy-mfe"
    assert legacy_build_ref(LANDED) == "legacy-mfe"


def test_legacy_build_ref_is_none_when_the_mfe_is_gone() -> None:
    """Nothing to repoint at — the build has to be retired, not pinned."""
    assert legacy_build_ref(LANDED_NO_BRANCH) is None


def test_advice_names_the_exposed_deployments() -> None:
    assert "mitxonline" in advice(LANDED, exposed_deployments=["mitxonline"])


def test_advice_for_a_gone_mfe_says_to_drop_the_build() -> None:
    assert "drop the legacy build" in advice(
        LANDED_NO_BRANCH, exposed_deployments=["mitxonline"]
    )


def test_untouched_repo_needs_no_action() -> None:
    assert advice(STILL_LEGACY, exposed_deployments=["mitxonline"]).startswith(
        "no action"
    )


def test_release_annotation_distinguishes_null_from_absent() -> None:
    """`null` means landed-with-no-release; a missing key means not landed."""
    landed = """\
apiVersion: backstage.io/v1alpha1
metadata:
  annotations:
    openedx.org/release: null
"""
    not_landed = """\
apiVersion: backstage.io/v1alpha1
metadata:
  annotations:
    openedx.org/arch-interest-groups: ''
"""
    assert upstream._release_annotation(landed) == (True, None)
    assert upstream._release_annotation(not_landed) == (False, None)
    assert upstream._release_annotation(None) == (False, None)


def test_watch_list_round_trips(tmp_path: Path) -> None:
    (tmp_path / "upstream_watch.yaml").write_text(
        "repos:\n"
        "- repo: openedx/frontend-app-learning\n"
        "  exposed_deployments: [mitxonline]\n"
    )
    entries = upstream.load_watch_list(tmp_path)
    assert entries == [
        {"repo": "openedx/frontend-app-learning", "exposed_deployments": ["mitxonline"]}
    ]


def test_missing_watch_list_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="upstream_watch.yaml"):
        upstream.load_watch_list(tmp_path)


def test_shipped_mit_ol_watch_list_is_well_formed() -> None:
    from lehrer.cli import _paths

    entries = upstream.load_watch_list(_paths.repo_root() / "deployments" / "mit-ol")
    assert entries
    for entry in entries:
        assert entry["repo"].startswith("openedx/frontend-app-")
        assert isinstance(entry["exposed_deployments"], list)
