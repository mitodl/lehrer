# OL-Specific Assumptions in `src/lehrer/main.py`

Reference table produced as part of the structural refactor (plan 01). Every string in
`src/lehrer/main.py` that contains `mitol`, `mitxonline`, `mitodl`, `github.mit.edu`,
`verificient`, or `proctortrack` — plus every value derived from the `settings_namespace`
concept — is catalogued here. This table is the API contract for Tasks 6–8.

## Hardcoded values

| Location | Function + line | Hardcoded value | Parameter name | Type | OL default |
|---|---|---|---|---|---|
| `install_deps` | ~265 | `if deployment_name == "mitxonline": uv pip uninstall edx-name-affirmation` | `packages_to_remove` | `list[str]` | `["edx-name-affirmation"]` (mitxonline only) |
| `install_deps` | ~316 | `npm install 'git+https://git@github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732'` | `extra_npm_packages` | `list[str]` | `["git+https://git@github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732"]` |
| `collected` | ~442–444 | `mkdir -p ./lms/envs/mitol ./cms/envs/mitol` | `settings_namespace` | `str` | `"mitol"` |
| `collected` | ~471 | `cp … lms/envs/mitol/assets.py` | derived from `settings_namespace` | — | — |
| `collected` | ~478 | `cp … lms/envs/mitol/i18n.py` | derived from `settings_namespace` | — | — |
| `collected` | ~485 | `cp … cms/envs/mitol/assets.py` | derived from `settings_namespace` | — | — |
| `collected` | ~492 | `cp … cms/envs/mitol/i18n.py` | derived from `settings_namespace` | — | — |
| `fetch_translations` | ~579 | `translations_repository = "mitodl/mitxonline-translations"` (default) | `translations_repository` | `str` | required — no default after refactor |
| `fetch_translations` | ~598 | `DJANGO_SETTINGS_MODULE = lms.envs.mitol.i18n` | derived from `settings_namespace` | — | — |
| `fetch_translations` | ~636 | `DJANGO_SETTINGS_MODULE = cms.envs.mitol.i18n` | derived from `settings_namespace` | — | — |
| `build_static_assets` | ~700 | `--settings=mitol.assets` (×4 collectstatic calls) | derived from `settings_namespace` | — | — |
| `docker_image` | ~788 | `ssh-keyscan 'github.com' 'github.mit.edu'` | `extra_ssh_hosts` | `list[str]` | `["github.mit.edu"]` |
| `build_platform` | ~817 | `translations_repo = "mitodl/mitxonline-translations"` (default) | `translations_repo` | `str` | `"openedx/openedx-translations"` after refactor |
| `build_mfe` / `build_legacy` | ~1380–1381 | `npm pack @mitodl/smoot-design@^6.12.0` + extract + copy to `public/static/smoot-design/` | `extra_npm_bundles` | `list[str]` (`"pkg_spec\|target_path"` format) | `["@mitodl/smoot-design@^6.12.0\|public/static/smoot-design"]` (learning MFE only) |
| `regenerate_aqueduct_settings` | ~1589 | `if deployment_name == "mitxonline": uv pip uninstall edx-name-affirmation` | `packages_to_remove` | `list[str]` | `["edx-name-affirmation"]` (mitxonline only) |

## Derived string substitutions driven by `settings_namespace`

All four of the following occur in three functions:

| Function | String substitution pattern | Example (OL value `"mitol"`) |
|---|---|---|
| `collected` | `./lms/envs/{settings_namespace}` (mkdir) | `./lms/envs/mitol` |
| `collected` | `./cms/envs/{settings_namespace}` (mkdir) | `./cms/envs/mitol` |
| `collected` | `/openedx/edx-platform/{lms,cms}/envs/{settings_namespace}/{assets,i18n}.py` (cp targets) | `…/mitol/assets.py`, `…/mitol/i18n.py` |
| `fetch_translations` | `{lms,cms}.envs.{settings_namespace}.i18n` (DJANGO_SETTINGS_MODULE) | `lms.envs.mitol.i18n` |
| `build_static_assets` | `--settings={settings_namespace}.assets` (×4 collectstatic) | `--settings=mitol.assets` |

## Default path references (moved in Task 2)

These `dag.current_module().source().directory(...)` calls reference paths that move
under `deployments/mit-ol/` during the directory skeleton task:

| Function | Old default path | New default path |
|---|---|---|
| `build_codejail` | `"codejail_config"` | `"deployments/mit-ol/codejail_config"` |
| `build_notes` | `"notes_config"` | `"deployments/mit-ol/notes_config"` |
| `build_mfe` / `watch_mfe` | `"mfe_slot_config"` | `"deployments/mit-ol/mfe_slot_config/legacy"` |
