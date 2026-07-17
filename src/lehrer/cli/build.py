"""``lehrer build`` — build and verify the Open edX images.

A single, consistent facade over the lehrer Dagger module
(``src/lehrer/main.py``) so the whole build-and-verify surface is one command
tree instead of a wall of ``dagger call`` incantations. ``lehrer build --help``
groups the commands the way you reason about them:

* **Build** — produce an image or artifact (``platform``, ``codejail``,
  ``notes``, ``mfe-legacy``, ``mfe-site``).
* **Verify** — the compatibility pyramid for a build cell, cheapest first:
  ``check`` (install + import) → ``test`` (edx-platform's own suite under the
  deployment's settings) → ``plugin-regression`` (the plugins' own suites);
  plus ``codejail-test`` / ``notes-test`` for those services.
* **Utilities** — ``cells``, ``functions``, and the raw ``call`` escape hatch.

Each command is a thin wrapper that forwards its trailing arguments straight to
Dagger, so the full ``dagger call`` flag surface (``--help``, ``export``,
``publish``, ``--source``, ...) is always available. The cell-scoped commands
(``platform``/``check``/``test``/``plugin-regression``) also accept a single
``<group>/<release>/<deployment>`` argument that expands to the right
``--build-manifest``/``--release-name``/``--deployment-name`` so you don't
repeat them; use ``lehrer build call ...`` for any function without a wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import cyclopts

from lehrer.cli import _paths
from lehrer.cli._proc import run
from lehrer.core.build_manifest import load_manifest

app = cyclopts.App(
    name="build",
    help="Build & verify Open edX images (edx-platform, MFEs, codejail, notes).",
)

# Ordered so `--help` reads as the mental model: make images, then verify them.
_BUILD = cyclopts.Group.create_ordered("Build")
_VERIFY = cyclopts.Group.create_ordered("Verify")
_UTIL = cyclopts.Group.create_ordered("Utilities")

# Trailing tokens are passed verbatim to `dagger`, including ones that begin
# with a hyphen (e.g. `--deployment-name`, `export`, `--path`).
DaggerArgs = Annotated[str, cyclopts.Parameter(allow_leading_hyphen=True)]

# The one argument every cell-scoped platform command shares: a single
# coordinate that expands to the manifest + release + deployment flags.
CellArg = Annotated[
    str | None,
    cyclopts.Parameter(
        help=(
            "<group>/<release>/<deployment> (e.g. mit-ol/master/mitxonline). "
            "Resolves deployments/<group>/build_manifest.yaml and forwards "
            "--build-manifest/--release-name/--deployment-name."
        )
    ),
]


def _dagger(*argv: str) -> None:
    run("dagger", *argv, cwd=str(_paths.repo_root()))


def _manifest_path(group: str) -> Path:
    return _paths.repo_root() / "deployments" / group / "build_manifest.yaml"


def _default_manifest_path() -> Path:
    """Return a manifest path when the caller didn't pass ``--manifest``.

    Prefers ``deployments/mit-ol`` (this repo's reference deployment) but
    falls back to auto-discovering any ``build_manifest.yaml`` under
    ``deployments/`` so generic/external operators without a ``mit-ol``
    directory still get a usable default.
    """
    mit_ol = _manifest_path("mit-ol")
    if mit_ol.exists():
        return mit_ol
    manifests = sorted(_paths.repo_root().glob("deployments/*/build_manifest.yaml"))
    if not manifests:
        msg = (
            "no build_manifest.yaml found under deployments/ and no --manifest "
            "path was given"
        )
        raise FileNotFoundError(msg)
    return manifests[0]


def _parse_cell(cell: str) -> tuple[str, str, str]:
    parts = cell.split("/")
    if len(parts) != 3:  # noqa: PLR2004
        msg = f"--cell must be <group>/<release>/<deployment>, got {cell!r}"
        raise ValueError(msg)
    group, release, deployment = parts
    return group, release, deployment


def _platform_cell_command(
    subcommand: str, cell: str | None, dagger_args: tuple[str, ...]
) -> None:
    """Forward a cell-scoped ``platform`` subcommand to Dagger.

    With no ``cell`` the trailing args are passed through verbatim (the caller
    supplies the flags themselves); with a ``<group>/<release>/<deployment>``
    cell the manifest/release/deployment flags are filled in for them. Shared
    by every cell-scoped platform command so they can never drift apart.
    """
    if cell is None:
        _dagger("call", "platform", subcommand, *dagger_args)
        return
    group, release, deployment = _parse_cell(cell)
    _dagger(
        "call",
        "platform",
        subcommand,
        "--build-manifest",
        str(_manifest_path(group)),
        "--release-name",
        release,
        "--deployment-name",
        deployment,
        *dagger_args,
    )


@app.command(group=_BUILD)
def platform(cell: CellArg = None, *dagger_args: DaggerArgs) -> None:
    """Build the edx-platform LMS/CMS image (``platform build-platform``)."""
    _platform_cell_command("build-platform", cell, dagger_args)


@app.command(group=_BUILD)
def codejail(*dagger_args: DaggerArgs) -> None:
    """Build the codejail service image (``codejail build``)."""
    _dagger("call", "codejail", "build", *dagger_args)


@app.command(group=_BUILD)
def notes(*dagger_args: DaggerArgs) -> None:
    """Build the edx-notes-api image (``notes build``)."""
    _dagger("call", "notes", "build", *dagger_args)


@app.command(name="mfe-legacy", group=_BUILD)
def mfe_legacy(*dagger_args: DaggerArgs) -> None:
    """Build a legacy MFE ``dist/`` (``mfe build-legacy``)."""
    _dagger("call", "mfe", "build-legacy", *dagger_args)


@app.command(name="mfe-site", group=_BUILD)
def mfe_site(*dagger_args: DaggerArgs) -> None:
    """Build an OEP-65 Site Project (``mfe build-site``)."""
    _dagger("call", "mfe", "build-site", *dagger_args)


@app.command(group=_VERIFY)
def check(cell: CellArg = None, *dagger_args: DaggerArgs) -> None:
    """Verify a cell's requirements install + import (``platform check-deployment``)."""
    _platform_cell_command("check-deployment", cell, dagger_args)


@app.command(group=_VERIFY)
def test(cell: CellArg = None, *dagger_args: DaggerArgs) -> None:
    """Run the edx-platform test suite inside a built image (``platform test``).

    Defaults to a curated smoke subset; pass ``--full`` for the whole suite,
    ``--test-paths`` for specific apps/paths, or ``--service cms`` for Studio.
    Remember ``--custom-settings ./deployments/<group>/settings``.
    """
    _platform_cell_command("test", cell, dagger_args)


@app.command(name="plugin-regression", group=_VERIFY)
def plugin_regression(cell: CellArg = None, *dagger_args: DaggerArgs) -> None:
    """Run installed plugins' own test suites in the image (``platform plugin-regression``).

    Discovers and runs whatever plugin tests are installed (maintained ``ol-*``
    plugins gain a ``[tests]`` extra by default; disable with
    ``--no-install-test-extras``). Passes cleanly when no suite is discovered.
    Remember ``--custom-settings ./deployments/<group>/settings``.
    """
    _platform_cell_command("plugin-regression", cell, dagger_args)


@app.command(name="codejail-test", group=_VERIFY)
def codejail_test(*dagger_args: DaggerArgs) -> None:
    """Run the codejailservice test suite in its image (``codejail test``)."""
    _dagger("call", "codejail", "test", *dagger_args)


@app.command(name="notes-test", group=_VERIFY)
def notes_test(*dagger_args: DaggerArgs) -> None:
    """Run the edx-notes-api test suite in its image (``notes test``)."""
    _dagger("call", "notes", "test", *dagger_args)


@app.command(group=_UTIL)
def cells(
    manifest: Annotated[
        str | None, cyclopts.Parameter(help="Path to a build_manifest.yaml.")
    ] = None,
) -> None:
    """Print the (release, deployment) cells in a build_manifest.yaml.

    The consumption API external consumers (e.g. ol-infrastructure's Concourse
    pipeline generator) cross-check their topology coordinates against — call
    ``lehrer.core.build_manifest.load_manifest`` directly instead of shelling
    out to this command when consuming from Python.
    """
    path = Path(manifest) if manifest else _default_manifest_path()
    build_manifest = load_manifest(path)
    for build_cell in build_manifest.cells:
        print(f"{build_cell.release}/{build_cell.deployment}")  # noqa: T201


@app.command(group=_UTIL)
def functions() -> None:
    """List all available Dagger functions (``dagger functions``)."""
    _dagger("functions")


@app.command(group=_UTIL)
def call(*dagger_args: DaggerArgs) -> None:
    """Raw ``dagger call`` passthrough for any function or chain."""
    _dagger("call", *dagger_args)
