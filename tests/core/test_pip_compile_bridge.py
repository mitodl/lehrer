from __future__ import annotations

from lehrer.core.pip_compile_bridge import python_deps_install_script


def test_branches_on_uv_lock_presence() -> None:
    script = python_deps_install_script(
        workdir="/app/service",
        legacy_requirements=["requirements/base.txt"],
    )
    assert "cd /app/service" in script
    assert "if [ -f uv.lock ]; then" in script
    assert "uv sync --locked --active --no-install-project --inexact" in script
    assert "pip install --no-cache-dir -r requirements/base.txt" in script


def test_multiple_legacy_requirements_each_get_their_own_flag() -> None:
    script = python_deps_install_script(
        workdir=".",
        legacy_requirements=["requirements/base.txt", "requirements/assets.txt"],
    )
    assert (
        "pip install --no-cache-dir -r requirements/base.txt"
        " -r requirements/assets.txt" in script
    )


def test_sync_is_always_inexact() -> None:
    # Load-bearing: callers commonly layer other installs (a deployment's own
    # package list, an editable framework checkout, another service's base
    # requirements) into the same environment around this call. A plain
    # (exact) sync prunes anything not in the checkout's own lock resolution,
    # which would silently strip those back out.
    script = python_deps_install_script(workdir=".", legacy_requirements=[])
    assert "--inexact" in script


def test_no_sync_groups_by_default() -> None:
    script = python_deps_install_script(workdir=".", legacy_requirements=[])
    assert "--group" not in script
    assert "--no-default-groups" not in script


def test_sync_groups_use_no_default_groups() -> None:
    script = python_deps_install_script(
        workdir=".", legacy_requirements=[], sync_groups=["assets", "dev"]
    )
    assert "--no-default-groups --group assets --group dev" in script


def test_legacy_installer_override() -> None:
    script = python_deps_install_script(
        workdir=".",
        legacy_requirements=["requirements/base.txt"],
        legacy_installer=["uv", "pip", "install"],
    )
    assert "uv pip install -r requirements/base.txt" in script
    assert "pip install --no-cache-dir" not in script


def test_ensure_uv_installs_uv_before_sync() -> None:
    without = python_deps_install_script(workdir=".", legacy_requirements=[])
    with_ensure = python_deps_install_script(
        workdir=".", legacy_requirements=[], ensure_uv=True
    )
    assert "pip install --quiet uv" not in without
    assert "pip install --quiet uv && uv sync" in with_ensure
