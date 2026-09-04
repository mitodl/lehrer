"""``lehrer upstream`` — track upstream Open edX frontend state.

Today this is one question: has an ``openedx/frontend-app-*`` repository landed
its frontend-base conversion into its default branch?  That merge turns the
default branch into an npm module library, so any OL legacy MFE build tracking
it stops producing a servable bundle and has to be repointed at ``legacy-mfe``
or absorbed into a Site Project.

The detection rules, and why the obvious ``legacy-mfe``-branch check is not one
of them, are in :mod:`lehrer.core.upstream`.  This module supplies the I/O: it
reads the watch list from the deployment group's ``upstream_watch.yaml`` and
the upstream facts from the GitHub and npm CLIs.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import cyclopts
import yaml

from lehrer.cli import _paths
from lehrer.cli._proc import CommandError, require
from lehrer.core.upstream import Landing, RepoState, classify, legacy_build_ref

app = cyclopts.App(
    name="upstream",
    help="Track upstream Open edX frontend state.",
)

_WATCH_FILE = "upstream_watch.yaml"


def _gh_json(*args: str) -> Any | None:
    """Run ``gh api`` and parse its JSON, returning ``None`` for a 404.

    A missing branch or file is an ordinary answer here ("no ``legacy-mfe``
    branch"), not a failure, so it must not raise.
    """
    completed = subprocess.run(  # noqa: S603 - argv is an explicit token list
        ["gh", "api", *args],  # noqa: S607 - resolved via PATH, checked by require()
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        if "404" in completed.stderr or "Not Found" in completed.stderr:
            return None
        raise CommandError(["gh", "api", *args], completed.returncode)
    return json.loads(completed.stdout)


def _gh_file(repo: str, ref: str, path: str) -> str | None:
    """Return the decoded contents of ``path`` at ``ref``, or ``None`` if absent."""
    # No `--jq`: it unwraps to a bare string, which is not JSON for the caller
    # to parse. Take the whole contents object and pull the field out here.
    payload = _gh_json(f"repos/{repo}/contents/{path}?ref={ref}")
    if payload is None or "content" not in payload:
        return None
    return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")


def _npm_dist_tags(package: str) -> dict[str, str]:
    """Return ``package``'s npm dist-tags, empty when it is unpublished."""
    completed = subprocess.run(  # noqa: S603
        ["npm", "view", package, "dist-tags", "--json"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}
    tags = json.loads(completed.stdout)
    return tags if isinstance(tags, dict) else {}


def _release_annotation(catalog_info: str | None) -> tuple[bool, str | None]:
    """Pull ``openedx.org/release`` out of a ``catalog-info.yaml``.

    Returns ``(present, value)``.  The distinction matters: the key set to
    ``null`` means "landed, and no supported release ships the micro-frontend",
    while the key being absent means the repository has not landed at all.
    """
    if catalog_info is None:
        return False, None
    try:
        parsed = yaml.safe_load(catalog_info)
    except yaml.YAMLError:
        return False, None
    annotations = (parsed or {}).get("metadata", {}).get("annotations", {})
    if not isinstance(annotations, dict) or "openedx.org/release" not in annotations:
        return False, None
    return True, annotations["openedx.org/release"]


def fetch_state(repo: str, *, check_npm: bool = True) -> RepoState:
    """Read the upstream facts for ``repo`` (``owner/name``) from GitHub and npm."""
    meta = _gh_json(f"repos/{repo}")
    if meta is None:
        message = f"upstream repository not found: {repo}"
        raise CommandError([message], 1)
    default_branch = meta["default_branch"]

    package_json = _gh_file(repo, default_branch, "package.json")
    package: dict[str, Any] = {}
    if package_json:
        try:
            package = json.loads(package_json)
        except json.JSONDecodeError:
            package = {}

    present, annotation = _release_annotation(
        _gh_file(repo, default_branch, "catalog-info.yaml")
    )

    name = package.get("name") or f"@openedx/{repo.split('/')[-1]}"
    return RepoState(
        repo=repo,
        default_branch=default_branch,
        version=package.get("version"),
        build_script=(package.get("scripts") or {}).get("build"),
        has_exports=bool(package.get("exports")),
        release_annotation=annotation,
        release_annotation_present=present,
        legacy_mfe_branch=_gh_json(f"repos/{repo}/branches/legacy-mfe") is not None,
        npm_dist_tags=_npm_dist_tags(name) if check_npm else {},
    )


def load_watch_list(deployment_config: Path) -> list[dict[str, Any]]:
    """Return the ``repos`` entries from a deployment group's watch file."""
    watch_file = deployment_config / _WATCH_FILE
    if not watch_file.is_file():
        message = f"no {_WATCH_FILE} in {deployment_config}"
        raise CommandError([message], 1)
    parsed = yaml.safe_load(watch_file.read_text()) or {}
    return list(parsed.get("repos") or [])


def advice(state: RepoState, *, exposed_deployments: list[str]) -> str:
    """One line on what, if anything, the exposure to ``state`` now requires.

    Lives here rather than in :mod:`lehrer.core.upstream` because it speaks in
    terms of OL deployments, which core must stay ignorant of.
    """
    stage = classify(state)
    if stage is Landing.LEGACY:
        return "no action — default branch still builds the micro-frontend"

    if not exposed_deployments:
        which = "no OL deployment builds this from its default branch"
    else:
        which = f"builds from the default branch: {', '.join(exposed_deployments)}"

    if stage is Landing.BRANCH_CUT:
        return f"merge imminent — pin to legacy-mfe now ({which})"
    if legacy_build_ref(state) is None:
        return (
            "landed with no legacy-mfe branch — the micro-frontend is gone; "
            f"drop the legacy build and consume the npm module instead ({which})"
        )
    return f"landed — pin to legacy-mfe or absorb into the Site Project ({which})"


_STAGE_LABEL = {
    Landing.LANDED: "LANDED",
    Landing.BRANCH_CUT: "BRANCH CUT",
    Landing.LEGACY: "legacy",
}


@app.command(name="frontend-base-status")
def frontend_base_status(
    *,
    deployment_config: Annotated[
        Path | None,
        cyclopts.Parameter(
            help="Deployment group directory holding upstream_watch.yaml "
            "(default: <repo>/deployments/mit-ol)."
        ),
    ] = None,
    repo: Annotated[
        list[str] | None,
        cyclopts.Parameter(
            help="Check these owner/name repositories instead of the watch list."
        ),
    ] = None,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(name=["--json"], help="Emit JSON instead of a table."),
    ] = False,
    fail_on_landing: Annotated[
        bool,
        cyclopts.Parameter(
            help="Exit non-zero when a repo an OL deployment builds from its "
            "default branch has landed or has had legacy-mfe cut. For CI."
        ),
    ] = False,
) -> None:
    """Report which upstream MFE repos have landed their frontend-base conversion.

    Reads the watch list from ``<deployment-config>/upstream_watch.yaml``, which
    also records the OL deployments whose legacy MFE build tracks each
    repository's default branch.
    """
    require("gh")

    if repo:
        entries = [{"repo": name, "exposed_deployments": []} for name in repo]
    else:
        group = deployment_config or (_paths.repo_root() / "deployments" / "mit-ol")
        entries = load_watch_list(group)

    rows: list[dict[str, Any]] = []
    breaking = False
    for entry in entries:
        state = fetch_state(str(entry["repo"]))
        exposed = list(entry.get("exposed_deployments") or [])
        stage = classify(state)
        if stage is not Landing.LEGACY and exposed:
            breaking = True
        rows.append(
            {
                "repo": state.repo,
                "default_branch": state.default_branch,
                "stage": str(stage),
                "version": state.version,
                "build": state.build_script,
                "release_annotation": state.release_annotation,
                "legacy_mfe_branch": state.legacy_mfe_branch,
                "legacy_build_ref": legacy_build_ref(state),
                "npm_dist_tags": state.npm_dist_tags,
                "exposed_deployments": exposed,
                "advice": advice(state, exposed_deployments=exposed),
            }
        )

    if json_output:
        print(json.dumps(rows, indent=2))
    else:
        width = max((len(r["repo"]) for r in rows), default=0)
        for row in rows:
            label = _STAGE_LABEL[Landing(row["stage"])]
            print(f"{row['repo']:<{width}}  {label:<10}  {row['advice']}")

    if fail_on_landing and breaking:
        sys.stderr.write(
            "lehrer: a repository an OL deployment builds from its default "
            "branch has landed its frontend-base conversion\n"
        )
        raise SystemExit(1)
