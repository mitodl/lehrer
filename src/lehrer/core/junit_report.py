"""Turn a pytest JUnit XML report into a machine- and human-readable summary.

``platform test`` runs one pytest over edx-platform's own suite *plus* the
installed plugin packages, so its exit code answers "did anything break?" but
not "whose tests actually ran?".  That second question is the one a plugin
bump needs answered: a plugin whose ``[tests]`` extra never landed collects
zero tests and the run stays green, which looks identical to a plugin whose
suite passed.  Only the post-collection report can tell those apart.

This module is the pure, dependency-free half of that reporting.  It parses the
JUnit XML pytest writes and attributes every test case to a *target* — the
edx-platform suite, or one of the plugin packages handed to ``--pyargs`` —
using the ``classname``'s top-level package.  Plugin targets that collected
nothing are still reported (with zero counts), because "this plugin
contributed no tests" is the signal, not an absence of one.

Stdlib only and no Dagger imports: it is injected into the build container to
run next to pytest, and unit-tested on the host from the same source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from xml.etree import ElementTree

if TYPE_CHECKING:
    from collections.abc import Iterable

PLATFORM_TARGET = "edx-platform"


@dataclass
class TargetSummary:
    """Per-target test counts, as attributed from the JUnit report."""

    name: str
    kind: str  # "platform" | "plugin"
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0

    @property
    def passed(self) -> int:
        """Cases that neither failed, errored, nor were skipped."""
        return self.tests - self.failures - self.errors - self.skipped


@dataclass
class RunSummary:
    """The whole run: overall counts plus a row per target."""

    targets: list[TargetSummary] = field(default_factory=list)

    @property
    def tests(self) -> int:
        return sum(t.tests for t in self.targets)

    @property
    def failures(self) -> int:
        return sum(t.failures for t in self.targets)

    @property
    def errors(self) -> int:
        return sum(t.errors for t in self.targets)

    @property
    def skipped(self) -> int:
        return sum(t.skipped for t in self.targets)

    @property
    def duration_seconds(self) -> float:
        return sum(t.duration_seconds for t in self.targets)

    @property
    def contributing_plugins(self) -> list[str]:
        """Plugin targets that collected at least one test."""
        return [t.name for t in self.targets if t.kind == "plugin" and t.tests]

    @property
    def silent_plugins(self) -> list[str]:
        """Plugin targets that collected nothing — installed but shipping no tests."""
        return [t.name for t in self.targets if t.kind == "plugin" and not t.tests]


def _target_of(classname: str, plugin_modules: Iterable[str]) -> str:
    """Attribute a JUnit ``classname`` to a plugin package or to edx-platform.

    pytest sets ``classname`` to the dotted module path (plus class, if any) of
    the test, so a test collected from a ``--pyargs`` plugin package always
    begins with that package's import name.  edx-platform's own cases are
    rooted at ``lms``/``cms``/``openedx``/``common`` and match nothing here.
    """
    head = classname.split(".", 1)[0]
    for module in plugin_modules:
        if head == module:
            return module
    return PLATFORM_TARGET


def summarize_junit(xml_text: str, plugin_modules: Iterable[str] = ()) -> RunSummary:
    """Parse a pytest JUnit XML report into a :class:`RunSummary`.

    ``plugin_modules`` are the import names handed to pytest via ``--pyargs``.
    Every one of them gets a row even when it collected nothing, so the report
    distinguishes "this plugin's tests passed" from "this plugin shipped none".
    """
    modules = list(dict.fromkeys(plugin_modules))
    summaries: dict[str, TargetSummary] = {
        PLATFORM_TARGET: TargetSummary(name=PLATFORM_TARGET, kind="platform")
    }
    for module in modules:
        summaries[module] = TargetSummary(name=module, kind="plugin")

    root = ElementTree.fromstring(xml_text)  # noqa: S314
    for case in root.iter("testcase"):
        target = summaries[_target_of(case.get("classname", ""), modules)]
        target.tests += 1
        target.duration_seconds += float(case.get("time") or 0.0)
        if case.find("failure") is not None:
            target.failures += 1
        elif case.find("error") is not None:
            target.errors += 1
        elif case.find("skipped") is not None:
            target.skipped += 1

    return RunSummary(targets=list(summaries.values()))


def summary_json(summary: RunSummary) -> str:
    """Serialize a :class:`RunSummary` as indented JSON for CI to consume."""
    return json.dumps(
        {
            "totals": {
                "tests": summary.tests,
                "failures": summary.failures,
                "errors": summary.errors,
                "skipped": summary.skipped,
                "duration_seconds": round(summary.duration_seconds, 3),
            },
            "contributing_plugins": summary.contributing_plugins,
            "silent_plugins": summary.silent_plugins,
            "targets": [
                {
                    "name": t.name,
                    "kind": t.kind,
                    "tests": t.tests,
                    "passed": t.passed,
                    "failures": t.failures,
                    "errors": t.errors,
                    "skipped": t.skipped,
                    "duration_seconds": round(t.duration_seconds, 3),
                }
                for t in summary.targets
            ],
        },
        indent=2,
    )


def summary_markdown(summary: RunSummary, title: str = "Platform test run") -> str:
    """Render a :class:`RunSummary` as a Markdown table for a CI step summary."""
    lines = [
        f"### {title}",
        "",
        f"**{summary.tests}** tests · {summary.failures} failed · "
        f"{summary.errors} errored · {summary.skipped} skipped · "
        f"{summary.duration_seconds:.1f}s",
        "",
        "| Target | Kind | Tests | Passed | Failed | Errors | Skipped | Time (s) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {t.name} | {t.kind} | {t.tests} | {t.passed} | {t.failures} | "
        f"{t.errors} | {t.skipped} | {t.duration_seconds:.1f} |"
        for t in summary.targets
    ]
    if summary.silent_plugins:
        lines += [
            "",
            "Plugins that collected no tests (installed, but shipping no suite): "
            + ", ".join(f"`{name}`" for name in summary.silent_plugins),
        ]
    return "\n".join(lines) + "\n"
