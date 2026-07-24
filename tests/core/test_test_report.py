"""Unit tests for the JUnit report summarizer."""

import json

from lehrer.core.test_report import (
    PLATFORM_TARGET,
    summarize_junit,
    summary_json,
    summary_markdown,
)

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="5">
    <testcase classname="lms.djangoapps.courseware.tests.test_views.ViewTests"
              name="test_index" time="0.5"/>
    <testcase classname="common.djangoapps.student.tests.test_login"
              name="test_bad_password" time="0.25">
      <failure message="assert False">boom</failure>
    </testcase>
    <testcase classname="ol_openedx_chat.tests.test_plugin" name="test_renders"
              time="1.5"/>
    <testcase classname="ol_openedx_chat.tests.test_plugin" name="test_skipped"
              time="0.0">
      <skipped message="needs mongo"/>
    </testcase>
    <testcase classname="ol_openedx_logging.tests.test_config" name="test_setup"
              time="0.75">
      <error message="ImportError">nope</error>
    </testcase>
  </testsuite>
</testsuites>
"""


def _by_name(summary: object) -> dict:
    return {t.name: t for t in summary.targets}  # type: ignore[attr-defined]


def test_platform_cases_are_attributed_to_edx_platform() -> None:
    targets = _by_name(summarize_junit(JUNIT, ["ol_openedx_chat"]))
    platform = targets[PLATFORM_TARGET]
    # Two lms/common cases, plus the ol_openedx_logging case the caller did not
    # list — unattributable to a plugin, so it lands here rather than vanishing.
    assert platform.tests == 3  # noqa: PLR2004
    assert platform.failures == 1
    assert platform.errors == 1
    assert platform.passed == 1


def test_listed_plugin_modules_get_their_own_rows() -> None:
    targets = _by_name(
        summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_logging"])
    )
    chat = targets["ol_openedx_chat"]
    assert chat.kind == "plugin"
    assert chat.tests == 2  # noqa: PLR2004
    assert chat.skipped == 1
    assert chat.passed == 1
    assert chat.duration_seconds == 1.5  # noqa: PLR2004
    assert targets["ol_openedx_logging"].errors == 1


def test_unlisted_plugin_falls_back_to_platform() -> None:
    # A module pytest collected but the caller never listed cannot be
    # attributed to a plugin — it must not vanish from the totals.
    summary = summarize_junit(JUNIT, [])
    assert summary.tests == 5  # noqa: PLR2004
    assert [t.name for t in summary.targets] == [PLATFORM_TARGET]


def test_plugin_that_collected_nothing_is_still_reported() -> None:
    # The whole point of the report: "shipped no suite" must be visible, and it
    # looks identical to "suite passed" in the exit code alone.
    summary = summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_sentry"])
    assert summary.contributing_plugins == ["ol_openedx_chat"]
    assert summary.silent_plugins == ["ol_openedx_sentry"]


def test_duplicate_plugin_modules_collapse_to_one_row() -> None:
    summary = summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_chat"])
    assert [t.name for t in summary.targets] == [PLATFORM_TARGET, "ol_openedx_chat"]


def test_totals_aggregate_every_target() -> None:
    summary = summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_logging"])
    assert summary.tests == 5  # noqa: PLR2004
    assert summary.failures == 1
    assert summary.errors == 1
    assert summary.skipped == 1
    assert summary.duration_seconds == 3.0  # noqa: PLR2004


def test_empty_report_summarizes_to_zero() -> None:
    summary = summarize_junit(
        '<testsuites><testsuite name="pytest" tests="0"/></testsuites>',
        ["ol_openedx_chat"],
    )
    assert summary.tests == 0
    assert summary.silent_plugins == ["ol_openedx_chat"]


def test_summary_json_is_parseable_and_carries_the_plugin_verdict() -> None:
    payload = json.loads(
        summary_json(summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_sentry"]))
    )
    assert payload["totals"]["tests"] == 5  # noqa: PLR2004
    assert payload["contributing_plugins"] == ["ol_openedx_chat"]
    assert payload["silent_plugins"] == ["ol_openedx_sentry"]
    chat = next(t for t in payload["targets"] if t["name"] == "ol_openedx_chat")
    assert chat == {
        "name": "ol_openedx_chat",
        "kind": "plugin",
        "tests": 2,
        "passed": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 1,
        "duration_seconds": 1.5,
    }


def test_summary_markdown_renders_a_row_per_target() -> None:
    markdown = summary_markdown(
        summarize_junit(JUNIT, ["ol_openedx_chat", "ol_openedx_sentry"])
    )
    assert "| edx-platform | platform |" in markdown
    assert "| ol_openedx_chat | plugin | 2 |" in markdown
    assert "| ol_openedx_sentry | plugin | 0 |" in markdown
    assert "`ol_openedx_sentry`" in markdown  # named in the silent-plugin note
