"""``lehrer build`` — drive the Dagger build pipelines.

These commands are thin, well-labelled wrappers around ``dagger call`` against
the lehrer Dagger module (``src/lehrer/main.py``).  They run from the repo root
so relative ``--source`` / config paths resolve the same way they would for a
bare ``dagger call``.

Every wrapper forwards its trailing arguments straight through to Dagger, so
the full ``dagger call`` flag surface (``--help``, ``export``, ``publish``,
``--source``, ...) is available.  Use ``lehrer build call ...`` as a raw
escape hatch for any function not given a dedicated wrapper.
"""

from __future__ import annotations

from typing import Annotated

import cyclopts

from lehrer.cli import _paths
from lehrer.cli._proc import run

app = cyclopts.App(
    name="build",
    help="Run the Dagger build pipelines (edx-platform, MFEs, codejail, notes).",
)

# Trailing tokens are passed verbatim to `dagger`, including ones that begin
# with a hyphen (e.g. `--deployment-name`, `export`, `--path`).
DaggerArgs = Annotated[str, cyclopts.Parameter(allow_leading_hyphen=True)]


def _dagger(*argv: str) -> None:
    run("dagger", *argv, cwd=str(_paths.repo_root()))


@app.command
def functions() -> None:
    """List all available Dagger functions (``dagger functions``)."""
    _dagger("functions")


@app.command
def platform(*dagger_args: DaggerArgs) -> None:
    """Build the edx-platform LMS/CMS image (``platform build-platform``)."""
    _dagger("call", "platform", "build-platform", *dagger_args)


@app.command(name="mfe-legacy")
def mfe_legacy(*dagger_args: DaggerArgs) -> None:
    """Build a legacy MFE ``dist/`` (``mfe build-legacy``)."""
    _dagger("call", "mfe", "build-legacy", *dagger_args)


@app.command(name="mfe-site")
def mfe_site(*dagger_args: DaggerArgs) -> None:
    """Build an OEP-65 Site Project (``mfe build-site``)."""
    _dagger("call", "mfe", "build-site", *dagger_args)


@app.command
def codejail(*dagger_args: DaggerArgs) -> None:
    """Build the codejail service image (``codejail build``)."""
    _dagger("call", "codejail", "build", *dagger_args)


@app.command
def notes(*dagger_args: DaggerArgs) -> None:
    """Build the edx-notes-api image (``notes build``)."""
    _dagger("call", "notes", "build", *dagger_args)


@app.command
def call(*dagger_args: DaggerArgs) -> None:
    """Raw ``dagger call`` passthrough for any function or chain."""
    _dagger("call", *dagger_args)
