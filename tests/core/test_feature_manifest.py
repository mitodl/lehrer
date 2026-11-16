from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from lehrer.cli.features import settings_inventories
from lehrer.core.build_manifest import load_manifest
from lehrer.core.feature_manifest import (
    AdoptionFile,
    FeatureDefinition,
    FeatureManifestError,
    Group,
    ScopesFile,
    load_definitions,
    merge_operations,
    substitute,
)
from lehrer.core.mfe_config import BuildConfig

MIT_OL = Path(__file__).parents[2] / "deployments" / "mit-ol"
SLOT_DIR = MIT_OL / "mfe_slot_config" / "legacy"
MANIFEST = load_manifest(MIT_OL / "build_manifest.yaml")
INVENTORIES = settings_inventories(MIT_OL)
BASELINE = BuildConfig.model_validate(
    yaml.safe_load((SLOT_DIR / "build_config.yaml").read_text())
)

AI_DRAWER: dict[str, Any] = {
    "version": 1,
    "feature": "ai-drawer",
    "summary": "AskTIM chat drawer in the learning MFE.",
    "origin": "plugin",
    "provided_by": "ol-openedx-chat",
    "frontend_paths": ["legacy"],
    "parameters": {
        "implementation": {
            "type": "enum",
            "choices": ["slot", "standalone"],
            "default": "standalone",
        }
    },
    "requires": {"plugins": ["ol-openedx-chat"], "frontends": ["learning"]},
    "operations": {
        "mfe_build_env": {
            "learning": {
                "ENABLE_AI_DRAWER_SLOT": {
                    "by_parameter": "implementation",
                    "cases": {"slot": "true", "standalone": "false"},
                }
            }
        }
    },
}

SCOPES: dict[str, Any] = {
    "version": 1,
    "scopes": {
        "mxo-ci": {
            "cell": {"release": "master", "deployment": "mitxonline"},
            "frontends": {"learning": "legacy"},
        },
        "mxo-qa": {
            "cell": {"release": "master", "deployment": "mitxonline"},
            "frontends": {"learning": "legacy"},
        },
        "mitx-ci": {
            "cell": {"release": "master", "deployment": "mitx"},
            "frontends": {"learning": "legacy"},
        },
        "xpro-ci": {
            "cell": {"release": "ulmo", "deployment": "xpro"},
            "frontends": {"learning": "legacy"},
        },
        "site-ci": {
            "cell": {"release": "master", "deployment": "mitxonline"},
            "frontends": {"learning": {"site": "mitxonline"}},
        },
    },
    "sets": {"mxo-all": ["mxo-ci", "mxo-qa"]},
}


def _definition(**overrides: Any) -> dict[str, Any]:
    base = {
        "version": 1,
        "feature": "thing",
        "summary": "A test feature.",
        "origin": "operator",
    }
    return {**base, **overrides}


def _group(
    definitions: list[dict[str, Any]],
    adoption: dict[str, Any],
    scopes: dict[str, Any] | None = None,
    tmp_path: Path | None = None,
) -> Group:
    source = tmp_path or Path("definitions")
    return Group(
        definitions={
            d["feature"]: _loaded(d, source / f"{d['feature']}.yaml")
            for d in definitions
        },
        scopes=ScopesFile.model_validate(scopes or SCOPES),
        adoption=AdoptionFile.model_validate({"version": 1, "adoption": adoption}),
        manifest=MANIFEST,
        inventories=INVENTORIES,
        slot_dir=SLOT_DIR,
        baseline=BASELINE,
    )


def _loaded(data: dict[str, Any], path: Path) -> Any:
    from lehrer.core.feature_manifest import Definition

    return Definition(FeatureDefinition.model_validate(data), path)


def _feature(group: Group, scope: str, name: str) -> Any:
    return next(f for f in group.resolve(scope).features if f.feature == name)


class TestAIDrawer:
    def test_set_adoption_reaches_every_member(self) -> None:
        group = _group(
            [AI_DRAWER], {"mxo-all": {"ai-drawer": {"implementation": "slot"}}}
        )
        for scope in ("mxo-ci", "mxo-qa"):
            drawer = _feature(group, scope, "ai-drawer")
            assert drawer.mfe_build_env == {
                "learning": {"ENABLE_AI_DRAWER_SLOT": "true"}
            }
        assert group.resolve("mitx-ci").features == []

    def test_scope_block_replaces_the_set_per_parameter(self) -> None:
        group = _group(
            [AI_DRAWER],
            {
                "mxo-all": {"ai-drawer": {"implementation": "slot"}},
                "mxo-qa": {"ai-drawer": {"implementation": "standalone"}},
            },
        )
        drawer = _feature(group, "mxo-qa", "ai-drawer")
        assert drawer.mfe_build_env["learning"]["ENABLE_AI_DRAWER_SLOT"] == "false"
        assert group.adopted("mxo-qa")["ai-drawer"].via == ["mxo-all", "mxo-qa"]

    def test_enabled_false_turns_off_a_set_adoption(self) -> None:
        group = _group(
            [AI_DRAWER],
            {"mxo-all": {"ai-drawer": {}}, "mxo-qa": {"ai-drawer": {"enabled": False}}},
        )
        assert group.adopted("mxo-qa") == {}
        assert "ai-drawer" in group.adopted("mxo-ci")

    def test_site_project_frontend_is_refused(self) -> None:
        group = _group([AI_DRAWER], {"site-ci": {"ai-drawer": {}}})
        with pytest.raises(FeatureManifestError, match="builds 'learning' as site"):
            group.resolve("site-ci")

    def test_unlisted_frontend_is_refused(self) -> None:
        scopes = {
            "version": 1,
            "scopes": {"bare": {"cell": {"release": "master", "deployment": "mitx"}}},
        }
        group = _group([AI_DRAWER], {"bare": {"ai-drawer": {}}}, scopes)
        with pytest.raises(FeatureManifestError, match="frontends do not list"):
            group.resolve("bare")


class TestAdoption:
    def test_two_sets_adopting_one_feature_conflict(self) -> None:
        scopes = {**SCOPES, "sets": {"a": ["mxo-ci"], "b": ["mxo-ci"]}}
        group = _group(
            [AI_DRAWER], {"a": {"ai-drawer": {}}, "b": {"ai-drawer": {}}}, scopes
        )
        with pytest.raises(FeatureManifestError, match="more than one set"):
            group.adopted("mxo-ci")

    @pytest.mark.parametrize(
        ("block", "match"),
        [
            ({"nope": 1}, "no parameter 'nope'"),
            ({"implementation": "other"}, "is not one of"),
            ({"enabled": "yes"}, "true or false"),
        ],
    )
    def test_bad_values_are_refused(self, block: dict[str, Any], match: str) -> None:
        group = _group([AI_DRAWER], {"mxo-ci": {"ai-drawer": block}})
        with pytest.raises(FeatureManifestError, match=match):
            group.adopted("mxo-ci")

    def test_a_required_parameter_must_be_supplied(self) -> None:
        definition = _definition(parameters={"n": {"type": "integer"}})
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(
            FeatureManifestError, match="needs a value for parameter 'n'"
        ):
            group.adopted("mxo-ci")

    def test_unknown_feature_and_scope_names_fail(self) -> None:
        with pytest.raises(FeatureManifestError, match="no definition"):
            _group([], {"mxo-ci": {"ghost": {}}}).adopted("mxo-ci")
        with pytest.raises(FeatureManifestError, match="neither scopes nor sets"):
            _group([], {"typo": {}}).adopted("mxo-ci")

    def test_required_features_must_be_adopted_too(self) -> None:
        dependent = _definition(feature="dependent", requires={"features": ["thing"]})
        group = _group([_definition(), dependent], {"mxo-ci": {"dependent": {}}})
        with pytest.raises(
            FeatureManifestError, match=r"requires features \['thing'\]"
        ):
            group.resolve("mxo-ci")


class TestSettings:
    def test_keys_are_checked_against_the_settings_model(self) -> None:
        definition = _definition(operations={"settings": {"lms": {"NOT_A_SETTING": 1}}})
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(FeatureManifestError, match="NOT_A_SETTING"):
            group.resolve("mxo-ci")

    def test_aliased_fields_are_keyed_by_their_alias(self) -> None:
        definition = _definition(
            operations={"settings": {"lms": {"ENABLE_AUTHN_MICROFRONTEND": True}}}
        )
        thing = _feature(
            _group([definition], {"mxo-ci": {"thing": {}}}), "mxo-ci", "thing"
        )
        assert thing.settings == {"lms": {"EDXAPP_ENABLE_AUTHN_MFE": True}}

    def test_mixin_fields_are_in_the_inventory(self) -> None:
        # Declared on ProductionSettingsMixin, not in the generated model.
        definition = _definition(operations={"settings": {"lms": {"LOG_DIR": "/x"}}})
        _group([definition], {"mxo-ci": {"thing": {}}}).resolve("mxo-ci")

    @pytest.mark.parametrize("group_name", ["settings", "features"])
    def test_runtime_config_settings_are_reserved(self, group_name: str) -> None:
        with pytest.raises(
            ValidationError, match="only be written through site_config"
        ):
            FeatureDefinition.model_validate(
                _definition(operations={group_name: {"lms": {"MFE_CONFIG": {}}}})
            )

    def test_cells_without_aqueduct_take_no_settings(self) -> None:
        definition = _definition(operations={"features": {"lms": {"ENABLE_X": True}}})
        group = _group([definition], {"xpro-ci": {"thing": {}}})
        with pytest.raises(FeatureManifestError, match="does not use django-aqueduct"):
            group.resolve("xpro-ci")

    def test_null_parameter_omits_the_key(self) -> None:
        definition = _definition(
            parameters={"dir": {"type": "string", "default": None}},
            operations={"settings": {"lms": {"LOG_DIR": "${dir}"}}},
        )
        thing = _feature(
            _group([definition], {"mxo-ci": {"thing": {}}}), "mxo-ci", "thing"
        )
        assert thing.settings == {"lms": {}}


class TestPlugins:
    def test_missing_plugin_is_refused(self) -> None:
        definition = _definition(requires={"plugins": ["not-a-plugin"]})
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(
            FeatureManifestError, match="'not-a-plugin' is not installed"
        ):
            group.resolve("mxo-ci")

    def test_vcs_only_plugin_is_unverifiable(self) -> None:
        manifest = MANIFEST.model_copy(deep=True)
        cell = manifest.resolve_cell("master", "mitx")
        cell.overrides.append("vcs-plugin @ git+https://example.invalid/vcs-plugin.git")
        definition = _definition(requires={"plugins": ["vcs-plugin"]})
        group = _group([definition], {"mitx-ci": {"thing": {}}})
        group.manifest = manifest
        with pytest.raises(FeatureManifestError, match="cannot be verified"):
            group.resolve("mitx-ci")


class TestSiteConfig:
    def test_promoted_keys_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="site-level keys"):
            FeatureDefinition.model_validate(
                _definition(
                    operations={"site_config": {"mfe_config": {"LOGO_URL": "x"}}}
                )
            )

    def test_frontend_site_config_writes_common_app_config_only(self) -> None:
        with pytest.raises(ValidationError, match="commonAppConfig"):
            FeatureDefinition.model_validate(
                _definition(
                    operations={"site_config": {"frontend_site_config": {"apps": []}}}
                )
            )

    def test_by_release_selects_the_cell_release(self) -> None:
        definition = _definition(
            operations={
                "site_config": {
                    "by_release": {
                        "ulmo": {"mfe_config": {"CHAT": True}},
                        "default": {
                            "frontend_site_config": {"commonAppConfig": {"chat": True}}
                        },
                    }
                }
            }
        )
        thing = _feature(
            _group([definition], {"mxo-ci": {"thing": {}}}), "mxo-ci", "thing"
        )
        assert thing.site_config == {
            "FRONTEND_SITE_CONFIG": {"commonAppConfig": {"chat": True}}
        }


class TestConflicts:
    def _two(self, a_ops: dict[str, Any], b_ops: dict[str, Any]) -> Group:
        return _group(
            [
                _definition(feature="a", operations=a_ops),
                _definition(feature="b", operations=b_ops),
            ],
            {"mxo-ci": {"a": {}, "b": {}}},
        )

    def test_unequal_values_on_one_setting_conflict(self) -> None:
        group = self._two(
            {"settings": {"lms": {"LOG_DIR": "/a"}}},
            {"settings": {"lms": {"LOG_DIR": "/b"}}},
        )
        with pytest.raises(
            FeatureManifestError, match="conflict on setting lms LOG_DIR"
        ):
            group.resolve("mxo-ci")

    def test_equal_values_are_shared(self) -> None:
        ops = {"settings": {"lms": {"LOG_DIR": "/a"}}}
        resolved = self._two(ops, ops).resolve("mxo-ci")
        assert resolved.owners[("setting", "lms", "LOG_DIR")] == ["a", "b"]

    def test_features_and_settings_share_a_key_space(self) -> None:
        group = self._two(
            {"features": {"lms": {"LOG_DIR": "/a"}}},
            {"settings": {"lms": {"LOG_DIR": "/b"}}},
        )
        with pytest.raises(FeatureManifestError, match="LOG_DIR"):
            group.resolve("mxo-ci")

    def test_runtime_destinations_conflict_across_settings(self) -> None:
        group = self._two(
            {"site_config": {"mfe_config": {"CHAT": True}}},
            {
                "site_config": {
                    "frontend_site_config": {"commonAppConfig": {"CHAT": False}}
                }
            },
        )
        with pytest.raises(
            FeatureManifestError, match="site-config commonAppConfig CHAT"
        ):
            group.resolve("mxo-ci")

    def test_legacy_override_competes_with_global_mfe_config(self) -> None:
        group = self._two(
            {"site_config": {"mfe_config": {"CHAT": True}}},
            {"site_config": {"mfe_config_overrides": {"learning": {"CHAT": False}}}},
        )
        with pytest.raises(FeatureManifestError, match="legacy MFE config CHAT"):
            group.resolve("mxo-ci")

    def test_slot_dest_conflicts_with_the_baseline(self) -> None:
        definition = _definition(
            frontend_paths=["legacy"],
            requires={"frontends": ["learning"]},
            operations={
                "mfe_assets": {
                    "learning": {
                        "extra_slot_files": ["Footer.jsx:AIDrawerManagerSidebar.jsx"]
                    }
                }
            },
        )
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(FeatureManifestError, match="build_config.yaml"):
            group.resolve("mxo-ci")

    def test_bootstrap_identities_conflict(self) -> None:
        group = self._two(
            {"bootstrap": {"waffle_flags": [{"name": "x.y", "everyone": True}]}},
            {"bootstrap": {"waffle_flags": [{"name": "x.y", "everyone": False}]}},
        )
        with pytest.raises(FeatureManifestError, match="bootstrap waffle_flags x.y"):
            group.resolve("mxo-ci")


class TestDefinitions:
    def test_lookups_cover_every_choice(self) -> None:
        drawer = {
            **AI_DRAWER,
            "operations": {
                "mfe_build_env": {
                    "learning": {
                        "X": {"by_parameter": "implementation", "cases": {"slot": "1"}}
                    }
                }
            },
        }
        with pytest.raises(ValidationError, match="miss"):
            FeatureDefinition.model_validate(drawer)

    def test_placeholders_name_declared_parameters(self) -> None:
        with pytest.raises(ValidationError, match="names no declared parameter"):
            FeatureDefinition.model_validate(
                _definition(operations={"settings": {"lms": {"LOG_DIR": "${nope}"}}})
            )

    def test_enabled_is_not_a_parameter(self) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            FeatureDefinition.model_validate(
                _definition(parameters={"enabled": {"type": "boolean"}})
            )

    def test_plugin_origin_names_its_distribution(self) -> None:
        with pytest.raises(ValidationError, match="provided_by"):
            FeatureDefinition.model_validate(_definition(origin="plugin"))

    def test_names_are_unique_across_sources(self, tmp_path: Path) -> None:
        for root in ("catalog", "definitions"):
            (tmp_path / root).mkdir()
            (tmp_path / root / "thing.yaml").write_text(yaml.safe_dump(_definition()))
        with pytest.raises(FeatureManifestError, match="declared by both"):
            load_definitions(tmp_path / "catalog", tmp_path / "definitions", None)

    def test_file_is_named_after_its_feature(self, tmp_path: Path) -> None:
        (tmp_path / "other.yaml").write_text(yaml.safe_dump(_definition()))
        with pytest.raises(FeatureManifestError, match="thing.yaml"):
            load_definitions(None, tmp_path, None)

    def test_vendored_must_be_the_plugins_own(self, tmp_path: Path) -> None:
        vendored = tmp_path / "some-plugin" / "1.0"
        vendored.mkdir(parents=True)
        (vendored / "thing.yaml").write_text(yaml.safe_dump(_definition()))
        with pytest.raises(FeatureManifestError, match="origin: plugin"):
            load_definitions(None, None, tmp_path)


class TestMergeAndSubstitute:
    def test_identity_lists_replace_matching_entries(self) -> None:
        base = {
            "bootstrap": {
                "waffle_flags": [{"name": "a.b", "everyone": True}, {"name": "c.d"}]
            }
        }
        override = {
            "bootstrap": {
                "waffle_flags": [{"name": "a.b", "staff": True}, {"name": "e.f"}]
            }
        }
        merged = merge_operations(base, override)
        assert merged["bootstrap"]["waffle_flags"] == [
            {"name": "a.b", "staff": True},
            {"name": "c.d"},
            {"name": "e.f"},
        ]

    def test_slot_files_merge_by_dest(self) -> None:
        base = {
            "mfe_assets": {
                "m": {
                    "extra_slot_files": [
                        "A.jsx",
                        {"dest": "B.jsx", "by_release": {"default": "B.jsx"}},
                    ]
                }
            }
        }
        override = {"mfe_assets": {"m": {"extra_slot_files": ["Other.jsx:B.jsx"]}}}
        merged = merge_operations(base, override)
        assert merged["mfe_assets"]["m"]["extra_slot_files"] == [
            "A.jsx",
            "Other.jsx:B.jsx",
        ]

    def test_whole_placeholder_keeps_its_type(self) -> None:
        assert substitute({"n": "${n}", "s": "x-${n}"}, {"n": 3}) == {
            "n": 3,
            "s": "x-3",
        }

    @pytest.mark.parametrize(
        ("path", "value", "match"),
        [
            (
                ("bootstrap", "oauth_applications", "client_id_env"),
                "lower",
                "environment",
            ),
            (("bootstrap", "oauth_applications", "name"), "{SECRET_KEY}", "braces"),
        ],
    )
    def test_bootstrap_parameters_are_restricted(
        self, path: tuple[str, ...], value: str, match: str
    ) -> None:
        with pytest.raises(FeatureManifestError, match=match):
            substitute("${p}", {"p": value}, path)

    def test_feature_providers_and_tokens_are_not_optional(self) -> None:
        definition = _definition(
            operations={
                "bootstrap": {
                    "service_access_tokens": [
                        {
                            "username": "svc",
                            "email": "svc@example.invalid",
                            "token_env": "SVC_TOKEN",
                            "application_name": "svc",
                        }
                    ]
                }
            }
        )
        thing = _feature(
            _group([definition], {"mxo-ci": {"thing": {}}}), "mxo-ci", "thing"
        )
        assert thing.bootstrap.service_access_tokens[0].optional is False

    def test_fragments_cannot_grant_superuser(self) -> None:
        definition = _definition(
            operations={
                "bootstrap": {
                    "users": [
                        {
                            "username": "u",
                            "email": "u@example.invalid",
                            "superuser": True,
                        }
                    ]
                }
            }
        )
        with pytest.raises(FeatureManifestError, match="base spec"):
            _group([definition], {"mxo-ci": {"thing": {}}}).resolve("mxo-ci")


def test_shared_legacy_builds_must_agree() -> None:
    scopes = {
        "version": 1,
        "scopes": {
            name: {
                "cell": {"release": "master", "deployment": "mitxonline"},
                "frontends": {"learning": {"legacy": "mxo-learning"}},
            }
            for name in ("one", "two")
        },
    }
    group = _group(
        [AI_DRAWER],
        {"one": {"ai-drawer": {"implementation": "slot"}}, "two": {"ai-drawer": {}}},
        scopes,
    )
    (error,) = group.check()
    assert "share the learning build 'mxo-learning'" in error


MODE = {"mode": {"type": "enum", "choices": ["a", "b"], "default": "a"}}


class TestReviewRegressions:
    def test_a_lookup_cannot_write_a_promoted_site_key(self) -> None:
        definition = _definition(
            parameters=MODE,
            operations={
                "site_config": {
                    "mfe_config": {
                        "by_parameter": "mode",
                        "cases": {
                            "a": {"LMS_BASE_URL": "https://x.invalid"},
                            "b": None,
                        },
                    }
                }
            },
        )
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(FeatureManifestError, match="site-level keys"):
            group.resolve("mxo-ci")

    def test_a_flat_site_config_override_reaches_a_by_release_definition(self) -> None:
        definition = _definition(
            operations={
                "site_config": {
                    "by_release": {"default": {"mfe_config": {"CHAT": True}}}
                }
            }
        )
        adoption = {
            "mxo-ci": {
                "thing": {"operations": {"site_config": {"mfe_config": {"OTHER": 1}}}}
            }
        }
        thing = _feature(_group([definition], adoption), "mxo-ci", "thing")
        assert thing.site_config == {"MFE_CONFIG": {"CHAT": True, "OTHER": 1}}

    def test_a_scalar_over_a_mapping_conflicts(self) -> None:
        group = _group(
            [
                _definition(
                    feature="a",
                    operations={"site_config": {"mfe_config": {"CHAT": {"on": True}}}},
                ),
                _definition(
                    feature="b", operations={"site_config": {"mfe_config": {"CHAT": 5}}}
                ),
            ],
            {"mxo-ci": {"a": {}, "b": {}}},
        )
        with pytest.raises(
            FeatureManifestError, match="conflict on setting lms MFE_CONFIG CHAT"
        ):
            group.resolve("mxo-ci")

    def test_a_legacy_override_inside_a_global_mapping_conflicts(self) -> None:
        group = _group(
            [
                _definition(
                    feature="a",
                    operations={"site_config": {"mfe_config": {"CHAT": {"x": 1}}}},
                ),
                _definition(
                    feature="b",
                    operations={
                        "site_config": {
                            "mfe_config_overrides": {"learning": {"CHAT": 5}}
                        }
                    },
                ),
            ],
            {"mxo-ci": {"a": {}, "b": {}}},
        )
        with pytest.raises(FeatureManifestError, match="legacy MFE config CHAT"):
            group.resolve("mxo-ci")

    def test_an_empty_mapping_does_not_conflict(self) -> None:
        group = _group(
            [
                _definition(
                    feature="a",
                    operations={"site_config": {"mfe_config": {"CHAT": {}}}},
                ),
                _definition(
                    feature="b",
                    operations={"site_config": {"mfe_config": {"CHAT": {"x": 1}}}},
                ),
            ],
            {"mxo-ci": {"a": {}, "b": {}}},
        )
        group.resolve("mxo-ci")

    def test_a_null_enum_omits_its_lookup(self) -> None:
        definition = _definition(
            parameters={"mode": {**MODE["mode"], "default": None}},
            operations={
                "site_config": {
                    "mfe_config": {
                        "CHAT": {"by_parameter": "mode", "cases": {"a": 1, "b": 2}}
                    }
                }
            },
        )
        thing = _feature(
            _group([definition], {"mxo-ci": {"thing": {}}}), "mxo-ci", "thing"
        )
        assert thing.site_config == {}

    def test_an_override_entry_without_its_identity_is_an_error(self) -> None:
        definition = _definition(
            operations={"bootstrap": {"waffle_flags": [{"name": "thing.on"}]}}
        )
        adoption = {
            "mxo-ci": {
                "thing": {
                    "operations": {"bootstrap": {"waffle_flags": [{"everyone": False}]}}
                }
            }
        }
        with pytest.raises(FeatureManifestError, match="no identity"):
            _group([definition], adoption).adopted("mxo-ci")

    def test_a_setting_typo_fails_even_when_its_value_is_null(self) -> None:
        definition = _definition(
            parameters={"model": {"type": "string", "default": None}},
            operations={"settings": {"lms": {"NOT_A_REAL_SETTING": "${model}"}}},
        )
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        with pytest.raises(FeatureManifestError, match="NOT_A_REAL_SETTING"):
            group.resolve("mxo-ci")


class TestPrFeedback:
    """Regressions for review comments on mitodl/lehrer#419."""

    def test_one_feature_cannot_write_two_values_to_one_setting(self) -> None:
        definition = _definition(
            operations={
                "features": {"lms": {"LOG_DIR": "/a"}},
                "settings": {"lms": {"LOG_DIR": "/b"}},
            }
        )
        with pytest.raises(FeatureManifestError, match="LOG_DIR"):
            _group([definition], {"mxo-ci": {"thing": {}}}).resolve("mxo-ci")

    def test_operations_is_not_a_parameter(self) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            FeatureDefinition.model_validate(
                _definition(parameters={"operations": {"type": "string"}})
            )

    def test_an_override_replaces_a_lookup_whole(self) -> None:
        definition = _definition(
            parameters=MODE,
            operations={
                "site_config": {
                    "mfe_config": {
                        "by_parameter": "mode",
                        "cases": {"a": {"CHAT": 1}, "b": {"CHAT": 2}},
                    }
                }
            },
        )
        adoption = {
            "mxo-ci": {
                "thing": {"operations": {"site_config": {"mfe_config": {"CHAT": 3}}}}
            }
        }
        thing = _feature(_group([definition], adoption), "mxo-ci", "thing")
        assert thing.site_config == {"MFE_CONFIG": {"CHAT": 3}}

    def test_an_override_cannot_carry_two_differing_entries(self) -> None:
        definition = _definition(
            operations={"bootstrap": {"waffle_flags": [{"name": "x.y"}]}}
        )
        override = {
            "bootstrap": {
                "waffle_flags": [
                    {"name": "x.y", "everyone": True},
                    {"name": "x.y", "everyone": False},
                ]
            }
        }
        adoption = {"mxo-ci": {"thing": {"operations": override}}}
        with pytest.raises(FeatureManifestError, match="two entries for 'x.y' differ"):
            _group([definition], adoption).adopted("mxo-ci")

    def test_an_override_cannot_build_an_unrequired_mfe(self) -> None:
        adoption = {
            "mxo-ci": {
                "ai-drawer": {"operations": {"mfe_build_env": {"authn": {"X": "1"}}}}
            }
        }
        with pytest.raises(FeatureManifestError, match=r"builds \['authn'\]"):
            _group([AI_DRAWER], adoption).adopted("mxo-ci")

    def test_a_missing_slot_dir_fails_a_slot_file(self, tmp_path: Path) -> None:
        definition = _definition(
            frontend_paths=["legacy"],
            requires={"frontends": ["learning"]},
            operations={"mfe_assets": {"learning": {"extra_slot_files": ["New.jsx"]}}},
        )
        group = _group([definition], {"mxo-ci": {"thing": {}}})
        group.slot_dir = tmp_path / "absent"
        with pytest.raises(FeatureManifestError, match="directory does not exist"):
            group.resolve("mxo-ci")

    def test_settings_features_competes_with_a_features_key(self) -> None:
        group = _group(
            [
                _definition(
                    feature="a",
                    operations={"settings": {"lms": {"FEATURES": {"ENABLE_X": False}}}},
                ),
                _definition(
                    feature="b", operations={"features": {"lms": {"ENABLE_X": True}}}
                ),
            ],
            {"mxo-ci": {"a": {}, "b": {}}},
        )
        with pytest.raises(FeatureManifestError, match="FEATURES ENABLE_X"):
            group.resolve("mxo-ci")

    def test_build_digest_ignores_which_feature_sent_an_input(self) -> None:
        twin = {**AI_DRAWER, "feature": "twin"}
        scopes = {
            "version": 1,
            "scopes": {
                name: {
                    "cell": {"release": "master", "deployment": "mitxonline"},
                    "frontends": {"learning": {"legacy": "shared"}},
                }
                for name in ("one", "two")
            },
        }
        group = _group(
            [AI_DRAWER, twin],
            {"one": {"ai-drawer": {}}, "two": {"ai-drawer": {}, "twin": {}}},
            scopes,
        )
        assert group.check() == []
