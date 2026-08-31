# Lehrer – Copilot Instructions

## What This Is

A [Dagger](https://dagger.io/) Python module that builds and publishes Open edX
platform images (edx-platform, codejail, edx-notes, MFEs) for MIT ODL
deployments, plus a [cyclopts](https://cyclopts.readthedocs.io/) CLI (`lehrer`)
that drives those builds and a local k3d dev environment.

## Repository layout

```
src/lehrer/
├── main.py                 # Dagger entry point: the thin `Lehrer` root type
├── core/                   # the build pipelines — one module per service
│   ├── platform.py         # OpenedxPlatform  — edx-platform LMS/CMS
│   ├── mfe.py              # OpenedxMfe       — legacy + OEP-65 MFEs
│   ├── codejail.py         # OpenedxCodejail
│   ├── notes.py            # OpenedxNotes
│   ├── build_manifest.py   # build_manifest.yaml pydantic models
│   ├── mfe_config.py       # build_config.yaml pydantic models
│   ├── plugin_imports.py   # plugin import verification
│   ├── plugin_tests.py     # plugin test discovery
│   ├── pip_compile_bridge.py
│   └── junit_report.py
├── cli/                    # the `lehrer` CLI
│   ├── __init__.py         # root app; mounts dev / build / compat
│   ├── local_dev.py        # `lehrer dev`    — k3d + Tilt environment
│   ├── build.py            # `lehrer build`  — facade over `dagger call`
│   └── compat.py           # `lehrer compat` — plugin-compat CI matrix cells
├── settings/base.py        # ProductionSettingsMixin injected into built images
└── infra/                  # planned Pulumi components — stub, see DESIGN.md

deployments/<group>/        # operator config; NOT part of the generic pipelines
├── build_manifest.yaml
├── settings/
├── mfe_slot_config/{legacy,frontend}/
├── codejail_config/
└── notes_config/

local-dev/                  # k3d cluster, Tiltfile, helm values, manifests
tests/                      # pytest suite for cli/ and core/
plans/                      # design plans and follow-ups
```

`src/` is the Dagger module source root — the generated SDK lands at `src/sdk`
and is gitignored. Never edit or reference it as application code.

## Local Dev Setup

```bash
uv sync                                # install the CLI + deps into .venv
uv run lehrer --help                   # command tree
uv run lehrer build functions          # list every Dagger function
uv run pytest                          # run the test suite
```

## Running builds

Prefer the CLI over raw `dagger call`; it resolves the build manifest from a
`<group>/<release>/<deployment>` **cell** coordinate:

```bash
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings
```

The equivalent raw form, with every flag the cell would have supplied:

```bash
dagger call platform build-platform \
  --build-manifest ./deployments/mit-ol/build_manifest.yaml \
  --release-name master \
  --deployment-name mitxonline \
  --custom-settings ./deployments/mit-ol/settings
```

Any trailing arguments to a `lehrer build` command are forwarded to Dagger, and
`lehrer build call ...` is a raw passthrough for functions with no wrapper.

## Architecture

Every Dagger function is namespaced under a service object returned by a
`Lehrer` method — `platform`, `mfe`, `codejail`, `notes` — so the CLI path is
`dagger call <object> <function>`. Within `OpenedxPlatform`, most stages take a
`dagger.Container` and return a modified one; `build_platform` chains them.

`build_platform` is a two-base build, the way a multi-stage Dockerfile would be:

1. Build dependencies on one base: `apt_base` → `get_code` → `install_deps`.
2. Start a **fresh** `apt_base` and copy only the needed directories across.
3. Conditionally apply `locales` (unless `--include-locales false`) and `themes`.
4. `collected` → `fetch_translations` → `build_static_assets` →
   `inject_aqueduct_settings` → `docker_image`.
5. Unless `--verify-boot false`, run Django's system checks for LMS and CMS
   against the finished image.

`tutor_utils` and `dockerize` supply inputs to `collected` rather than being
pipeline stages themselves.

Beyond the stages, `OpenedxPlatform` exposes `check_deployment`,
`verify_settings`, `test`, `test_report`, `publish_platform`, and
`regenerate_aqueduct_settings`.

## Key Conventions

**Function naming**: Python `snake_case` methods become `kebab-case` CLI
commands automatically. `build_platform` → `dagger call platform build-platform`.

**`async def` vs `def`**: Functions that do I/O or return values (publish,
`build_*`, `watch_*`) are `async`. Pure container-builder steps that chain
operations are synchronous.

**No implicit operator config.** The generic pipelines never fall back to MIT
OL's directories. `slot_config`, `codejail_config`, and `notes_config` are all
required and raise a `ValueError` naming the flag when omitted. Anything
operator-specific belongs under `deployments/<group>/`, not in `lehrer.core`.

This is enforced, not just conventional: the `lehrer-core-boundary` pre-commit
hook fails on `deployments`, `mitol`, `mitxonline`, `mitodl`, `github.mit.edu`,
`verificient` or `proctortrack` appearing anywhere under `src/lehrer/core/` or
`src/lehrer/infra/` — docstrings, comments and Markdown included. Write
examples in those modules with placeholder names.

**`build_manifest.yaml`**: Per-deployment-group declarative source of truth
(e.g. `deployments/mit-ol/build_manifest.yaml`) — one cell per
`(release, deployment)` pair, each with its own `packages`/`overrides` pip
requirement lines, platform/theme/translations repo+branch, and python/node
version. Passed via `--build-manifest`; see `src/lehrer/core/build_manifest.py`.

**Python version logic**: `3.12` for `release_name == "master"`, `3.11` for all
other releases. Applies to `platform.build_platform` and `codejail.build`;
`notes.build` takes a fixed `3.11` default.

**MFE config file resolution**:
- Learning MFE: `learning-mfe-config.env.jsx` + `{deployment}/common-mfe-config.env.jsx`
- All other MFEs: `{deployment}/common-mfe-config.env.jsx` as `env.config.jsx`

Per-MFE customizations (extra slot files, styles, npm bundles) are better
declared once in a `build_config.yaml` beside the slot config and applied with
`mfe build-legacy-configured`; the schema is generated from
`src/lehrer/core/mfe_config.py` and committed as `build_config.schema.json`.

**lxml/xmlsec override pattern**: `install_deps` uses `uv pip install` for most
packages, then switches to plain `pip install --no-cache-dir` for the override
file because it contains `--no-binary` flags that need special handling.

**`custom_settings` directory**: Passed to `build_platform`. Supplies
`lms.env.yml`, `cms.env.yml`, `{lms,cms}/assets.py`, `{lms,cms}/i18n.py`,
`{lms,cms}/aqueduct.py`, `{lms,cms}/models/aqueduct.py`, and the three operator
scripts (`set_waffle_flags.py`, `process_scheduled_emails.py`, `saml_pull.py`).
`models/base.py` is **not** operator-supplied — `inject_aqueduct_settings`
injects it from `src/lehrer/settings/base.py`. Full contract in
`docs/creating-a-deployment.md`.

## Tests and CI

`tests/` holds a pytest suite covering `cli/` and `core/`. `ci.yml` runs, on
every push and pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file=pyproject.toml src/lehrer tests
uv run pytest tests/ -v
uv run pre-commit run build-config-schema --all-files
uv run pre-commit run build-manifest-schema --all-files
uv run pre-commit run lehrer-core-boundary --all-files
```

The remaining workflows need a Dagger engine or a schedule:
`settings-verify.yml` boots each cell's committed aqueduct settings,
`plugin-compat.yml` installs and imports each cell's pinned requirements
(`lehrer compat` picks the affected cells for a PR), `canary.yml` runs full
platform builds on a schedule, and `actions-static-analysis.yml` lints the
workflows with zizmor.
