from __future__ import annotations

import pytest

from lehrer.core.platform import _repo_shorthand


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://github.com/openedx/openedx-translations",
            "openedx/openedx-translations",
        ),
        (
            "https://github.com/openedx/openedx-translations/",
            "openedx/openedx-translations",
        ),
        (
            "https://github.com/openedx/openedx-translations.git",
            "openedx/openedx-translations",
        ),
        ("openedx/openedx-translations", "openedx/openedx-translations"),
    ],
)
def test_repo_shorthand(value: str, expected: str) -> None:
    assert _repo_shorthand(value) == expected
