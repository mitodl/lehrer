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
| `lehrer dev`    | Manage the local k3d Open edX dev environment |
| `lehrer build`  | Run the Dagger build pipelines |
| `lehrer compat` | Enumerate the build cells a diff affects, for the CI matrices |

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

lehrer dev db-collation  # audit MariaDB schema-collation drift (see below)
```

Use a deployment-specific config and MFE hot-reload:

```bash
lehrer dev start --deployment-config ./deployments/mit-ol --mfe-hot-reload
```

#### MFE hot reload

`--mfe-hot-reload` serves the MFEs from host dev servers *instead of* from the
cluster: the compiled nginx image, Deployment and ingress route are all skipped,
so nothing is built for a site you are editing live.

Each site's dev server binds the port declared for it in
`mfe_slot_config/frontend/dev-ports.yaml`. Keep those clear of the ports k3d's
loadbalancer binds (`k3d-config.yaml`: 8000, 8001, 8010, 8090) and distinct
from each other; the Tiltfile refuses to load otherwise. Defaults:

| Deployment | Site | Dev port | Dev `baseUrl` |
|---|---|---|---|
| generic | default    | 8100 | http://localhost:8100 |
| mit-ol  | mitx       | 8101 | http://apps.local.openedx.io:8101 |
| mit-ol  | mitxonline | 8102 | http://apps.local.openedx.io:8102 |
| mit-ol  | xpro       | 8103 | http://apps.local.openedx.io:8103 |

The port is declared rather than read out of `baseUrl` because the two answer
different questions: the port is where webpack-dev-server listens on your
machine, while `baseUrl` is where the browser reaches the app. They coincide
only when a site gets a host to itself. An MFE served as a **sub-path of the
LMS** — the topology ol-infrastructure deploys — has a `baseUrl` carrying the
LMS origin and no port of its own. When `baseUrl` *does* name a port, the
Tiltfile checks it matches, since a dev server listening anywhere else just
serves a broken site.

Hostnames are per-deployment settings, not fixed requirements. The defaults
above need no setup because upstream Open edX publishes `*.local.openedx.io` as
a public A record pointing at `127.0.0.1` — but that makes hot reload depend on
public DNS, so it breaks offline or behind a resolver that filters the name. To
check before starting:

```bash
lehrer dev check --deployment-config ./deployments/mit-ol
```

If a name does not resolve, map it to `127.0.0.1` in `/etc/hosts`.

Secret values are read from the environment (`MYSQL_ROOT_PASSWORD`,
`DJANGO_SECRET_KEY`, `MONGO_PASSWORD`, `PROVISION_SUPERUSER_PASSWORD`, ...) and
fall back to safe local-dev defaults. They all land in the `openedx-secrets`
Secret, which the MariaDB and MongoDB CRs read too — so an override reaches the
operators rather than only the application.

> **Existing clusters:** the MariaDB CR used to carry its own root-password
> Secret, and `spec.rootPasswordSecretKeyRef` is immutable. A cluster created
> before that change rejects the new manifest and `lehrer dev start` fails on
> the `mysql` resource. Both `lehrer dev setup` and `lehrer dev start` detect
> this and print the fix:
>
> ```bash
> kubectl --context k3d-lehrer-dev -n openedx delete mariadb mysql
> kubectl --context k3d-lehrer-dev -n openedx delete pvc storage-mysql-0
> ```
>
> which drops the edxapp databases and lets the migrate and provision Jobs
> rebuild them. Both lines matter: the PVC is retained when the CR goes, and a
> replacement that reattaches it keeps the old databases *and* the old root
> password. Keep the `--context` too — an unqualified delete lands on whichever
> cluster your kubeconfig currently points at.

`MYSQL_ROOT_PASSWORD` is init-only. MariaDB sets root's password when it
initializes an empty datadir and never rotates it, so an override has to be set
before the **first** `lehrer dev setup`; changing it later moves the Secret but
not the server. `lehrer dev setup` notices and prints the same recreate steps.
`MONGO_PASSWORD` has no such limitation — the MongoDB operator rotates SCRAM
credentials when the referenced Secret changes.

#### Provisioning

`edxapp-migrate` creates the edxapp schema; three more Jobs turn that into a
usable stack:

| Job | Trigger | What it does |
|---|---|---|
| `edxapp-provision`  | automatic | Superuser, notes OAuth client, waffle flags |
| `notes-migrate`     | automatic | edx-notes-api schema and search index |
| `edxapp-demo-course`| manual    | Imports the Open edX demo course |

`edxapp-provision` creates the `edx` / `edx` superuser (override the password
with `PROVISION_SUPERUSER_PASSWORD` before `lehrer dev setup`), the DOT OAuth
Application that LMS↔notes SSO signs its tokens with, and the waffle flags in
`local-dev/provision/waffle-flags.yaml`. It is idempotent, so Tilt re-runs it
whenever the platform image changes. Add OAuth clients in
`local-dev/provision/provision.py`; both files are mounted into the Job as a
ConfigMap.

`notes-migrate` creates the tables in the `notes` database (the MariaDB CR
creates the database and the grant, but nothing creates the schema) and the
OpenSearch index. Both are required: edx-notes-api indexes on every save via
`RealTimeSignalProcessor`, so a missing index breaks annotation writes and not
just search. The Job fails rather than leave a notes service running that
cannot be written to.

`edxapp-demo-course` resolves the demo course branch matching the release the
stack was built from, so a named-release stack does not import master content.
Set `DEMO_COURSE_GIT_BRANCH` in the Job to pin a branch instead. It is left off
the critical path because it clones the course repo over the network. Trigger
it from the Tilt UI, or:

```bash
tilt trigger edxapp-demo-course
```

Neither migrate Job retries. MariaDB DDL is not transactional, so a migration
that dies partway leaves the tables and columns it already created behind, and a
second attempt fails on "table already exists" — burying whatever the first, real
error was. `backoffLimit: 0` keeps the original failure on screen.

#### Database collation

Every schema is created as `utf8mb4` / `utf8mb4_unicode_ci`, pinned explicitly in
`local-dev/manifests/infra/mariadb.yaml`. This is not a detail the server config
can cover for you: a schema's default collation is stored once, at
`CREATE DATABASE` time, and never follows a later change to `collation-server`.
Any `CREATE TABLE` that omits an explicit `COLLATE` inherits whatever the schema
was created with, and a foreign key between two tables on different collations is
rejected with errno 150, "Foreign key constraint is incorrectly formed" — a
migration failure that reads like a MariaDB bug and is really schema metadata
drift. It is a longstanding source of migration failures in residential MITx.

The mariadb-operator makes this easy to get wrong. `spec.database` on the MariaDB
CR does not create the schema itself; the operator turns it into a `Database` CR
named `<mariadb>-database` with no `characterSet`/`collate`, the CRD defaults
(`utf8` / `utf8_general_ci`) get stamped on, and it issues an explicit
`CREATE DATABASE edxapp CHARACTER SET = 'utf8' COLLATE = 'utf8_general_ci'`.
Declaring `mysql-database` ourselves is what stops that: the reconciler only
builds its own when that key is absent. Anything that provisions a MariaDB schema
for a lehrer deployment needs the same treatment — set the collation at creation,
and do not rely on a parameter group, which only reaches schemas created after it.

To check an existing cluster:

```bash
lehrer dev db-collation                 # report schema and table collations
lehrer dev db-collation --fix           # ALTER DATABASE drifted schemas
lehrer dev db-collation --check-tables  # also CHECK TABLE for corruption
```

`--fix` only realigns the schema-level default, which is a metadata change that
rewrites nothing — new tables land on the right collation, existing ones keep
theirs. Converting those in place is the risky half, so it is not automated; on a
dev cluster, recreate the instance and let the Jobs rebuild the schema.
`--check-tables` reports and never repairs: rebuilding a corrupt unique index can
delete the duplicate rows it was masking. This mirrors ol-infrastructure's
`bin/mariadb-collation-guard`, which is the version to reach for against deployed
environments.

`lehrer dev setup` runs the schema-level audit on an already-initialized datadir
and points here if it finds drift.

> **Existing clusters:** if your cluster predates this, the operator already
> generated a `mysql-database` Database resource on `utf8`, and `characterSet` /
> `collate` are immutable — `lehrer dev start` fails on it. Both `setup` and
> `start` detect that and print the way out. Delete the resource *after* patching
> its `cleanupPolicy` to `Skip`: the Database finalizer runs `DROP DATABASE`, so
> deleting it on the CRD's `Delete` default takes edxapp with it. The manifests
> now set `cleanupPolicy: Skip` on all three databases for that reason.

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

`build-platform` is a two-base build, the way a multi-stage Dockerfile would
be. Dependencies are resolved on one base, and only `/openedx/venv`,
`/openedx/edx-platform` and `/openedx/nodeenv` are copied onto a fresh one —
so the intermediate state of the dependency resolution (uv and npm caches,
build artifacts, discarded layers) never reaches the shipped image. The
compilers and `-dev` headers do: the second base is another `apt-base`, which
installs the same toolchain the first one did.

1. **apt-base** - Base Python container with system dependencies and uv
2. **get-code** - Get edx-platform source (local or Git) and create the venv
3. **install-deps** - Install Python (uv) and Node.js (nodeenv) dependencies

then, on a second `apt-base`, with the venv and source copied across:

4. **locales** - openedx-i18n locale files (skipped by `--include-locales false`)
5. **themes** - Get theme files (local or Git)
6. **collected** - Assemble artifacts and configure the container. Takes its
   inputs from **tutor-utils** (Tutor's bin scripts) and **dockerize**
7. **fetch-translations** - Pull and compile translations
8. **build-static-assets** - Build and collect static assets
9. **inject-aqueduct-settings** - Install the aqueduct settings models
10. **docker-image** - Finalize for deployment

Unless `--verify-boot false`, the finished image is then started and Django's
system checks are run for both LMS and CMS. `publish-platform` chains onto the
returned `Container` to push it.

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
`fetch-translations` → `build-static-assets` → `inject-aqueduct-settings` →
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

Everything the pipelines need is operator-owned and lives under
`deployments/<group>/`. Nothing is picked up implicitly from the repo root, and
the generic pipelines never fall back to MIT OL's directories — `slot_config`,
`codejail_config` and `notes_config` are all required, and omitting one fails
with an error naming the flag.

```
deployments/mit-ol/
├── build_manifest.yaml          # one cell per (release, deployment)
├── settings/                    # → --custom-settings
├── mfe_slot_config/
│   ├── legacy/                  # → --slot-config for webpack MFEs
│   └── frontend/                # → --site-project for OEP-65 Site Projects
├── codejail_config/             # → --codejail-config (01-sandbox)
└── notes_config/                # → --notes-config (env_config.py)
```

### `build_manifest.yaml`

The declarative source of truth for a deployment group: one cell per
`(release, deployment)` pair naming the platform/theme/translations repos and
branches, the Python and Node versions, and the pinned requirement lines. It
replaces the older `pip_package_lists/` + `pip_package_overrides/` directories,
which remain supported as a lower-level alternative
(`{release_name}/{deployment_name}.txt` under each). See
`src/lehrer/core/build_manifest.py` and `plans/06-build-manifest.md`.

### `custom_settings/` (`settings/`)

```
settings/
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

Every file is required. There is deliberately no top-level `models/base.py`:
`inject-aqueduct-settings` supplies that from lehrer's own
`src/lehrer/settings/base.py`, keeping the `ProductionSettingsMixin` a single
implementation rather than a per-operator copy. The full contract is in
[docs/creating-a-deployment.md](docs/creating-a-deployment.md).

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

- Build any Open edX MFE from source, or from a local checkout (`--mfe-source`)
- Slot configuration files (`Footer.jsx`, `env.config.jsx`, and any file named
  by `--extra-slot-files`)
- Deployment-specific styling (`--styles-file`)
- Extra npm packages packed as static bundles (`--extra-npm-bundles`), which is
  how the learning MFE gets smoot-design and its AI-drawer components
- Build-time configuration via repeatable `--env-vars`
- Translation pulls via `--pre-build-commands` (openedx-atlas)
- Per-deployment customizations declared once in `build_config.yaml`
- Local development with hot reload

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

`mfe_slot_config/legacy/` holds what `--slot-config` points at for a webpack
MFE build. Two files are looked up by name on every build:

- `Footer.jsx` — custom footer component (all MFEs)
- `{deployment}/common-mfe-config.env.jsx` — per-deployment config, installed as
  `env.config.jsx`. The learning MFE additionally picks up
  `learning-mfe-config.env.jsx`

Everything else in the directory is opt-in, named by `--extra-slot-files`,
`--styles-file` and `--extra-npm-bundles` (or resolved from `build_config.yaml`
by `build-legacy-configured`). MIT OL's directory currently supplies AI-drawer
and feedback slot components, `ResponsiveCourseTabs.jsx`, and the
`mitx-styles.scss` / `mitxonline-styles.scss` deployment stylesheets.

`mfe_slot_config/frontend/` is the OEP-65 side: one Site Project per deployment
plus a `shared/` component directory and `dev-ports.yaml`.

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

### Tests and checks

`tests/` covers the parts of `src/lehrer/` that run without a Dagger engine —
argument and manifest resolution, config parsing, JUnit report generation, the
CLI wrappers:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file=pyproject.toml src/lehrer tests
uv run pytest tests/ -v
```

`ci.yml` runs exactly those four on every push and pull request, then three
named pre-commit hooks rather than the whole suite:

```bash
uv run pre-commit run build-config-schema --all-files
uv run pre-commit run build-manifest-schema --all-files
uv run pre-commit run lehrer-core-boundary --all-files
```

The rest of the hooks run on commit, so `uv run pre-commit run --all-files`
locally is a superset of the PR gate, not the same thing. The other
workflows cover what needs a Dagger engine or a schedule: `settings-verify.yml`
boots each cell's committed aqueduct settings, `plugin-compat.yml` installs and
imports each cell's pinned requirements, `canary.yml` runs full platform builds
on a schedule, and `actions-static-analysis.yml` lints the workflows themselves
with zizmor.

### Adding New Functions

`src/lehrer/main.py` is only the Dagger entry point — a thin `Lehrer` root type
whose methods return the per-service objects. The pipelines themselves live in
`src/lehrer/core/`, one module per service.

1. Add the `@function` method to the service object it belongs to —
   `core/platform.py`, `core/mfe.py`, `core/codejail.py` or `core/notes.py`.
   Only a *new service* needs a new accessor on `Lehrer` in `main.py`
2. Follow the naming convention (snake_case becomes kebab-case in the CLI)
3. Add docstrings with Args and Returns sections
4. If it is a routine operation, add a wrapper to `src/lehrer/cli/build.py` so
   it gets a `lehrer build` shortcut
5. Add tests under `tests/core/` (or `tests/cli/`) for any logic that can be
   exercised without a Dagger engine — argument resolution, config parsing,
   report generation
6. Update this README and `docs/creating-a-deployment.md` with the parameters

## License

BSD-3-Clause
