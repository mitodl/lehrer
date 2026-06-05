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
│   ├── models/
│   │   └── base.py
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
├── pip_package_lists/
│   └── {release_name}/
│       └── {deployment_name}.txt
├── pip_package_overrides/
│   └── {release_name}/
│       └── {deployment_name}.txt
├── mfe_slot_config/
│   ├── Footer.jsx
│   ├── learning-mfe-config.env.jsx
│   └── {deployment_name}/
│       └── common-mfe-config.env.jsx
├── codejail_config/
│   └── 01-sandbox
└── notes_config/
    └── env_config.py
```

---

## Platform builder parameters — `OpenedxPlatform`

### `build_platform`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `deployment_name` | `str` | **required** | Deployment name used for theme path and pip package file names (e.g. `"mydeployment"`) |
| `release_name` | `str` | **required** | Open edX release name (e.g. `"master"`, `"sumac"`, `"teak"`) |
| `pip_package_lists` | `Directory` | **required** | Directory with pip requirements. Must contain `{release_name}/{deployment_name}.txt` |
| `pip_package_overrides` | `Directory` | **required** | Directory with pip build overrides. Must contain `{release_name}/{deployment_name}.txt` |
| `custom_settings` | `Directory` | **required** | Directory with settings files (see layout above) |
| `translations_repo` | `str` | `"openedx/openedx-translations"` | GitHub repository for translations (e.g. `"myorg/my-translations"`) |
| `source` | `Directory` | `None` | Local edx-platform source (overrides `platform_repo`/`platform_branch`) |
| `platform_repo` | `str` | `"https://github.com/openedx/edx-platform"` | Git URL for edx-platform |
| `platform_branch` | `str` | `"master"` | Git branch / tag for edx-platform |
| `theme_source` | `Directory` | `None` | Local theme source (overrides `theme_repo`/`theme_branch`) |
| `theme_repo` | `str` | `None` | Git URL for theme repository |
| `theme_branch` | `str` | `None` | Git branch / tag for theme |
| `python_version` | `str` | `None` | Python version. Auto-detected: `3.12` for `master`, `3.11` for others |
| `node_version` | `str` | `"20.18.0"` | Node.js version |
| `locale_version` | `str` | `"master"` | openedx-i18n ref (archived repo) |
| `translations_branch` | `str` | `"main"` | Branch for translations repo |
| `include_locales` | `bool` | `True` | Include openedx-i18n locale files |
| `settings_namespace` | `str` | `"production"` | Django settings sub-package. Files go into `lms/envs/{namespace}/` and `cms/envs/{namespace}/`. MIT OL uses `"mitol"` |
| `extra_ssh_hosts` | `list[str]` | `[]` | Additional SSH hosts beyond `github.com` for `known_hosts` (e.g. `["github.mit.edu"]`) |
| `packages_to_remove` | `list[str]` | `[]` | Python packages to uninstall after base install |
| `extra_npm_packages` | `list[str]` | `[]` | Additional npm packages to install (e.g. private git packages) |

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
| `mfe_repo` | `str` | **required** | Git URL for the MFE |
| `mfe_branch` | `str` | `"master"` | Git branch |
| `node_version` | `str` | `"20.18.0"` | Node.js version |
| `deployment_name` | `str` | `"mitxonline"` | Deployment name for config file selection |
| `slot_config` | `Directory` | `None` | Slot config directory (defaults to MIT OL legacy config) |
| `enable_ai_drawer` | `bool` | `False` | Include AI drawer components (learning MFE only) |
| `styles_file` | `str` | `None` | Deployment-specific styles file name |
| `extra_npm_bundles` | `list[str]` | `[]` | Extra npm packages to pack as static bundles. Format: `"pkg_spec\|target_dir"` (e.g. `"@myorg/lib@^1.0\|public/static/lib"`) |

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
| `codejail_config` | `Directory` | `None` | Directory with `01-sandbox` sudoers file (defaults to MIT OL config) |

---

## Notes builder parameters — `OpenedxNotes.build`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `release_name` | `str` | `"master"` | Git branch/tag (e.g. `"open-release/sumac.master"`) |
| `python_version` | `str` | `"3.11"` | Python version |
| `notes_code` | `Directory` | `None` | Local edx-notes-api source |
| `notes_repo` | `str` | `None` | Git URL (required if `notes_code` not provided) |
| `notes_config` | `Directory` | `None` | Directory with `env_config.py` (defaults to MIT OL config) |

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

The `custom_settings` directory passed to `build_platform` / `collected`
**must** contain the following files (all required — missing files will cause
a container exec error with a clear message from `cp`):

```
custom_settings/
├── lms.env.yml
├── cms.env.yml
├── models/
│   └── base.py
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

See `deployments/mit-ol/settings/` for a worked example.
