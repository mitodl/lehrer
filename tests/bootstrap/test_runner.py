from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lehrer.bootstrap import __main__ as runner
from lehrer.bootstrap.spec import BootstrapSpec, Migration


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
    ("steps", "expected"),
    [
        ("migrate", ["migrate"]),
        ("demo_course", ["demo_course"]),
        ("waffle_flags", ["setup", "waffle_flags"]),
        # The default, and what a deployed pre-deploy Job runs: the registry
        # comes up only after migrate's children have finished.
        (
            "migrate,users,waffle_flags,demo_course",
            ["migrate", "setup", "users", "waffle_flags", "demo_course"],
        ),
    ],
)
def test_django_is_set_up_just_before_the_first_orm_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, steps: str, expected: list[str]
) -> None:
    # migrate and demo_course run in manage.py children with their own app
    # registry. One set up in the runner while they run doubles peak memory.
    events: list[str] = []
    monkeypatch.setitem(
        sys.modules, "django", SimpleNamespace(setup=lambda: events.append("setup"))
    )
    monkeypatch.setitem(sys.modules, "django.conf", SimpleNamespace(settings=None))
    for step in runner.STEPS:
        monkeypatch.setitem(
            runner.APPLY, step, lambda *_, step=step: events.append(step)
        )
    spec = tmp_path / "spec.yaml"
    spec.write_text("{}\n")
    runner.main([str(spec), "--steps", steps])
    assert events == expected


class _DemoCourseCommands:
    """Stands in for git and manage.py, laying out a checkout on clone."""

    def __init__(self, layout: str, *, import_fails: bool = False) -> None:
        self.layout = layout
        self.import_fails = import_fails
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **_: Any) -> SimpleNamespace:
        self.commands.append(command)
        if command[:2] == ["git", "clone"]:
            course = Path(command[-1]) / self.layout
            course.mkdir(parents=True, exist_ok=True)
            (course / "course.xml").write_text("<course/>")
        elif "import" in command and self.import_fails:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)


@pytest.fixture
def demo_course(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "cms.envs.aqueduct")
    monkeypatch.setitem(
        sys.modules, "openedx.core.release", SimpleNamespace(RELEASE_LINE="teak")
    )

    def install(layout: str, **kwargs: bool) -> _DemoCourseCommands:
        commands = _DemoCourseCommands(layout, **kwargs)
        monkeypatch.setattr(runner.subprocess, "run", commands.run)
        return commands

    return install


@pytest.mark.parametrize(
    ("layout", "data_dir", "course_dir"),
    [
        ("demo-course/course", "openedx-demo-course/demo-course", "course"),
        (".", "", "openedx-demo-course"),
    ],
)
def test_demo_course_imports_the_directory_holding_course_xml(
    demo_course: Any,
    capsys: pytest.CaptureFixture[str],
    layout: str,
    data_dir: str,
    course_dir: str,
) -> None:
    commands = demo_course(layout)
    spec = BootstrapSpec.model_validate({"demo_course": {"branch": "release/teak"}})
    runner.apply_demo_course(spec, None)

    clone, manage = commands.commands
    assert clone[:2] == ["git", "clone"]
    assert clone[clone.index("--branch") + 1] == "release/teak"
    assert manage[1:4] == ["manage.py", "cms", "import"]
    tmp = Path(clone[-1]).parent
    assert Path(manage[4]) == tmp / data_dir
    assert manage[5] == course_dir
    assert "--settings=aqueduct" in manage
    assert _lines(capsys) == [
        {
            "step": "demo_course",
            "target": "https://github.com/openedx/openedx-demo-course@release/teak",
            "result": "imported",
        }
    ]


def test_demo_course_reports_nothing_when_the_import_fails(
    demo_course: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    demo_course("demo-course/course", import_fails=True)
    spec = BootstrapSpec.model_validate({"demo_course": {"branch": "release/teak"}})
    with pytest.raises(subprocess.CalledProcessError):
        runner.apply_demo_course(spec, None)
    assert capsys.readouterr().out == ""
