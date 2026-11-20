from __future__ import annotations

from pathlib import Path

import pytest

from lehrer.cli.features import SETTINGS_BASE, settings_inventories
from lehrer.core.settings_inventory import (
    InventoryError,
    configured_class,
    inventory,
)
from lehrer.settings.base import ProductionSettingsMixin, StudioSettingsMixin

DEPLOYMENTS = Path(__file__).parents[2] / "deployments"


@pytest.mark.parametrize("mixin", [ProductionSettingsMixin, StudioSettingsMixin])
def test_walker_matches_the_mixins_model_fields(mixin: type) -> None:
    # The walker reads source; pydantic reads the class. If they disagree, the
    # walker has missed a declaration form and would reject valid keys.
    walked = inventory(SETTINGS_BASE, mixin.__name__)
    assert set(walked) == set(mixin.model_fields)  # type: ignore[attr-defined]


@pytest.mark.parametrize("group", ["mit-ol", "generic"])
def test_every_group_inventories_both_services(group: str) -> None:
    found = settings_inventories(DEPLOYMENTS / group)
    assert set(found) == {"lms", "cms"}
    # One field from each layer: the generated model, the lehrer mixin, and
    # (CMS) the Studio mixin.
    assert {"FEATURES", "LOG_DIR"} <= set(found["lms"])
    assert "SOCIAL_AUTH_EDX_OAUTH2_KEY" in found["cms"]


def test_aliases_are_recorded() -> None:
    lms = settings_inventories(DEPLOYMENTS / "mit-ol")["lms"]
    assert lms["ENABLE_AUTHN_MICROFRONTEND"].key == "EDXAPP_ENABLE_AUTHN_MFE"


def test_class_vars_and_private_names_are_skipped() -> None:
    lms = settings_inventories(DEPLOYMENTS / "mit-ol")["lms"]
    assert "FEATURES_COMPAT_KEYS" not in lms
    assert "model_config" not in lms


def test_entry_class_is_the_one_configured() -> None:
    entry = DEPLOYMENTS / "mit-ol" / "settings" / "lms" / "aqueduct.py"
    assert configured_class(entry) == "LMSProductionSettings"


def test_an_unfollowable_base_fails_loudly(tmp_path: Path) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text(
        "from somewhere import Mystery\n\nclass Settings(Mystery):\n    A: int = 1\n"
    )
    with pytest.raises(InventoryError, match="Mystery"):
        inventory(entry, "Settings")


def test_a_missing_injected_module_fails_loudly(tmp_path: Path) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text(
        "from .models.base import Mixin\n\nclass Settings(Mixin):\n    pass\n"
    )
    with pytest.raises(InventoryError, match="does not exist"):
        inventory(entry, "Settings")
