# Creating a Lehrer Deployment

This guide explains how to use lehrer to build Open edX service images for
your own deployment.  Lehrer is a [Dagger](https://dagger.io/) module that
provides generic, parameterizable build pipelines for Open edX services.

MIT Open Learning's own configuration lives in `deployments/mit-ol/` and
serves as a reference implementation.

## What lehrer provides

Lehrer exposes four Dagger object types, each responsible for one service:

| Sub-command | Type | Builds |
|---|---|---|
| `dagger call platform` | `OpenedxPlatform` | edx-platform (LMS + CMS) container image |
| `dagger call mfe` | `OpenedxMfe` | Open edX Micro Frontends — `build_legacy` (stable) and `build_site` / `watch_site` (OEP-65) |
| `dagger call codejail` | `OpenedxCodejail` | codejail sandboxed execution service |
| `dagger call notes` | `OpenedxNotes` | edx-notes-api annotation service |

## Recommended repository layout

```
my-deployment/
├── settings/
│   ├── lms.env.yml
│   ├── cms.env.yml
│   ├── lms/
│   │   ├── assets.py
│   │   ├── i18n.py
│   │   ├── aqueduct.py
│   │   └── models/
│   │       └── aqueduct.py
│   ├── cms/
│   │   ├── assets.py
│   │   ├── i18n.py
│   │   ├── aqueduct.py
│   │   └── models/
│   │       └── aqueduct.py
│   ├── set_waffle_flags.py
│   ├── process_scheduled_emails.py
│   └── saml_pull.py
├── build_manifest.yaml          # recommended: single source of truth for build cells
├── pip_package_lists/           # legacy alternative to build_manifest.yaml
│   └── {release_name}/
│       └── {deployment_name}.txt
├── pip_package_overrides/       # legacy alternative to build_manifest.yaml
│   └── {release_name}/
│       └── {deployment_name}.txt
├── mfe_slot_config/
│   ├── legacy/                  # webpack MFEs — see build_legacy below
│   │   ├── Footer.jsx
│   │   ├── learning-mfe-config.env.jsx
│   │   ├── build_config.yaml    # optional; drives build_legacy_configured
│   │   └── {deployment_name}/
│   │       └── common-mfe-config.env.jsx
│   └── frontend/                # OEP-65 Site Projects — see build_site below
│       └── {deployment_name}/
├── codejail_config/
│   └── 01-sandbox
└── notes_config/
    └── env_config.py
```

`settings/` contains no top-level `models/base.py`. That file is supplied by
lehrer itself (`src/lehrer/settings/base.py`) and injected by
`inject_aqueduct_settings`; see the [`custom_settings` directory
contract](#custom_settings-directory-contract) below.

---

## Platform builder parameters — `OpenedxPlatform`

### `build_platform`

The recommended way to drive `build_platform` is a declarative
`build_manifest.yaml` (see [`lehrer.core.build_manifest`](../src/lehrer/core/build_manifest.py)
and `plans/06-build-manifest.md`) — one file per deployment group naming
every `(release, deployment)` cell's repo/branch, python/node version, theme,
translations, and pip packages. Pass `--build-manifest` + `--release-name` +
`--deployment-name` (or use `lehrer build platform --cell <group>/<release>/<deployment>`)
and every parameter below is resolved from the matching cell unless you pass
it explicitly. `pip_package_lists`/`pip_package_overrides` directories remain
a supported lower-level alternative.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `deployment_name` | `str` | **required** | Deployment name used for theme path and pip package file names (e.g. `"mydeployment"`) |
| `release_name` | `str` | **required** | Open edX release name (e.g. `"master"`, `"sumac"`, `"teak"`) |
| `custom_settings` | `Directory` | **required** | Directory with settings files (see layout above) |
| `build_manifest` | `File` | `None` | `build_manifest.yaml` (see above). Materializes `pip_package_lists`/`pip_package_overrides` and supplies defaults for the fields below |
| `pip_package_lists` | `Directory` | `None` | Directory with pip requirements. Must contain `{release_name}/{deployment_name}.txt`. Required unless `build_manifest` is given |
| `pip_package_overrides` | `Directory` | `None` | Directory with pip build overrides. Must contain `{release_name}/{deployment_name}.txt`. Required unless `build_manifest` is given |
| `translations_repo` | `str` | `None` → cell, else `"openedx/openedx-translations"` | GitHub repository for translations (e.g. `"myorg/my-translations"`) |
| `source` | `Directory` | `None` | Local edx-platform source (overrides `platform_repo`/`platform_branch`) |
| `platform_repo` | `str` | `None` → cell, else `"https://github.com/openedx/edx-platform"` | Git URL for edx-platform |
| `platform_branch` | `str` | `None` → cell, else `"master"` | Git branch / tag for edx-platform |
| `theme_source` | `Directory` | `None` | Local theme source (overrides `theme_repo`/`theme_branch`) |
| `theme_repo` | `str` | `None` → cell | Git URL for theme repository |
| `theme_branch` | `str` | `None` → cell | Git branch / tag for theme |
| `python_version` | `str` | `None` → cell, else auto | Python version. Auto-detected: `3.12` for `master`, `3.11` for others |
| `node_version` | `str` | `None` → cell, else `"20.18.0"` | Node.js version |
| `locale_version` | `str` | `"master"` | openedx-i18n ref (archived repo) |
| `translations_branch` | `str` | `None` → cell, else `"main"` | Branch for translations repo |
| `include_locales` | `bool` | `True` | Include openedx-i18n locale files |
| `settings_namespace` | `str` | `None` → cell, else `"production"` | Django settings sub-package. Files go into `lms/envs/{namespace}/` and `cms/envs/{namespace}/`. MIT OL uses `"mitol"` |
| `extra_ssh_hosts` | `list[str]` | `[]` | Additional SSH hosts beyond `github.com` for `known_hosts` (e.g. `["github.mit.edu"]`) |
| `packages_to_remove` | `list[str]` | `[]` | Python packages to uninstall after base install |
| `extra_npm_packages` | `list[str]` | `[]` | Additional npm packages to install (e.g. private git packages) |
| `verify_boot` | `bool` | `True` | Run Django system checks for LMS and CMS against the finished image. Set `false` to skip while iterating |
| `strict_translations` | `bool` | `False` | Fail the build when any tolerated translation step fails, instead of warning and continuing. Covers the plugin/xblock pulls *and* compiles as well as `atlas pull` — every step `_tolerant` wraps. `compilemessages`/`compilejsi18n` are unwrapped and fail the build either way |
| `include_dev_dependencies` | `bool` | `False` | Also install the cell's development requirements (used by `test`) |

Parameters marked `None` → cell take their value from the matching
`build_manifest.yaml` cell when `--build-manifest` is passed. The fallback
after the arrow applies only when neither a cell nor an explicit flag supplies
one. Passing the flag always wins over the cell.

### `install_deps`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with edx-platform at `/openedx/edx-platform` |
| `deployment_name` | `str` | **required** | Deployment name |
| `release_name` | `str` | **required** | Release name |
| `pip_package_lists` | `Directory` | **required** | Pip requirements directory |
| `pip_package_overrides` | `Directory` | **required** | Pip overrides directory |
| `node_version` | `str` | `"20.18.0"` | Node.js version |
| `packages_to_remove` | `list[str]` | `[]` | Packages to uninstall post-install |
| `extra_npm_packages` | `list[str]` | `[]` | Extra npm packages to install |
| `install_node` | `bool` | `True` | Install Node.js via nodeenv. `False` for verification-only builds that never compile assets |
| `include_dev_dependencies` | `bool` | `False` | Also install the cell's development requirements |

### `inject_aqueduct_settings`

Runs after `build_static_assets` and installs the aqueduct settings models into
the image. `models/base.py` comes from lehrer's own
`src/lehrer/settings/base.py`; everything else comes from `custom_settings`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with static assets built |
| `custom_settings` | `Directory` | **required** | Settings directory |
| `settings_namespace` | `str` | `"production"` | Django settings sub-package name |

### `collected`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with installed deps |
| `deployment_name` | `str` | **required** | Deployment name |
| `dockerize_bin` | `File` | **required** | Dockerize binary |
| `tutor_bin` | `Directory` | **required** | Tutor bin scripts |
| `custom_settings` | `Directory` | **required** | Settings directory |
| `settings_namespace` | `str` | `"production"` | Django settings sub-package name |
| `app_user_id` | `int` | `1000` | UID for the `app` user |
| `include_locales` | `bool` | `True` | Include locale files |

### `fetch_translations`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with collected artifacts |
| `translations_repository` | `str` | **required** | Translations GitHub repository (no default — must be explicit) |
| `settings_namespace` | `str` | `"production"` | Django settings sub-package for `DJANGO_SETTINGS_MODULE` |
| `translations_branch` | `str` | `"main"` | Translations branch |
| `strict` | `bool` | `False` | Fail the build when any tolerated pull or compile step fails, instead of warning to stderr and continuing. `build_platform` drives this with `--strict-translations` |

### `build_static_assets`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with translations |
| `deployment_name` | `str` | **required** | Deployment name for theme compilation |
| `settings_namespace` | `str` | `"production"` | Django settings sub-package for `--settings=` flag |

### `docker_image`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `container` | `Container` | **required** | Container with static assets |
| `deployment_name` | `str` | **required** | Deployment name |
| `release_name` | `str` | **required** | Release name |
| `extra_ssh_hosts` | `list[str]` | `[]` | Additional SSH hosts for `known_hosts` |

### Verification and publishing

Beyond the pipeline stages, `OpenedxPlatform` exposes:

| Function | Purpose |
|---|---|
| `check_deployment` | Cheapest tier — install a cell's pinned requirements and import every plugin. Python-only (`install_node=False`), no asset build |
| `verify_settings` | Boot a cell's committed aqueduct settings and run Django's system checks. `--drift` also reports settings that have drifted from the generated model |
| `test` | Run the edx-platform and installed-plugin test suites inside a built image |
| `test_report` | The same run, returning an exportable JUnit XML plus a per-plugin summary |
| `regenerate_aqueduct_settings` | Regenerate a deployment's `{lms,cms}/models/aqueduct.py` from the platform source |
| `publish_platform` | Push a built `Container` to a registry. Chain it onto `build_platform` |

```bash
dagger call platform build-platform \
  --build-manifest ./my-deployment/build_manifest.yaml \
  --release-name master --deployment-name mydeployment \
  --custom-settings ./my-deployment/settings \
  publish-platform \
  --registry ghcr.io \
  --repository myorg/openedx-mydeployment \
  --tag master-latest \
  --username "$GITHUB_USER" \
  --password env:GITHUB_TOKEN
```

---

## MFE builder — two build models

Lehrer supports two MFE build models that coexist permanently:

| Function | Model | When to use |
|---|---|---|
| `build_legacy` | Legacy per-MFE SPA | MFEs that have not yet migrated to `@openedx/frontend-base` |
| `build_site` | OEP-65 Site Project | MFEs shipped as module libraries in `@openedx/frontend-base` |
| `watch_site` | OEP-65 dev server | Local development against a Site Project |

The legacy and OEP-65 builds are independent — switching one MFE to the Site Project
model does not affect the others. See `plans/03-frontend-base-oep65.md` for migration
guidance and `plans/04-concourse-fastly-deployment.md` for deployment infrastructure.

---

## MFE builder parameters — `OpenedxMfe.build_legacy`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mfe_name` | `str` | **required** | MFE name (e.g. `"learning"`, `"account"`) |
| `slot_config` | `Directory` | **required** | Slot config directory. There is no fallback — omitting it raises a `ValueError` naming the flag |
| `mfe_repo` | `str` | `""` | Git URL for the MFE. Required unless `mfe_source` is given |
| `mfe_source` | `Directory` | `None` | Local MFE checkout (overrides `mfe_repo`/`mfe_branch`) |
| `mfe_branch` | `str` | `"master"` | Git branch |
| `node_version` | `str` | `"20"` | Node.js version — used as the `node:{version}-trixie-slim` base image tag |
| `deployment_name` | `str` | `"default"` | Deployment name for config file selection |
| `extra_slot_files` | `list[str]` | `[]` | Additional files to copy from `slot_config` into the MFE root. Each entry is `"filename"`, or `"source:dest"` to rename on copy |
| `styles_file` | `str` | `None` | A file from `slot_config` to copy into the MFE root as the deployment's styles |
| `extra_npm_bundles` | `list[str]` | `[]` | Extra npm packages to pack as static bundles. Format: `"pkg_spec\|target_dir"` (e.g. `"@myorg/lib@^1.0\|public/static/lib"`) |
| `env_vars` | `list[str]` | `[]` | Build-time environment variables, repeatable. Format: `"KEY=VALUE"` |
| `pre_build_commands` | `list[str]` | `[]` | Shell commands run after `npm install` and before `npm run build` (e.g. an `atlas` translation pull) |

MFEs bake their configuration in at build time, so `env_vars` is how
`LMS_BASE_URL`, `SITE_NAME`, `BASE_URL`, `APP_ID` and `DEPLOYMENT_NAME` reach
the bundle.

---

## MFE builder parameters — `OpenedxMfe.build_legacy_configured`

Rather than repeating `extra_slot_files`, `styles_file` and `extra_npm_bundles`
on every invocation, declare them once in a `build_config.yaml` beside the slot
configuration. `build_legacy_configured` reads that file, resolves the explicit
`build_legacy` arguments for the given deployment and release, and runs the
build.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mfe_name` | `str` | **required** | MFE name |
| `slot_config` | `Directory` | **required** | Slot config directory, containing `config_file` |
| `mfe_repo` | `str` | `""` | Git URL for the MFE. Required unless `mfe_source` is given |
| `mfe_source` | `Directory` | `None` | Local MFE checkout |
| `deployment_name` | `str` | `"default"` | Deployment name |
| `release_name` | `str` | `""` | Open edX release, for release-scoped overrides in the config |
| `config_file` | `str` | `"build_config.yaml"` | Name of the YAML config inside `slot_config` |
| `mfe_branch` | `str` | `"master"` | Git branch |
| `node_version` | `str` | `"20"` | Node.js version |
| `env_vars` | `list[str]` | `[]` | Build-time environment variables |
| `pre_build_commands` | `list[str]` | `[]` | Commands run after `npm install` |

The config schema is defined by the pydantic models in
`src/lehrer/core/mfe_config.py` and published as `build_config.schema.json` at
the repo root. Regenerate it with `dagger call mfe build-config-schema`.

## MFE builder parameters — `OpenedxMfe.watch_legacy`

Serves a legacy MFE from a local checkout with hot reload. Returns a
`dagger.Service`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mfe_source` | `Directory` | **required** | Local MFE checkout |
| `slot_config` | `Directory` | **required** | Slot config directory. Declared `None` in the signature but rejected at runtime, same as `build_legacy` |
| `node_version` | `str` | `"20"` | Node.js version |
| `deployment_name` | `str` | `"default"` | Deployment name |
| `mfe_name` | `str` | `"learning"` | MFE name |
| `port` | `int` | `8080` | Port to expose |

For iterating on a whole deployment's MFEs against a running stack, prefer
`lehrer dev start --deployment-config ./deployments/<group> --mfe-hot-reload`.

---

## MFE builder parameters — `OpenedxMfe.build_site`

Builds an OEP-65 Site Project using `npx openedx build`. The Site Project must contain
`package.json`, `site.config.build.tsx`, `src/i18n/index.ts`, `public/index.html`, and
a `browserslist` field in `package.json`. See `deployments/mit-ol/mfe_slot_config/frontend/`
for a working reference.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `site_project` | `Directory` | **required** | Site Project directory (contains `package.json` + `site.config.build.tsx`) |
| `shared_src` | `Directory` | `None` | Optional shared components directory, mounted at `{site_project}/shared/` and aliased as `@shared/*` in tsconfig |
| `node_version` | `str` | `"24"` | Node.js version |
| `public_path` | `str` | `None` | Optional public URL prefix for assets (webpack's publicPath). Used when static assets are hosted on a CDN (e.g., S3, Fastly). If provided, sets the `PUBLIC_PATH` environment variable before build. |

Returns a `dagger.Directory` containing the built `dist/` output.

```bash
# Basic build
dagger call mfe build-site \
  --site-project ./my-site-project \
  export --path ./dist

# With shared components
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  export --path  ./dist/mitxonline
```

## MFE builder parameters — `OpenedxMfe.watch_site`

Starts a local OEP-65 dev server using `npx openedx dev`. Accepts the same parameters
as `build_site` plus `port`. Returns a `dagger.Service`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `site_project` | `Directory` | **required** | Site Project directory |
| `shared_src` | `Directory` | `None` | Optional shared components directory |
| `node_version` | `str` | `"24"` | Node.js version |
| `port` | `int` | `8080` | Port to expose |

```bash
dagger call mfe watch-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  up --ports 8080:8080
```

## MFE builder parameters — `OpenedxMfe.build_federated_module`

Currently raises `NotImplementedError`. The `openedx build:module` CLI command does not
exist in `@openedx/frontend-base` as of v1.0.0-alpha.41; module libraries are bundled at
build time into the Site Project. This function will be implemented once the upstream CLI
command ships.

---

## Site Project layout requirements

A Site Project passed to `build_site` or `watch_site` must contain:

```
my-site-project/
├── package.json            ← must include @openedx/frontend-base, browserslist field
├── site.config.build.tsx   ← production SiteConfig (read by openedx build)
├── site.config.dev.tsx     ← development SiteConfig (read by openedx dev)
├── tsconfig.json
├── src/
│   └── i18n/
│       └── index.ts            ← required; export default [];
└── public/
    └── index.html          ← required; must contain <div id="root"></div>
```

`site.config.build.tsx` exports a `SiteConfig` object (or async function returning one)
with at minimum `siteId`, `siteName`, `baseUrl`, `lmsBaseUrl`, `loginUrl`, `logoutUrl`,
`environment`, and `apps[]`. Set `runtimeConfigJsonUrl: "/api/frontend_site_config/v1/"`
to allow the LMS to override URL and cookie fields at runtime, making one build artifact
serve all environments (CI, QA, Production).

---

## Codejail builder parameters — `OpenedxCodejail.build`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `release_name` | `str` | `"master"` | Open edX release name |
| `python_version` | `str` | `None` | Python version. Auto-detected: `3.12` for `master`, `3.11` for others |
| `codejail_config` | `Directory` | **required** | Directory with the `01-sandbox` sudoers file. There is no fallback — omitting it raises a `ValueError` naming the flag |

---

## Notes builder parameters — `OpenedxNotes.build`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `release_name` | `str` | `"master"` | Git branch/tag (e.g. `"open-release/sumac.master"`) |
| `python_version` | `str` | `"3.11"` | Python version |
| `notes_code` | `Directory` | `None` | Local edx-notes-api source |
| `notes_repo` | `str` | `None` | Git URL (required if `notes_code` not provided) |
| `notes_config` | `Directory` | **required** | Directory with `env_config.py`. There is no fallback — omitting it raises a `ValueError` naming the flag |

---

## Example: minimal community deployment

The smallest possible build that produces a working platform image using the
upstream community translations repository and a generic settings namespace:

```bash
dagger call platform build-platform \
  --deployment-name mydeployment \
  --release-name sumac \
  --settings-namespace production \
  --pip-package-lists ./my-deployment/pip_package_lists \
  --pip-package-overrides ./my-deployment/pip_package_overrides \
  --custom-settings ./my-deployment/settings \
  --platform-branch open-release/sumac.master \
  --translations-repo openedx/openedx-translations \
  --translations-branch main
```

The same build, driven by a `build_manifest.yaml` cell instead of separate
flags:

```bash
dagger call platform build-platform \
  --deployment-name mydeployment \
  --release-name sumac \
  --settings-namespace production \
  --build-manifest ./my-deployment/build_manifest.yaml \
  --custom-settings ./my-deployment/settings
```

No `--extra-ssh-hosts`, no `--packages-to-remove`, no `--extra-npm-packages`
— this is pure community Open edX with no operator-specific additions.

---

## Example: MIT OL deployment

MIT OL's canonical invocations are documented with all parameters explicit
in `deployments/mit-ol/build.md`.  That file is the reference implementation
showing how a production deployment supplies every OL-specific value.

The key OL-specific parameters are:

```bash
--settings-namespace mitol \
--extra-ssh-hosts '["github.mit.edu"]' \
--packages-to-remove '["edx-name-affirmation"]' \
--extra-npm-packages '["git+https://git@github.com/verificient/..."]' \
--translations-repo mitodl/mitxonline-translations
```

---

## `custom_settings` directory contract

The `custom_settings` directory passed to `build_platform` is consumed by two
stages: `collected` takes the env YAML and the assets/i18n modules,
`inject_aqueduct_settings` takes the aqueduct models and the operator scripts.
Every file below is required — a missing one fails the build in whichever stage
reaches for it.

```
custom_settings/
├── lms.env.yml
├── cms.env.yml
├── lms/
│   ├── assets.py
│   ├── i18n.py
│   ├── aqueduct.py
│   └── models/
│       └── aqueduct.py
├── cms/
│   ├── assets.py
│   ├── i18n.py
│   ├── aqueduct.py
│   └── models/
│       └── aqueduct.py
├── set_waffle_flags.py
├── process_scheduled_emails.py
└── saml_pull.py
```

There is deliberately no top-level `models/base.py`. `inject_aqueduct_settings`
supplies that from lehrer's own `src/lehrer/settings/base.py`, so the
`ProductionSettingsMixin` every deployment's `models/aqueduct.py` inherits from
stays a single implementation rather than a per-operator copy.

See `deployments/mit-ol/settings/` and `deployments/generic/settings/` for
worked examples.
