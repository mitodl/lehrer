from __future__ import annotations

import pytest
from pydantic import ValidationError

from lehrer.core.mfe_config import (
    BuildConfig,
    MfeBuildConfig,
    SlotFileByRelease,
    json_schema,
)


class TestSlotFileByReleaseResolve:
    def test_exact_release_match_wins_over_default(self) -> None:
        slot = SlotFileByRelease(
            dest="footer.tsx",
            by_release={"sumac": "footer.sumac.tsx", "default": "footer.tsx"},
        )
        assert slot.resolve("sumac") == "footer.sumac.tsx:footer.tsx"

    def test_falls_back_to_default_when_release_absent(self) -> None:
        slot = SlotFileByRelease(
            dest="footer.tsx",
            by_release={"default": "footer.tsx", "sumac": "footer.sumac.tsx"},
        )
        assert slot.resolve("teak") == "footer.tsx:footer.tsx"

    def test_raises_when_no_match_and_no_default(self) -> None:
        slot = SlotFileByRelease(
            dest="footer.tsx", by_release={"sumac": "footer.sumac.tsx"}
        )
        with pytest.raises(ValueError, match="No source for"):
            slot.resolve("teak")

    def test_release_name_lookup_is_case_insensitive(self) -> None:
        slot = SlotFileByRelease(
            dest="footer.tsx", by_release={"sumac": "footer.sumac.tsx"}
        )
        assert slot.resolve("SUMAC") == "footer.sumac.tsx:footer.tsx"


class TestRelativeMfePathGuard:
    @pytest.mark.parametrize(
        "dest", ["footer.tsx", "nested/footer.tsx", "./footer.tsx"]
    )
    def test_accepts_relative_paths(self, dest: str) -> None:
        slot = SlotFileByRelease(dest=dest, by_release={"default": "x"})
        assert slot.dest == dest

    @pytest.mark.parametrize(
        "dest", ["/etc/passwd", "../escape.tsx", "../../escape.tsx", ".."]
    )
    def test_rejects_absolute_and_traversal_paths(self, dest: str) -> None:
        with pytest.raises(ValidationError):
            SlotFileByRelease(dest=dest, by_release={"default": "x"})


class TestBuildConfigMfeLookup:
    def test_unconfigured_mfe_returns_empty_default(self) -> None:
        config = BuildConfig()
        result = config.mfe("learning")
        assert result == MfeBuildConfig()

    def test_lookup_is_case_insensitive(self) -> None:
        config = BuildConfig(
            mfes={"learning": MfeBuildConfig(extra_npm_bundles=["foo|bar"])}
        )
        assert config.mfe("Learning").extra_npm_bundles == ["foo|bar"]


class TestResolveExtraSlotFiles:
    def test_mixes_plain_strings_and_by_release_entries(self) -> None:
        mfe_cfg = MfeBuildConfig(
            extra_slot_files=[
                "plain.tsx",
                SlotFileByRelease(
                    dest="footer.tsx",
                    by_release={"sumac": "footer.sumac.tsx", "default": "footer.tsx"},
                ),
            ]
        )
        assert mfe_cfg.resolve_extra_slot_files("sumac") == [
            "plain.tsx",
            "footer.sumac.tsx:footer.tsx",
        ]


def test_json_schema_round_trips() -> None:
    schema = json_schema()
    assert schema == BuildConfig.model_json_schema()
    assert schema["title"] == "BuildConfig"
