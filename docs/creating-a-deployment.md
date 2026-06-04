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
| `dagger call mfe` | `OpenedxMfe` | Open edX Micro Frontends (legacy + OEP-65 stubs) |
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
