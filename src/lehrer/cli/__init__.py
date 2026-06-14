"""The ``lehrer`` command-line interface.

``lehrer`` is the single entrypoint for working in this repository.  It is
intended to grow to cover every routine task — today it manages the local
k3d dev environment (``lehrer dev``) and drives the Dagger build pipelines
(``lehrer build``).

Run ``lehrer --help`` for the full command tree.
"""

from __future__ import annotations

import sys

import cyclopts

from lehrer.cli import build, local_dev
from lehrer.cli._paths import RepoNotFoundError
from lehrer.cli._proc import CommandError

app = cyclopts.App(
    name="lehrer",
    help="Lehrer — Open edX build & local-dev toolchain.",
    version_flags=["--version"],
)

app.command(local_dev.app)
app.command(build.app)


def main() -> None:
    """Console-script entrypoint.

    External tools (k3d, kubectl, tilt, dagger, ...) do the real work, so a
    failure is almost always *their* non-zero exit, not a bug in lehrer.
    Surface those as a clean one-line error instead of a Python traceback,
    propagating the underlying exit code.
    """
    try:
        app()
    except CommandError as exc:
        sys.stderr.write(f"lehrer: error: {exc}\n")
        raise SystemExit(exc.returncode) from None
    except RepoNotFoundError as exc:
        sys.stderr.write(f"lehrer: error: {exc}\n")
        raise SystemExit(1) from None


__all__ = ["app", "main"]
