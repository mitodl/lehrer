from __future__ import annotations

import subprocess

import pytest

from lehrer.core.mfe import _assert_servable_bundle, _safe_mfe_path


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


def test_servable_bundle_assertion_passes_on_a_webpack_dist(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """frontend-build templates public/index.html into dist via HtmlWebpackPlugin."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    (dist / "app.js").write_text("//")
    argv = _assert_servable_bundle(str(dist))
    assert subprocess.run(argv, capture_output=True).returncode == 0  # noqa: S603


def test_servable_bundle_assertion_fails_on_a_module_library_dist(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A landed frontend-base repo's `make build` writes index.js and no index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.js").write_text("export {};")
    (dist / "index.d.ts").write_text("")
    completed = subprocess.run(  # noqa: S603
        _assert_servable_bundle(str(dist)), capture_output=True, text=True
    )
    assert completed.returncode == 1
    # The message has to name the cause and the next step: this fires in a
    # Concourse log nobody is reading closely.
    assert "module library" in completed.stderr
    assert "lehrer upstream frontend-base-status" in completed.stderr
    assert "legacy-mfe" in completed.stderr


def test_servable_bundle_assertion_fails_on_a_missing_dist(tmp_path) -> None:  # type: ignore[no-untyped-def]
    argv = _assert_servable_bundle(str(tmp_path / "absent"))
    assert subprocess.run(argv, capture_output=True).returncode == 1  # noqa: S603
