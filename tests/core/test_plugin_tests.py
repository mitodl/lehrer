from __future__ import annotations

import ast

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


def test_maintained_extras_skips_unpinned_and_vcs() -> None:
    lines = [
        "ol-openedx-foo>=1.0",  # range, not a reproducible pin
        "ol-openedx-bar",  # unpinned
        "git+https://github.com/mitodl/ol-openedx-baz.git#egg=ol-openedx-baz",
        "ol-openedx-qux==1.2.3; python_version >= '3.11'",  # marker -> skip
    ]
    assert maintained_test_extra_specs(lines) == []


def test_maintained_extras_dedupes_first_wins() -> None:
    lines = ["ol-openedx-logging==0.3.5", "ol_openedx_logging==0.9.9"]
    # Normalization collapses the two spellings to one dist; first pin wins.
    assert maintained_test_extra_specs(lines) == ["ol-openedx-logging[tests]==0.3.5"]


def test_combined_script_is_valid_python() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware", "common/djangoapps/student"],
        ["ol-openedx-logging"],
        "lms.envs.lehrer_test",
        "/openedx/reports/report.xml",
    )
    ast.parse(source)  # written verbatim into the container — must parse


def test_combined_script_embeds_edx_paths_plugins_and_report() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware"],
        ["ol-openedx-logging"],
        "cms.envs.lehrer_test",
        "/openedx/reports/report.xml",
        markers="not slow",
    )
    # edx-platform paths run as plain path args; plugin packages via --pyargs.
    assert "'lms/djangoapps/courseware'" in source
    assert "'ol-openedx-logging'" in source
    assert "'--pyargs'" in source
    assert "--ds={settings_module}" in source
    assert "cms.envs.lehrer_test" in source
    assert "/openedx/reports/report.xml" in source
    assert "not slow" in source
    # dist -> module resolution is read from installed metadata, never a
    # hand-maintained map, so a healthy plugin can't be mis-skipped.
    assert "packages_distributions()" in source


def test_combined_script_without_plugins_runs_edx_paths_only() -> None:
    source = combined_pytest_script(
        ["lms/djangoapps/courseware"],
        [],
        "lms.envs.lehrer_test",
        "/openedx/reports/report.xml",
    )
    ast.parse(source)
    # With no plugin dists the --pyargs branch is guarded off at runtime; the
    # edx paths still run.
    assert "plugin_dists = []" in source
    assert "if plugin_modules:" in source
