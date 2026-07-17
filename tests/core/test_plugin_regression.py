from __future__ import annotations

import ast

from lehrer.core.plugin_regression import (
    maintained_test_extra_specs,
    plugin_regression_script,
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


def test_regression_script_is_valid_python() -> None:
    source = plugin_regression_script(
        ["ol-openedx-logging", "openedx-scorm-xblock"],
        "lms.envs.lehrer_test",
        "/openedx/reports/plugins.xml",
    )
    ast.parse(source)  # written verbatim into the container — must parse


def test_regression_script_embeds_targets_settings_and_report() -> None:
    source = plugin_regression_script(
        ["ol-openedx-logging"], "cms.envs.lehrer_test", "/openedx/reports/plugins.xml"
    )
    assert "'ol-openedx-logging'" in source
    assert "--ds={settings_module}" in source
    assert "cms.envs.lehrer_test" in source
    assert "/openedx/reports/plugins.xml" in source
    # Discovery is via --pyargs over installed packages, with an aggregated
    # JUnit report.
    assert "'--pyargs'" in source
    assert "--junitxml={junit_path}" in source


def test_regression_script_treats_no_tests_collected_as_success() -> None:
    source = plugin_regression_script(
        ["ol-openedx-logging"], "lms.envs.lehrer_test", "/tmp/r.xml"
    )
    # Exit 5 (NO_TESTS_COLLECTED) must be swallowed — the expected state until
    # plugins ship their [tests] extra — so the gate stays green meanwhile.
    assert "code == 5" in source
    assert "sys.exit(code)" in source


def test_regression_script_resolves_modules_at_runtime() -> None:
    source = plugin_regression_script(["ol-openedx-logging"], "lms.envs.test", "/r.xml")
    # dist -> module resolution is read from installed metadata, never a
    # hand-maintained map, so a healthy plugin can't be mis-skipped.
    assert "packages_distributions()" in source
