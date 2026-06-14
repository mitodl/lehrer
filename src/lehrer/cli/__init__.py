"""The ``lehrer`` command-line interface.

``lehrer`` is the single entrypoint for working in this repository.  It is
intended to grow to cover every routine task — today it manages the local
k3d dev environment (``lehrer dev``) and drives the Dagger build pipelines
(``lehrer build``).

Run ``lehrer --help`` for the full command tree.
"""

from __future__ import annotations

import cyclopts

from lehrer.cli import build, local_dev

app = cyclopts.App(
    name="lehrer",
    help="Lehrer — Open edX build & local-dev toolchain.",
    version_flags=["--version"],
)

app.command(local_dev.app)
app.command(build.app)


def main() -> None:
    """Console-script entrypoint."""
    app()


__all__ = ["app", "main"]
