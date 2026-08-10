from __future__ import annotations

import ast

import pytest

from lehrer.core.platform import (
    _FAILURE_OUTPUT_CHARS,
    _derive_test_settings,
    _edx_base_deps_script,
    _edx_testing_deps_script,
    _test_paths,
    _TestRunFailed,
)


@pytest.mark.parametrize("service", ["lms", "cms"])
def test_smoke_paths_are_a_subset_of_full(service: str) -> None:
    smoke = _test_paths(service, full=False)
    full = _test_paths(service, full=True)
    assert smoke, "smoke subset must not be empty"
    assert full, "full path set must not be empty"
    # Every smoke path must live under one of the full-run roots, so `--full`
    # is a strict superset of the default gate.
    for path in smoke:
        assert any(path == root or path.startswith(f"{root}/") for root in full), (
            f"{path!r} not covered by full roots {full}"
        )


def test_test_paths_rejects_unknown_service() -> None:
    with pytest.raises(ValueError, match="service must be one of"):
        _test_paths("workers", full=False)


@pytest.mark.parametrize("service", ["lms", "cms"])
def test_derive_test_settings_is_valid_python(service: str) -> None:
    source = _derive_test_settings(service)
    # Must parse — the module is written verbatim into the container.
    ast.parse(source)
    # Starts from the service's own test settings (the test-harness authority).
    assert f"from {service}.envs.test import *" in source
    # Overlays the deployment feature flags from the generated model.
    assert f"from {service}.envs.models.aqueduct import AqueductSettings" in source
    # Merge in place (item assignment), not a rebind, so a FeaturesProxy on
    # modern edx-platform is preserved rather than replaced by a plain dict.
    assert "FEATURES[_flag] = _value" in source
    assert "FEATURES = {" not in source


def test_derive_test_settings_rejects_unknown_service() -> None:
    with pytest.raises(ValueError, match="service must be one of"):
        _derive_test_settings("workers")


def test_failure_carries_the_run_output() -> None:
    # `expect=ANY` means Dagger no longer prints a failing exec's output, so a
    # red run is only diagnosable if the exception carries it.
    message = str(_TestRunFailed(1, "collected 3 items\nFAILED test_x", "Traceback"))
    assert "pytest exited 1" in message
    assert "FAILED test_x" in message
    assert "Traceback" in message


def test_failure_omits_empty_streams() -> None:
    message = str(_TestRunFailed(2, "some stdout", "   \n "))
    assert "--- stdout ---" in message
    assert "--- stderr ---" not in message


def test_failure_truncates_from_the_end() -> None:
    # Keep the tail: pytest's summary and the traceback are at the end, and an
    # error that buried them under the first 8k of collection noise is useless.
    stdout = "noise" * _FAILURE_OUTPUT_CHARS + "THE ACTUAL FAILURE"
    message = str(_TestRunFailed(1, stdout, ""))
    assert "THE ACTUAL FAILURE" in message
    assert "(truncated)" in message
    assert len(message) < _FAILURE_OUTPUT_CHARS + 500


def test_edx_base_deps_script_branches_on_uv_lock() -> None:
    script = _edx_base_deps_script()
    assert "cd /openedx/edx-platform" in script
    assert "if [ -f uv.lock ]; then" in script
    # uv.lock branch: a direct sync, no intermediate requirements file.
    assert "uv sync --locked --active --no-install-project" in script
    # legacy branch: same base+assets requirements the pre-migration path used.
    assert (
        "uv pip install -r requirements/edx/base.txt"
        " -r requirements/edx/assets.txt" in script
    )


def test_edx_base_deps_script_sync_is_inexact() -> None:
    # Load-bearing: callers layer an editable django-aqueduct install and the
    # deployment's own pinned package list on top of this sync, before or
    # after. A plain (exact) sync prunes anything not in edx-platform's own
    # lock resolution, which would silently strip those back out.
    script = _edx_base_deps_script()
    assert "--inexact" in script


def test_edx_base_deps_script_excludes_dev_group_by_default() -> None:
    script = _edx_base_deps_script()
    assert "--group assets" in script
    assert "--group dev" not in script
    assert "development.txt" not in script


def test_edx_base_deps_script_include_dev() -> None:
    script = _edx_base_deps_script(include_dev=True)
    assert "--group assets" in script
    assert "--group dev" in script
    # legacy branch also needs the pre-migration development.txt equivalent.
    assert "-r requirements/edx/development.txt" in script


def test_edx_testing_deps_script() -> None:
    script = _edx_testing_deps_script()
    assert "cd /openedx/edx-platform" in script
    assert "if [ -f uv.lock ]; then" in script
    assert "--inexact" in script
    assert "--group testing" in script
    # legacy branch: same testing.txt the pre-migration path installed.
    assert "uv pip install -r requirements/edx/testing.txt" in script
