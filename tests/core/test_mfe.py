from __future__ import annotations

import pytest

from lehrer.core.mfe import _safe_mfe_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("footer.tsx", "footer.tsx"),
        ("nested/footer.tsx", "nested/footer.tsx"),
        ("./footer.tsx", "footer.tsx"),
    ],
)
def test_accepts_and_normalizes_relative_paths(path: str, expected: str) -> None:
    assert _safe_mfe_path(path, field="extra_slot_files") == expected


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../escape.tsx", "../../nested/escape.tsx", ".."]
)
def test_rejects_absolute_and_traversal_paths(path: str) -> None:
    with pytest.raises(ValueError, match="must be a relative path"):
        _safe_mfe_path(path, field="styles_file")


def test_error_message_names_the_offending_field() -> None:
    with pytest.raises(ValueError, match="styles_file"):
        _safe_mfe_path("/etc/passwd", field="styles_file")
