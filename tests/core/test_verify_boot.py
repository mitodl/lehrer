from __future__ import annotations

from typing import Any

import pytest

from lehrer.core.platform import OpenedxPlatform


class _RecordingContainer:
    def __init__(self) -> None:
        self.execs: list[list[str]] = []

    def with_exec(self, args: list[str]) -> _RecordingContainer:
        self.execs.append(args)
        return self


def _boot_commands(*, uses_aqueduct: bool) -> list[str]:
    recorder = _RecordingContainer()
    container: Any = recorder
    result = OpenedxPlatform()._verify_boot(  # noqa: SLF001
        container, uses_aqueduct=uses_aqueduct
    )
    assert result is recorder
    return [args[2] for args in recorder.execs]


def test_verify_boot_aqueduct_cell_checks_aqueduct_without_stub() -> None:
    lms, cms = _boot_commands(uses_aqueduct=True)
    assert lms.endswith(
        "SERVICE_VARIANT=lms python manage.py lms check --settings=aqueduct"
    )
    assert cms.endswith(
        "SERVICE_VARIANT=cms python manage.py cms check --settings=aqueduct"
    )
    assert "_CFG" not in lms + cms


@pytest.mark.parametrize("svc", ["lms", "cms"])
def test_verify_boot_production_cell_uses_stub_config_and_cleans_up(svc: str) -> None:
    command = dict(
        zip(("lms", "cms"), _boot_commands(uses_aqueduct=False), strict=True)
    )[svc]
    assert "--settings=production" in command
    assert "LMS_ROOT_URL" in command
    assert f"{svc.upper()}_CFG=/tmp/boot-check.yml" in command
    assert command.endswith("rm -f /tmp/boot-check.yml")
