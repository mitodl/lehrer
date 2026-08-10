from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from lehrer.core import junit_report
from lehrer.core.plugin_tests import (
    combined_pytest_script,
    maintained_test_extra_specs,
)


def test_maintained_extras_selects_pinned_ol_plugins() -> None:
    lines = [
        "ol-openedx-logging==0.3.5  # Support for structlog",
        "ol_openedx_chat==0.5.9",
        "openedx-scorm-xblock==19.0.4",  # not ours (no ol- prefix)
        "edx-sysadmin==0.4.2",  # ours by ownership but not the ol- namespace
        "granian==2.7.9",  # bare library
        "",
        "# a comment line",
    ]
    specs = maintained_test_extra_specs(lines)
    assert specs == [
        "ol-openedx-logging[tests]==0.3.5",
        "ol-openedx-chat[tests]==0.5.9",
    ]


def test_maintained_extras_skips_unpinned_vcs_and_wildcard() -> None:
    lines = [
        "ol-openedx-foo>=1.0",  # range, not a reproducible pin
        "ol-openedx-bar",  # unpinned
        "git+https://github.com/mitodl/ol-openedx-baz.git#egg=ol-openedx-baz",
        "ol-openedx-qux==1.2.3; python_version >= '3.11'",  # marker -> skip
        "ol-openedx-star==1.2.*",  # wildcard could move the patch -> skip
    ]
    assert maintained_test_extra_specs(lines) == []


def test_maintained_extras_last_pin_wins_for_overrides() -> None:
    # A cell concatenates overrides AFTER the package list and install_deps
    # applies them last, so the extra must take the override version (0.9.9),
    # while keeping the distribution's first-seen position.
    lines = [
        "ol-openedx-logging==0.3.5",
        "ol-openedx-chat==0.5.9",
        "ol_openedx_logging==0.9.9",  # override, later — wins its version
    ]
    assert maintained_test_extra_specs(lines) == [
        "ol-openedx-logging[tests]==0.9.9",
        "ol-openedx-chat[tests]==0.5.9",
    ]


def test_combined_script_is_valid_python() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware", "common/djangoapps/student"],
        ["ol-openedx-logging"],
        "lms.envs.lehrer_test",
    )
    ast.parse(source)  # written verbatim into the container — must parse


def test_combined_script_embeds_edx_paths_and_plugins() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware"],
        ["ol-openedx-logging"],
        "cms.envs.lehrer_test",
        markers="not slow",
    )
    # edx-platform paths run as plain path args; plugin packages via --pyargs.
    assert "'lms/djangoapps/courseware'" in source
    assert "'ol-openedx-logging'" in source
    assert "'--pyargs'" in source
    assert "--ds={settings_module}" in source
    assert "cms.envs.lehrer_test" in source
    assert "not slow" in source
    # dist -> module resolution is read from installed metadata, never a
    # hand-maintained map, so a healthy plugin can't be mis-skipped.
    assert "packages_distributions()" in source


def test_combined_script_without_plugins_runs_edx_paths_only() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware"],
        [],
        "lms.envs.lehrer_test",
    )
    ast.parse(source)
    # With no plugin dists the --pyargs branch is guarded off at runtime; the
    # edx paths still run.
    assert "plugin_dists = []" in source
    assert "if plugin_modules:" in source


def test_combined_script_always_writes_a_junit_report() -> None:
    # Unconditional: the report is what `platform test-report` returns, and a
    # `--no-include-plugins` run must be just as inspectable as a plugin one.
    for dists in ([], ["ol-openedx-logging"]):
        source = combined_pytest_script(
            ["lms/djangoapps/courseware"], dists, "lms.envs.t"
        )
        assert "--junitxml={junit_path}" in source
        assert "summary.json" in source
        assert "summary.md" in source


def _run_driver(
    tmp_path: Path, plugin_dists: list[str], *, exit_code: int, junit: str
) -> subprocess.CompletedProcess[str]:
    """Execute a generated driver against a stub pytest that writes ``junit``.

    Exercises the report tail for real — the part that only runs after
    ``pytest.main`` returns and so can't be checked by reading the source.
    """
    reports_dir = tmp_path / "reports"
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    shutil.copy(Path(junit_report.__file__), tool_dir / "lehrer_junit_report.py")

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "pytest.py").write_text(
        "import sys\n"
        "def main(args):\n"
        "    target = next(a.split('=', 1)[1] for a in args"
        " if a.startswith('--junitxml='))\n"
        f"    open(target, 'w').write({junit!r})\n"
        f"    return {exit_code}\n"
    )

    source = combined_pytest_script(
        ["lms/djangoapps/courseware"],
        plugin_dists,
        "lms.envs.lehrer_test",
        reports_dir=str(reports_dir),
        tool_dir=str(tool_dir),
    )
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(stub_dir)},
        check=False,
        cwd=tmp_path,
    )


_STUB_JUNIT = (
    '<testsuites><testsuite name="pytest" tests="1">'
    '<testcase classname="lms.djangoapps.courseware.test_x" name="t" time="1.0"/>'
    "</testsuite></testsuites>"
)


def test_driver_writes_the_report_artifacts(tmp_path: Path) -> None:
    result = _run_driver(tmp_path, [], exit_code=0, junit=_STUB_JUNIT)
    assert result.returncode == 0, result.stderr
    reports = tmp_path / "reports"
    assert (reports / "report.xml").read_text() == _STUB_JUNIT
    assert json.loads((reports / "summary.json").read_text())["totals"]["tests"] == 1
    assert "| edx-platform | platform | 1 |" in (reports / "summary.md").read_text()
    # The summary is echoed so `platform test`'s stdout carries it too.
    assert "| edx-platform | platform | 1 |" in result.stdout


def test_driver_preserves_a_failing_exit_code(tmp_path: Path) -> None:
    # The report is written *and* the suite's verdict survives — `test` gates on
    # this exit code, so summarizing must never launder a failure into a pass.
    result = _run_driver(tmp_path, [], exit_code=1, junit=_STUB_JUNIT)
    assert result.returncode == 1
    assert (tmp_path / "reports" / "summary.json").exists()


def test_driver_survives_an_unparseable_report(tmp_path: Path) -> None:
    # A summarizer that can't parse the XML must not turn a passing suite red.
    result = _run_driver(tmp_path, [], exit_code=0, junit="not xml at all")
    assert result.returncode == 0
    assert "REPORT SUMMARY FAILED" in result.stdout
    assert not (tmp_path / "reports" / "summary.json").exists()


def test_driver_is_silent_about_plugins_when_none_were_requested(
    tmp_path: Path,
) -> None:
    result = _run_driver(tmp_path, [], exit_code=0, junit=_STUB_JUNIT)
    assert "PLUGIN" not in result.stdout


def test_driver_reports_a_requested_plugin_that_did_not_install(
    tmp_path: Path,
) -> None:
    result = _run_driver(
        tmp_path, ["ol-openedx-nonexistent"], exit_code=0, junit=_STUB_JUNIT
    )
    assert "PLUGIN MISSING: ol-openedx-nonexistent" in result.stdout
