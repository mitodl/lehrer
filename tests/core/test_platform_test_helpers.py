from __future__ import annotations

import ast

import pytest

from lehrer.core.platform import (
    _FAILURE_OUTPUT_CHARS,
    _derive_test_settings,
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
