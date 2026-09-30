from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lehrer.bootstrap import __main__ as runner
from lehrer.bootstrap.spec import Migration


def test_manage_runs_each_service_under_its_own_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # manage.py prefers DJANGO_SETTINGS_MODULE over its service argument, so
    # without --settings a CMS migrate from an LMS-configured Job would load
    # the LMS settings.
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "lms.envs.aqueduct")
    command = runner._manage("cms", "migrate")
    assert command[1:4] == ["manage.py", "cms", "migrate"]
    assert "--settings=aqueduct" in command


def test_run_migrate_reports_whether_it_applied_anything() -> None:
    applied = (
        "import sys\n"
        # The platform logs to the same stream mid-migration, so the OK can
        # land on a later line than its Applying.
        "sys.stdout.write('  Applying a.0001_initial...')\n"
        "print('Key BLOCK_STRUCTURES_SETTINGS not found')\n"
        "print(' OK')\n"
    )
    assert runner._run_migrate([sys.executable, "-c", applied])
    noop = "print('Running migrations:'); print('  No migrations to apply.')"
    assert not runner._run_migrate([sys.executable, "-c", noop])


def test_run_migrate_raises_on_failure() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        runner._run_migrate([sys.executable, "-c", "raise SystemExit(1)"])


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, str]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_migrate_targets_one_app_on_one_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "lms.envs.aqueduct")
    commands = []

    def run_migrate(command: list[str]) -> bool:
        commands.append(command)
        return False

    monkeypatch.setattr(runner, "_run_migrate", run_migrate)
    runner._migrate(
        Migration(
            service="lms",
            app_label="coursewarehistoryextended",
            database="student_module_history",
        )
    )
    assert "--database=student_module_history" in commands[0]
    assert "coursewarehistoryextended" in commands[0]
    assert _lines(capsys) == [
        {
            "step": "migrate",
            "target": "lms coursewarehistoryextended@student_module_history",
            "result": "unchanged",
        }
    ]


def test_demo_course_branch_is_the_first_that_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed = []

    def ls_remote(command: list[str], **_: Any) -> SimpleNamespace:
        probed.append(command[-1])
        return SimpleNamespace(returncode=0 if command[-1].endswith(".master") else 2)

    monkeypatch.setattr(runner.subprocess, "run", ls_remote)
    assert runner._demo_course_branch("repo", "sumac") == "open-release/sumac.master"
    assert probed == ["release/sumac", "open-release/sumac.master"]


def test_demo_course_branch_names_what_it_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=2)
    )
    with pytest.raises(ValueError, match="release/zebra"):
        runner._demo_course_branch("repo", "zebra")


@pytest.mark.parametrize(
    "layout",
    [
        # Redwood onward.
        "demo-course/course",
        # Quince and earlier.
        ".",
    ],
)
def test_demo_course_dir_finds_course_xml(tmp_path: Path, layout: str) -> None:
    course = tmp_path / layout
    course.mkdir(parents=True, exist_ok=True)
    (course / "course.xml").write_text("<course/>")
    assert runner._demo_course_dir(tmp_path) == course


def test_demo_course_dir_refuses_a_checkout_without_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="course.xml"):
        runner._demo_course_dir(tmp_path)


@pytest.mark.parametrize(
    ("steps", "set_up"),
    [
        ("migrate", False),
        ("demo_course", False),
        ("migrate,users", True),
        ("waffle_flags", True),
    ],
)
def test_only_orm_steps_set_up_django(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, steps: str, set_up: bool
) -> None:
    # migrate and demo_course run in manage.py children with their own app
    # registry. Setting one up here as well doubles peak memory for the run.
    calls = []
    monkeypatch.setitem(
        sys.modules, "django", SimpleNamespace(setup=lambda: calls.append(1))
    )
    monkeypatch.setitem(sys.modules, "django.conf", SimpleNamespace(settings=None))
    for step in runner.STEPS:
        monkeypatch.setitem(runner.APPLY, step, lambda *_: None)
    spec = tmp_path / "spec.yaml"
    spec.write_text("{}\n")
    runner.main([str(spec), "--steps", steps])
    assert bool(calls) is set_up
