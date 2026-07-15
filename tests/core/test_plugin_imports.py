from __future__ import annotations

import pytest

from lehrer.core.plugin_imports import plugin_distributions


def test_selects_plugin_prefixes_and_suffixes() -> None:
    lines = [
        "ol-openedx-logging==0.3.5",
        "openedx-scorm-xblock==19.0.4",
        "edx-sysadmin==0.4.2",
        "rapid-response-xblock==0.11.0",
        "invideoquiz-xblock==2.0.0",
    ]
    assert plugin_distributions(lines) == [
        "ol-openedx-logging",
        "openedx-scorm-xblock",
        "edx-sysadmin",
        "rapid-response-xblock",
        "invideoquiz-xblock",
    ]


def test_skips_bare_libraries() -> None:
    lines = [
        "granian==2.7.9",
        "django-redis==6.0.0",
        "celery-redbeat==2.3.3",
        "setuptools==81.0.0",
        "pydantic-settings[yaml]==2.14.2",
    ]
    assert plugin_distributions(lines) == []


def test_skips_vcs_url_and_comment_lines() -> None:
    lines = [
        "# Experimental plugins",
        "",
        "  ",
        "-r other.txt",
        "git+https://github.com/example/ol-openedx-thing.git#egg=ol-openedx-thing",
        "https://example.com/pkg.tar.gz",
    ]
    assert plugin_distributions(lines) == []


def test_strips_extras_specifiers_and_inline_comments() -> None:
    lines = [
        "ol-openedx-chat==0.5.9  # AI chat feature",
        "ol-openedx-chat-xblock>=0.4.6",
        "edx-sga==0.29.0 ; python_version >= '3.11'",
    ]
    assert plugin_distributions(lines) == [
        "ol-openedx-chat",
        "ol-openedx-chat-xblock",
        "edx-sga",
    ]


def test_normalizes_and_dedupes() -> None:
    lines = [
        "OL_OpenEdX.Logging==0.3.5",
        "ol-openedx-logging==0.3.5",
    ]
    assert plugin_distributions(lines) == ["ol-openedx-logging"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("edx-name-affirmation", ["edx-name-affirmation"]),
        ("openedx-companion-auth==1.2.0", ["openedx-companion-auth"]),
        ("ol-social-auth==0.2.2", ["ol-social-auth"]),
        ("django-aqueduct==0.9.0", []),
        ("opentelemetry-api", []),
    ],
)
def test_individual_lines(line: str, expected: list[str]) -> None:
    assert plugin_distributions([line]) == expected
