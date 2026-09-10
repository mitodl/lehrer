"""Detect whether an upstream MFE repository has landed its frontend-base conversion.

Per https://discuss.openedx.org/t/frontend-base-the-plan-for-willow/19438 and
openedx/frontend-base#243, each ``frontend-app-*`` repository's frontend-base
conversion is merged *into* its default branch, and the micro-frontend it
replaces lives on ``legacy-mfe``.  Any pipeline that builds the micro-frontend
from the default branch has to be repointed or retired at that moment, so the
question this module answers is: which branch of this repo still holds a
webpack micro-frontend?

The obvious signal — ``legacy-mfe`` exists — is wrong in both directions, as
observed on 2026-09-01:

* False positive.  Upstream cuts the branch, then merges.  Catalog's branch was
  cut 2026-08-27T19:48Z and frontend-template-application's on 2026-08-17, both
  ahead of the merge.  A poll in that window reports a landing that has not
  happened.
* False negative.  ``legacy-mfe`` is only cut when a supported release still
  ships the micro-frontend.  frontend-app-notifications landed on 2026-08-27
  with ``openedx.org/release: null`` and no branch at all.

The decisive evidence is on the default branch itself: after the merge its
``package.json`` describes an npm module library rather than a webpack app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# `scripts.build` values that mean "this tree still builds a webpack bundle".
# A converted App Repository builds with `make build`, whose target is
# `tsc --project tsconfig.build.json` plus a copy of SCSS and assets into
# `dist/` (checked 2026-09-01 on authn, catalog, notifications and
# instructor-dashboard); the micro-frontends drive fedx-scripts/webpack.
_MICRO_FRONTEND_BUILD_MARKERS = ("fedx-scripts", "webpack")


class Landing(StrEnum):
    """How far along a repository is in the frontend-base landing."""

    LANDED = "landed"
    """The default branch is a frontend-base module library."""

    BRANCH_CUT = "branch_cut"
    """``legacy-mfe`` exists but the default branch is still a micro-frontend.

    Upstream cuts the branch immediately before merging, so this is the last
    warning: the merge is imminent and the pin can be made pre-emptively.
    """

    LEGACY = "legacy"
    """No sign of the landing yet; the default branch builds the MFE."""


@dataclass(frozen=True)
class RepoState:
    """The upstream facts a landing verdict is drawn from.

    Everything here is read from the *default* branch except
    ``legacy_mfe_branch``.
    """

    repo: str
    default_branch: str
    version: str | None = None
    build_script: str | None = None
    has_exports: bool = False
    release_annotation: str | None = None
    """``openedx.org/release`` from ``catalog-info.yaml``.

    ``"legacy-mfe"`` after a landing that a supported release still ships,
    ``None`` after one that none does.  Absent from the file entirely on a
    repository that has not landed.
    """

    release_annotation_present: bool = False
    """Whether the key appeared at all — ``None`` alone is ambiguous."""

    legacy_mfe_branch: bool = False
    npm_dist_tags: dict[str, str] = field(default_factory=dict)


def is_module_library(state: RepoState) -> bool:
    """Return ``True`` when the default branch is a frontend-base module library.

    Two conditions, both required.  ``exports`` alone is not enough: a
    micro-frontend can declare it for its own consumers.  A non-webpack build
    script alone is not enough either, since a repository may wrap webpack in a
    Makefile.
    """
    if not state.has_exports:
        return False
    build = (state.build_script or "").lower()
    return not any(marker in build for marker in _MICRO_FRONTEND_BUILD_MARKERS)


def classify(state: RepoState) -> Landing:
    """Return the landing stage for ``state``."""
    if is_module_library(state):
        return Landing.LANDED
    if state.legacy_mfe_branch:
        return Landing.BRANCH_CUT
    return Landing.LEGACY


def legacy_build_ref(state: RepoState) -> str | None:
    """Return the branch a legacy MFE build should track, or ``None``.

    ``None`` means the micro-frontend is gone: the repository landed without
    cutting ``legacy-mfe`` because no supported release still ships it, so
    there is nothing left to repoint a legacy build at and the build has to be
    retired rather than pinned.
    """
    if state.legacy_mfe_branch:
        return "legacy-mfe"
    if classify(state) is Landing.LANDED:
        return None
    return state.default_branch
