# Lehrer – Copilot Instructions

## What This Is

A [Dagger](https://dagger.io/) Python module that builds and publishes Open edX platform images (edx-platform, codejail, edx-notes, MFEs) for MIT ODL deployments. It replaces an Earthly-based build pipeline.

All logic lives in a single file: `src/lehrer/main.py`.

## Local Dev Setup

```bash
uv sync                  # install deps (uses local editable sdk/ as dagger-io)
dagger functions         # list all available module functions
dagger call build-platform --help
```

The `sdk/` directory is a local editable install of the Dagger Python SDK — do not treat it as application code.

## Running the Module

```bash
# Run a single build step
dagger call apt-base --python-version 3.11 stdout

# Full platform build
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name sumac \
  --pip-package-lists ./pip_package_lists \
  --pip-package-overrides ./pip_package_overrides \
  --custom-settings ./settings \
  --edx-platform-git-branch open-release/sumac.master \
  --theme-git-repo https://github.com/mitodl/mitxonline-theme \
  --theme-git-branch main
```

There are no automated tests in this repository.

## Architecture

The `Lehrer` class (`@object_type`) contains one `@function`-decorated method per build step. Each step takes a `dagger.Container` and returns a modified one. `build_platform` chains them all together.

Pipeline stages (in order):
1. `apt_base` → base Python + system deps + uv binary
2. `locales` → openedx-i18n locale files at `/openedx/locale`
3. `get_code` → edx-platform source at `/openedx/edx-platform` + venv creation
4. `install_deps` → Python (uv) + Node.js (nodeenv) deps
5. `themes` → theme files at `/openedx/themes/{deployment_name}`
6. `collected` → assembles dockerize, tutor bin, custom settings, creates `app` user
7. `fetch_translations` → atlas pull + compilemessages
8. `build_static_assets` → sass compile, collectstatic, webpack
9. `docker_image` → bytecode compile, SSH config, finalize

Additional top-level functions: `build_codejail`, `build_notes`, `build_mfe`, `watch_mfe`, `publish_platform`.

## Key Conventions

**Function naming**: Python `snake_case` methods become `kebab-case` CLI commands automatically. `build_platform` → `dagger call build-platform`.

**`async def` vs `def`**: Functions that do I/O or return values (publish, build_*, watch_*) are `async`. Pure container-builder steps that chain operations are synchronous.

**`dag.current_module().source().directory(...)`**: Used in `build_codejail`, `build_notes`, and `build_mfe` to reference bundled config directories from within the module at runtime. This is the pattern for optional directory parameters that default to a repo-local path.

**Config directories bundled in repo**:
- `codejail_config/` — `01-sandbox` sudoers file for codejail
- `notes_config/` — `env_config.py` settings for edx-notes
- `mfe_slot_config/` — JSX slot configs and SCSS; per-deployment subdirs (`mitx/`, `mitxonline/`, `mitx-staging/`, `xpro/`) each contain `common-mfe-config.env.jsx`

**pip_package_lists/** and **pip_package_overrides/**: Organized as `{release_name}/{deployment_name}.txt`. Releases: `master`, `teak`, `ulmo` (older: `sumac`, `redwood`). Deployments: `mitx`, `mitxonline`, `mitx-staging`.

**Python version logic**: `3.12` for `release_name == "master"`, `3.11` for all other releases. Applies to `build_platform`, `build_codejail`, and is a fixed `3.11` default for `build_notes`.

**MFE config file resolution**:
- Learning MFE: uses `learning-mfe-config.env.jsx` + `{deployment}/common-mfe-config.env.jsx`
- All other MFEs: uses `{deployment}/common-mfe-config.env.jsx` as `env.config.jsx`

**lxml/xmlsec override pattern**: `install_deps` uses `uv pip install` for most packages, then switches to plain `pip install --no-cache-dir` for the override file because it contains `--no-binary` flags that need special handling.

**settings/ directory**: Passed as `custom_settings` to `build_platform`. Contains `lms.env.yml`, `cms.env.yml`, and `lms/`/`cms/` subdirectories with `assets.py` and `i18n.py` settings modules (placed at `lms/envs/mitol/` and `cms/envs/mitol/` in the container).
