"""Subprocess helpers shared across the lehrer CLI commands.

Everything the CLI does ultimately shells out to an external tool (``k3d``,
``kubectl``, ``helm``, ``tilt``, ``dagger``, ``docker``).  These helpers give
that a single, consistent surface: commands are echoed before they run so the
user can see exactly what is happening, output is streamed live, and a
non-zero exit raises :class:`CommandError`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence


class CommandError(RuntimeError):
    """Raised when an external command exits non-zero."""

    def __init__(self, argv: Sequence[str], returncode: int) -> None:
        self.argv = list(argv)
        self.returncode = returncode
        super().__init__(f"command failed ({returncode}): {' '.join(self.argv)}")


def _echo(argv: Sequence[str], *, prefix: str = "==>") -> None:
    sys.stderr.write(f"{prefix} {' '.join(argv)}\n")
    sys.stderr.flush()


def have(cmd: str) -> bool:
    """Return ``True`` if ``cmd`` is on ``PATH``."""
    return shutil.which(cmd) is not None


def require(cmd: str) -> None:
    """Abort with a helpful message if ``cmd`` is not installed."""
    if not have(cmd):
        raise CommandError([cmd], 127)


def run(
    *argv: str,
    check: bool = True,
    echo: bool = True,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    input: str | None = None,
) -> int:
    """Run ``argv`` with output streamed to the terminal.

    Returns the process exit code.  Raises :class:`CommandError` on a non-zero
    exit unless ``check`` is ``False``.
    """
    if echo:
        _echo(argv)
    completed = subprocess.run(  # noqa: S603 - argv is an explicit token list
        argv,
        env=dict(env) if env is not None else None,
        cwd=cwd,
        input=input,
        text=True,
    )
    if check and completed.returncode != 0:
        raise CommandError(argv, completed.returncode)
    return completed.returncode


def capture(*argv: str, check: bool = True) -> str:
    """Run ``argv`` and return its stripped stdout (no echo, no streaming)."""
    completed = subprocess.run(  # noqa: S603 - argv is an explicit token list
        argv,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise CommandError(argv, completed.returncode)
    return completed.stdout.strip()


def pipe(producer: Sequence[str], consumer: Sequence[str]) -> None:
    """Run ``producer | consumer`` and raise if either side fails.

    Used for the ``kubectl create ... --dry-run=client -o yaml | kubectl apply``
    idempotent-apply idiom.
    """
    _echo([*producer, "|", *consumer])
    first = subprocess.run(  # noqa: S603
        list(producer), capture_output=True, text=True
    )
    if first.returncode != 0:
        sys.stderr.write(first.stderr)
        raise CommandError(producer, first.returncode)
    second = subprocess.run(  # noqa: S603
        list(consumer), input=first.stdout, text=True
    )
    if second.returncode != 0:
        raise CommandError(consumer, second.returncode)
