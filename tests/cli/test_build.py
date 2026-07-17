from __future__ import annotations

import pytest

from lehrer.cli import build


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Capture the argv each command would hand to ``dagger`` without running it."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(build, "run", lambda *argv, **_kw: calls.append(argv))
    return calls


def test_cell_scoped_command_expands_to_manifest_flags(
    captured: list[tuple[str, ...]],
) -> None:
    build.test("mit-ol/master/mitxonline", "--full")
    (argv,) = captured
    assert argv[:3] == ("dagger", "call", "platform")
    assert argv[3] == "test"
    # The single cell coordinate expands to the three manifest flags...
    assert "--release-name" in argv and "master" in argv
    assert "--deployment-name" in argv and "mitxonline" in argv
    manifest_idx = argv.index("--build-manifest")
    assert argv[manifest_idx + 1].endswith("deployments/mit-ol/build_manifest.yaml")
    # ...and trailing args are still forwarded verbatim.
    assert argv[-1] == "--full"


def test_cell_scoped_command_without_cell_is_passthrough(
    captured: list[tuple[str, ...]],
) -> None:
    build.plugin_regression(None, "--custom-settings", "./settings")
    (argv,) = captured
    assert argv == (
        "dagger",
        "call",
        "platform",
        "plugin-regression",
        "--custom-settings",
        "./settings",
    )


def test_service_commands_target_their_own_module(
    captured: list[tuple[str, ...]],
) -> None:
    build.codejail_test("--foo")
    build.notes("--bar")
    assert captured[0] == ("dagger", "call", "codejail", "test", "--foo")
    assert captured[1] == ("dagger", "call", "notes", "build", "--bar")


def test_bad_cell_coordinate_is_rejected(captured: list[tuple[str, ...]]) -> None:
    with pytest.raises(ValueError, match="group.*release.*deployment"):
        build.check("mit-ol/master")  # missing the deployment segment
    assert captured == []
