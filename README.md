# Lehrer - OpenEdx Platform Build Pipeline

A Dagger module for building and deploying Open edX platform images, services, and micro-frontends.

## Overview

This module provides:

- **Composable functions** - Build steps can be used independently or chained together
- **Flexibility** - Support for multiple deployments with different configurations
- **Multiple services** - Build platform, codejail, edx-notes, and MFEs
- **Local development** - Watch containers for testing MFE slot configs
- **Reproducibility** - Consistent builds across environments
- **Efficiency** - Leverages Dagger's caching and parallelization

## The `lehrer` CLI

`lehrer` is the single entrypoint for working in this repository. It is a
[cyclopts](https://cyclopts.readthedocs.io/) CLI that is intended to grow to
cover every routine task — today it manages the local k3d dev environment and
drives the Dagger build pipelines.

```bash
uv sync            # install the CLI into the project venv
uv run lehrer --help
```

Top-level command groups:

| Command | Purpose |
|---|---|
| `lehrer dev`   | Manage the local k3d Open edX dev environment |
| `lehrer build` | Run the Dagger build pipelines |

### Local development

The local dev environment runs on [k3d](https://k3d.io) + [Tilt](https://tilt.dev).
The cluster lifecycle is:

```bash
lehrer dev check       # verify required tools (k3d, kubectl, tilt, helm, dagger, docker)
lehrer dev setup       # create the k3d cluster + bootstrap secrets (run once)
lehrer dev start       # tilt up — build & deploy the services
lehrer dev stop        # tilt down — remove deployed resources, keep the cluster
lehrer dev teardown    # delete the cluster and clean up all local state
lehrer dev status      # show cluster / pod state
```

Use a deployment-specific config and MFE hot-reload:

```bash
lehrer dev start --deployment-config ./deployments/mit-ol --mfe-hot-reload
```

Secret values are read from the environment (`MYSQL_ROOT_PASSWORD`,
`DJANGO_SECRET_KEY`, `MONGO_PASSWORD`, ...) and fall back to safe local-dev
defaults.

### Builds

`lehrer build` is a thin, consistent facade over the Dagger module — it saves
you from remembering the object-scoped `dagger call` paths, and any trailing
arguments are forwarded straight to Dagger. `lehrer build --help` groups the
commands the way you reason about them:

| Command | Wraps | Purpose |
|---|---|---|
| `lehrer build platform`      | `platform build-platform`   | Build the edx-platform LMS/CMS image |
| `lehrer build codejail`      | `codejail build`            | Build the codejail service image |
| `lehrer build notes`         | `notes build`               | Build the edx-notes-api image |
| `lehrer build mfe-legacy`    | `mfe build-legacy`          | Build a legacy (webpack) MFE `dist/` |
| `lehrer build mfe-site`      | `mfe build-site`            | Build an OEP-65 Site Project |
| `lehrer build check`         | `platform check-deployment` | Verify a cell's requirements install + import |
| `lehrer build verify-settings` | `platform verify-settings` | Boot a cell's committed aqueduct settings + Django system checks |
| `lehrer build test`          | `platform test`             | Run edx-platform + installed plugin tests in a built image |
| `lehrer build test-report`   | `platform test-report`      | The same run, returning an exportable JUnit + per-plugin summary |
| `lehrer build codejail-test` | `codejail test`             | Run the codejail test suite |
| `lehrer build notes-test`    | `notes test`                | Run the edx-notes-api test suite |
| `lehrer build cells`         | —                           | Print the `(release, deployment)` cells in a manifest |
| `lehrer build functions`     | `dagger functions`          | List every Dagger function |
| `lehrer build call ...`      | `dagger call ...`           | Raw passthrough for any function without a wrapper |

The cell-scoped commands (`platform`, `check`, `test`) accept a single
`<group>/<release>/<deployment>` **cell** that expands to `--build-manifest
deployments/<group>/build_manifest.yaml --release-name <release>
--deployment-name <deployment>`, so you don't repeat them:

```bash
uv sync                                          # install the CLI into the venv

# Build the edx-platform image for a cell (the manifest supplies the rest):
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings

# Verify a cell (cheap → thorough):
uv run lehrer build check --cell mit-ol/master/mitxonline
uv run lehrer build test  --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings

# Other services and MFEs:
uv run lehrer build codejail --release-name master
uv run lehrer build mfe-legacy --mfe-name learning ... export --path ./dist

# Raw escape hatch for anything without a wrapper (e.g. publish, watch-site):
uv run lehrer build call mfe watch-site ...
```

The rest of this README documents the underlying Dagger functions directly;
each common one has a `lehrer build` shortcut per the table above.

## Architecture

The build pipeline follows these stages:

1. **apt-base** - Base Python container with system dependencies and uv
2. **locales** - Download OpenEdx i18n locale files
3. **get-code** - Get edx-platform source (local or Git)
4. **install-deps** - Install Python and Node.js dependencies using uv
5. **themes** - Get theme files (local or Git)
6. **tutor-utils** - Get utility scripts from Tutor
7. **collected** - Assemble artifacts and configure container
8. **fetch-translations** - Pull and compile translations
9. **build-static-assets** - Build and collect static assets
10. **docker-image** - Finalize for deployment
11. **publish-platform** - Publish to container registry

### Key Optimizations

- **uv for Python dependencies** - Uses Astral's uv instead of pip for significantly faster dependency resolution and installation
- **Bytecode compilation** - Pre-compiles Python bytecode during dependency installation for faster startup
- **Docker caching** - Leverages Dagger's caching for efficient rebuilds

## Functions

Every Dagger function is namespaced under a service object — `platform`, `mfe`,
`codejail`, or `notes`. Run `lehrer build functions` (or `dagger functions`) to
list them, and `dagger call <object> <function> --help` for a function's flags.

### `platform` — edx-platform

`build-platform` assembles the whole image the way a multi-stage Docker build
would: it first builds dependencies on one base (`apt-base` → `get-code` →
`install-deps`), then starts a **fresh** clean base and copies only the needed
directories across, conditionally applies `locales` (unless
`--include-locales false`) and `themes`, and finishes with `collected` →
`inject-aqueduct-settings` → `fetch-translations` → `build-static-assets` →
`docker-image`, then verifies the finished image can actually start by running
Django's system checks for both services (`--verify-boot false` to skip while
iterating). The other functions are those individual stages, plus
`check-deployment` / `verify-settings` / `test` (verification),
`publish-platform`, and `regenerate-aqueduct-settings`.

The simplest way to drive a full build is a **cell** — the deployment's
`build_manifest.yaml` supplies the platform/theme/translation repos, Python and
Node versions, and requirement pins, so you pass only the cell coordinate and
the settings directory:

```bash
# Recommended: the lehrer CLI resolves the manifest for you.
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings

# The same thing as a raw dagger call:
dagger call platform build-platform \
  --build-manifest ./deployments/mit-ol/build_manifest.yaml \
  --release-name master \
  --deployment-name mitxonline \
  --custom-settings ./deployments/mit-ol/settings
```

Without a manifest, pass the build parameters explicitly:

```bash
dagger call platform build-platform \
  --deployment-name mitxonline \
  --release-name master \
  --pip-package-lists ./pip_package_lists \
  --pip-package-overrides ./pip_package_overrides \
  --custom-settings ./settings \
  --platform-repo "https://github.com/openedx/edx-platform" \
  --platform-branch master \
  --theme-repo "https://github.com/mitodl/mitxonline-theme" \
  --theme-branch main \
  --python-version 3.12
```

`build-platform` returns a `Container`; chain `publish-platform` to push it
(there is no dedicated CLI wrapper — use `lehrer build call` or a raw
`dagger call`):

```bash
dagger call platform build-platform \
  --build-manifest ./deployments/mit-ol/build_manifest.yaml \
  --release-name master --deployment-name mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  publish-platform \
  --registry ghcr.io \
  --repository mitodl/openedx-mitxonline \
  --tag master-latest \
  --username "$GITHUB_USER" \
  --password env:GITHUB_TOKEN
```

## Required Inputs

### Directory Structures

#### `pip_package_lists/`
Contains pip requirements files organized by release and deployment:

```
pip_package_lists/
├── sumac/
│   ├── mitx.txt
│   └── mitxonline.txt
└── redwood/
    ├── mitx.txt
    └── mitxonline.txt
```

#### `pip_package_overrides/`
Contains pip override requirements (e.g., for lxml/xmlsec fixes):

```
pip_package_overrides/
├── sumac/
│   ├── mitx.txt
│   └── mitxonline.txt
└── redwood/
    ├── mitx.txt
    └── mitxonline.txt
```

#### `custom_settings/`
Contains custom Django settings and configuration files:

```
custom_settings/
├── lms.env.yml
├── cms.env.yml
├── lms/
│   ├── assets.py
│   └── i18n.py
├── cms/
│   ├── assets.py
│   └── i18n.py
├── lms_settings.py
├── cms_settings.py
├── models.py
├── utils.py
├── set_waffle_flags.py
├── process_scheduled_emails.py
└── saml_pull.py
```

## Examples

The examples below show the `lehrer build` form; the equivalent raw
`dagger call platform build-platform ...` accepts the same flags.

### Build for Multiple Deployments

```bash
# Build mitxonline
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings

# Build mitx
uv run lehrer build platform --cell mit-ol/master/mitx \
  --custom-settings ./deployments/mit-ol/settings
```

### Use Local Source for Development

Any extra flags after the `--cell` are forwarded to `build-platform`:

```bash
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  --source ../edx-platform \
  --theme-source ../mitxonline-theme
```

### Build Without Locales

```bash
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  --include-locales false
```

### Python Version Selection

By default:
- **master branch**: Uses Python 3.12
- **Other releases (sumac, redwood, etc.)**: Use Python 3.11

The manifest cell can pin `python_version`; override it per-invocation with
`--python-version`:

```bash
uv run lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  --python-version 3.11
```

### Building the Codejail Service

The codejail service provides sandboxed Python execution for running student code:

```bash
uv run lehrer build codejail --release-name master          # Python 3.12
uv run lehrer build codejail --release-name sumac           # Python 3.11
uv run lehrer build codejail --release-name master --python-version 3.11

# Raw form:
dagger call codejail build --release-name master
```

Codejail automatically installs the appropriate edx-platform sandbox requirements based on the release.

### Building the edx-notes Service

The edx-notes-api service provides student annotation functionality:

```bash
uv run lehrer build notes --release-name master
uv run lehrer build notes --release-name open-release/sumac.master
uv run lehrer build notes --release-name master --python-version 3.9

# Raw form:
dagger call notes build --release-name master
```

**Note**: edx-notes-api master branch requires Python 3.9+. Older releases may work with Python 3.8.

### Publishing Service Images

The codejail and notes builds return a `Container`; chain `publish` to push it.
There is no dedicated CLI wrapper for the chain, so use `lehrer build call` (or
a raw `dagger call`):

```bash
# Build and publish codejail
uv run lehrer build call codejail build --release-name sumac \
  publish --address ghcr.io/mitodl/openedx-codejail:sumac

# Build and publish notes
uv run lehrer build call notes build --release-name master \
  publish --address ghcr.io/mitodl/openedx-notes:latest
```

## Building Micro-Frontends (MFEs)

The module provides functions for building Open edX Micro-Frontends with deployment-specific configurations.

### MFE Build Features

- Build any Open edX MFE from source
- Support for slot configuration files (Footer.jsx, env.config.jsx, etc.)
- Deployment-specific styling (mitx-styles.scss, mitxonline-styles.scss)
- Learning MFE special handling (smoot-design, AI drawer components)
- Translation support via openedx-atlas
- Local development with watch container

### Basic MFE Build

`lehrer build mfe-legacy` wraps `mfe build-legacy`. `--slot-config` (the
operator's slot-configuration directory) is **required**, and `export --path
./dist` writes the built bundle out:

```bash
# Build the learning MFE
uv run lehrer build mfe-legacy \
  --mfe-name learning \
  --mfe-repo https://github.com/openedx/frontend-app-learning \
  --mfe-branch open-release/sumac.latest \
  --deployment-name mitxonline \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy \
  export --path ./dist

# Build with custom styles + an extra npm bundle. Bundle specs are
# "npm_package_spec|target_directory":
uv run lehrer build mfe-legacy \
  --mfe-name learning \
  --mfe-repo https://github.com/openedx/frontend-app-learning \
  --mfe-branch master \
  --deployment-name mitxonline \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy \
  --styles-file mitxonline-styles.scss \
  --extra-npm-bundles "@mitodl/smoot-design|public/static/smoot-design" \
  export --path ./dist

# Raw form:
dagger call mfe build-legacy --mfe-name account \
  --mfe-repo https://github.com/openedx/frontend-app-account \
  --deployment-name mitxonline \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy \
  export --path ./dist
```

Learning-MFE customizations (AI drawer slots, smoot-design, extra bundles) are
best captured once in a `build_config.yaml` and applied with
`build-legacy-configured` — see [Config-driven legacy
builds](#config-driven-legacy-builds-build-legacy-configured) below.

### MFE Environment Variables

MFEs bake configuration in at build time. Pass each variable with a repeatable
`--env-vars KEY=VALUE` flag:

```bash
uv run lehrer build mfe-legacy \
  --mfe-name learning \
  --mfe-repo https://github.com/openedx/frontend-app-learning \
  --deployment-name mitxonline \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy \
  --env-vars LMS_BASE_URL=https://courses.learn.mit.edu \
  --env-vars SITE_NAME="MIT Learn" \
  --env-vars APP_ID=learning \
  export --path ./dist
```

Common variables include `LMS_BASE_URL`, `SITE_NAME`, `BASE_URL`, `APP_ID`, and
`DEPLOYMENT_NAME`. See the Concourse pipeline `values.py` for the full set a
production build supplies.

### Local MFE development (hot reload)

For iterating on slot configs without rebuilding, run the local dev environment
with MFE hot-reload:

```bash
uv run lehrer dev start --deployment-config ./deployments/mit-ol --mfe-hot-reload
```

For an OEP-65 Site Project specifically, `mfe watch-site` serves a built Site
Project with hot reload:

```bash
uv run lehrer build call mfe watch-site \
  --site-project ./site-project up --ports 8080:8080
# Access at http://localhost:8080
```

### Slot Configuration Files

The `mfe_slot_config` directory contains:

- `Footer.jsx` - Custom footer component (all MFEs)
- `learning-mfe-config.env.jsx` - Learning MFE config
- `{deployment}/common-mfe-config.env.jsx` - Common config per deployment
- `AIDrawerManagerSidebar.jsx` - AI drawer sidebar (learning MFE)
- `SidebarAIDrawerCoordinator.jsx` - AI drawer coordinator (learning MFE)
- `mitx-styles.scss` - MITx Residential styles
- `mitxonline-styles.scss` - MITx Online styles

These files are copied into the MFE build to customize behavior per deployment.

### Config-driven legacy builds (`build-legacy-configured`)

Rather than passing `--extra-slot-files`, `--styles-file`, and
`--extra-npm-bundles` on every invocation, an operator can describe their
customizations once in a `build_config.yaml` that lives alongside the slot
configuration. `build-legacy-configured` reads it and resolves the explicit
`build-legacy` arguments per deployment and Open edX release:

```bash
dagger call mfe build-legacy-configured \
  --mfe-name learning \
  --slot-config ./mfe_slot_config/legacy \
  --mfe-source ./frontend-app-learning \
  --deployment-name mitxonline \
  --release-name master \
  export --path ./dist
```

The config structure is defined by the Pydantic models in
`src/lehrer/core/mfe_config.py`, which are both the runtime validation layer
(a malformed file fails fast with field-level errors) and the source of a
publishable JSON Schema.

### Validating `build_config.yaml`

Generate the JSON Schema for editor or agentic validation:

```bash
dagger call mfe build-config-schema > build_config.schema.json
```

A copy generated from the models is committed at the repo root as
`build_config.schema.json` (kept in sync by a pre-commit hook). Reference it
from the top of a `build_config.yaml` so editors validate as you type:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/mitodl/lehrer/main/build_config.schema.json
```

## Composing individual build steps

All build parameters are explicit — no implicit file copying from a build context.
Use directory/file mounting for local sources:

- Pass `--source` for a local edx-platform checkout
- Pass `--theme-source` for a local theme directory
- Pass `--pip-package-lists`, `--pip-package-overrides`, `--custom-settings` as directories

Use `lehrer build platform` (or `dagger call platform build-platform`) for a
complete end-to-end build. The individual `platform` functions are the
pipeline's stages: `apt-base` takes a `--python-version` and *creates* the
initial container, while the later stages (`get-code`, `install-deps`,
`locales`, `themes`, `collected`, ...) each take a container and return the next
one. `build-platform` is where they are wired together in
`src/lehrer/core/platform.py`.

### GitHub Actions Example

This repo's own CI drives the CLI (`uv run lehrer build ...`) — see
`.github/workflows/`. To publish an image from a workflow you can also call the
Dagger module directly:

```yaml
name: Build OpenEdx Image
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build and publish
        uses: dagger/dagger-for-github@v5
        with:
          version: "latest"
          verb: call
          args: |
            platform build-platform
            --build-manifest ./deployments/mit-ol/build_manifest.yaml
            --release-name master
            --deployment-name mitxonline
            --custom-settings ./deployments/mit-ol/settings
            publish-platform
            --registry ghcr.io
            --repository mitodl/openedx-mitxonline
            --tag ${{ github.sha }}
            --username ${{ github.actor }}
            --password env:GITHUB_TOKEN
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Development

### Running Locally

```bash
# Install the CLI + dependencies
uv sync

# List available functions
uv run lehrer build functions          # or: dagger functions

# Get help on a command or the underlying function
uv run lehrer build platform --help
dagger call platform build-platform --help

# Evaluate a single build stage
dagger call platform apt-base stdout
```

### Adding New Functions

1. Add function to `src/lehrer/main.py`
2. Follow naming convention (snake_case becomes kebab-case in CLI)
3. Add docstrings with Args and Returns sections
4. Update this README with examples

## License

BSD-3-Clause
