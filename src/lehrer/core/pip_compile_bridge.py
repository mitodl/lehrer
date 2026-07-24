"""Shared pip-compile -> uv.lock bridge for Python service builds.

Several Open edX services are (or may eventually be) migrating their Python
dependency management from pip-compile-generated ``requirements/*.txt``
files to ``pyproject.toml`` + ``uv.lock`` as the source of truth --
openedx-platform's own migration is tracked in
openedx/public-engineering#552. Every Python build in lehrer sources its
dependencies through :func:`python_deps_install_script`, which detects the
track from the checkout itself (``uv.lock`` present or not) rather than
hardcoding which release or service has migrated. That keeps a build
working across a service's migration landing without a lehrer change --
and costs nothing for a checkout that never migrates: the branch just
always takes the legacy arm.
"""

import shlex


def python_deps_install_script(
    *,
    workdir: str,
    legacy_requirements: list[str],
    sync_groups: list[str] | None = None,
    legacy_installer: list[str] | None = None,
    ensure_uv: bool = False,
) -> str:
    """Shell script installing a checkout's Python deps.

    Runs ``uv sync --locked`` against a committed ``uv.lock`` when present,
    otherwise falls back to installing the legacy pip-compile
    ``requirements/*.txt`` files.

    ``--inexact`` is always passed on the sync path: callers commonly layer
    other installs into the same environment around this call -- a
    deployment's own pinned package list, another service's base
    requirements, an editable framework checkout installed just before it.
    A plain (exact) sync prunes anything not in the checkout's own lock
    resolution, which would silently strip those back out.

    Args:
        workdir: Directory containing the checkout (``pyproject.toml``/
            ``uv.lock`` or the legacy ``requirements/`` tree).
        legacy_requirements: Requirement file paths (relative to
            ``workdir``) to install when no ``uv.lock`` is present.
        sync_groups: Dependency groups to select when ``uv.lock`` IS
            present, via ``--no-default-groups --group <name>`` for each.
            Omit for just the project's own default dependencies.
        legacy_installer: Command prefix for the legacy branch. Default
            ``["pip", "install", "--no-cache-dir"]``. Pass
            ``["uv", "pip", "install"]`` for a container where uv is
            already the installer of record.
        ensure_uv: Install uv via pip before the sync branch runs. Default
            ``False`` for containers (e.g. the edx-platform build) that
            already have uv on PATH; set ``True`` for containers (e.g.
            codejail, notes) that only have plain pip.

    Must run with ``VIRTUAL_ENV`` set to the target environment -- the sync
    branch uses ``--active``.
    """
    installer = list(legacy_installer or ["pip", "install", "--no-cache-dir"])
    legacy_args: list[str] = []
    for req in legacy_requirements:
        legacy_args += ["-r", req]
    legacy_cmd = " ".join(shlex.quote(part) for part in [*installer, *legacy_args])

    sync_parts = [
        "uv",
        "sync",
        "--locked",
        "--active",
        "--no-install-project",
        "--inexact",
    ]
    if sync_groups:
        sync_parts.append("--no-default-groups")
        for group in sync_groups:
            sync_parts += ["--group", group]
    sync_cmd = " ".join(shlex.quote(part) for part in sync_parts)
    if ensure_uv:
        sync_cmd = f"pip install --quiet uv && {sync_cmd}"

    return (
        "set -eu\n"
        f"cd {shlex.quote(workdir)}\n"
        "if [ -f uv.lock ]; then\n"
        f"  {sync_cmd}\n"
        "else\n"
        f"  {legacy_cmd}\n"
        "fi\n"
    )
