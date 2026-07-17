# MIT OL — Canonical Build Commands

Copy-pasteable `dagger call` commands for every service built by MIT OL.
All commands are run from the repository root.

> **Note:** Commands that pull private packages (proctortrack, private themes)
> require an SSH agent with the appropriate keys forwarded, or a `--ssh`
> secret argument.  Those are not shown here for brevity.

---

## 1. edx-platform — MITx Online (mitxonline), master branch

All build parameters (platform branch, translations repo, theme, python/node
version, `packages_to_remove`, pip packages) come from
`deployments/mit-ol/build_manifest.yaml` — the single source of truth for
every `(release, deployment)` cell (see `plans/06-build-manifest.md`).

```bash
lehrer build platform --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings
```

Equivalent raw `dagger call`:

```bash
dagger call platform build-platform \
  --deployment-name mitxonline \
  --release-name master \
  --settings-namespace mitol \
  --build-manifest ./deployments/mit-ol/build_manifest.yaml \
  --custom-settings ./deployments/mit-ol/settings
```

---

## 2. edx-platform — MITx (mitx), other cells

Every cell in the matrix is built the same way — swap `--cell`. The available
cells (`lehrer build cells --manifest ./deployments/mit-ol/build_manifest.yaml`):
`master/mitxonline`, `master/mitx`, `master/mitx-staging`, `ulmo/mitx`,
`ulmo/mitx-staging`, `ulmo/xpro`, `verawood/mitx`, `verawood/mitx-staging`,
`verawood/xpro`.

```bash
lehrer build platform --cell mit-ol/verawood/mitx \
  --custom-settings ./deployments/mit-ol/settings
```

---

## 3. codejail — any release

```bash
# master
dagger call codejail build \
  --release-name master \
  --codejail-config ./deployments/mit-ol/codejail_config

# teak
dagger call codejail build \
  --release-name teak \
  --codejail-config ./deployments/mit-ol/codejail_config
```

---

## 4. edx-notes-api — any release

```bash
# master
dagger call notes build \
  --release-name master \
  --notes-repo https://github.com/openedx/edx-notes-api \
  --notes-config ./deployments/mit-ol/notes_config

# teak
dagger call notes build \
  --release-name open-release/teak.master \
  --notes-repo https://github.com/openedx/edx-notes-api \
  --notes-config ./deployments/mit-ol/notes_config
```

---

## 5. MFE (legacy) — learning MFE

Extra slot files, npm bundles, and per-deployment styles are declared in
`mfe_slot_config/legacy/build_config.yaml` and resolved automatically by
`build-legacy-configured`.

```bash
dagger call mfe build-legacy-configured \
  --mfe-name learning \
  --mfe-repo https://github.com/openedx/frontend-app-learning \
  --mfe-branch master \
  --deployment-name mitxonline \
  --release-name master \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy
```

---

## 6. MFE (legacy) — admin-console

```bash
dagger call mfe build-legacy-configured \
  --mfe-name admin-console \
  --mfe-repo https://github.com/openedx/frontend-app-admin-console \
  --mfe-branch master \
  --deployment-name mitxonline \
  --release-name master \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy
```

---

## 7. OEP-65 Site Project builds (frontend-base)

Each deployment has its own Site Project under
`deployments/mit-ol/mfe_slot_config/frontend/<deployment>/`.
All three share components from `mfe_slot_config/frontend/shared/`.

### MITx Online (mitxonline)

```bash
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  export --path ./dist/mitxonline
```

Dev server:

```bash
dagger call mfe watch-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  up --ports 8080:8080
```

### MITx (mitx + mitx-staging)

One build artifact; `runtimeConfigJsonUrl` supplies environment-specific URLs at startup.

```bash
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitx \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  export --path ./dist/mitx
```

### xPRO

```bash
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/xpro \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  export --path ./dist/xpro
```

---

## 8. Regenerating aqueduct settings models

After adding or removing pip packages, regenerate the AqueductSettings pydantic
models and commit the result:

```bash
# mitxonline
dagger call platform regenerate-aqueduct-settings \
  --deployment-name mitxonline \
  --release-name master \
  --build-manifest ./deployments/mit-ol/build_manifest.yaml \
  export --path ./generated

cp generated/lms/models/aqueduct.py deployments/mit-ol/settings/lms/models/aqueduct.py
cp generated/cms/models/aqueduct.py deployments/mit-ol/settings/cms/models/aqueduct.py
```

---

## 9. Running test suites inside built images

These targets run test suites inside a built image, under the deployment's
configuration — so a regression particular to a `(deployment × release × plugin
set)` surfaces here rather than in production. They are the execution engine for
the plugin-compat matrix's deep tier and the scheduled canary. `platform test`
runs edx-platform's own suite **and** (by default) the installed plugins' own
suites in one run; `codejail-test`/`notes-test` run those services' suites.

### edx-platform (`platform test`)

Defaults to a curated smoke subset (courseware, student, third_party_auth for
LMS) run under `lms.envs.lehrer_test` — derived from `lms.envs.test`. The
deployment's plugins load automatically via the Open edX plugin framework, so
the run exercises the deployment's plugin set (the primary compatibility
signal). Only a MongoDB service (the modulestore) is provisioned — the stock
test settings use sqlite + a dummy cache + the mock search engine.

The deployment's actual `FEATURES` flags are overlaid **only** when you pass
`--config-sources` pointing at the cell's rendered `OL_SETTINGS_DIR` YAMLs
(the complex-type values K8s ConfigMaps supply at runtime — these live in
ol-infrastructure, not this repo). Without it, the run keeps the upstream test
flags. `--full` uses the same roots upstream collects (including `xmodule`).

```bash
# Smoke subset (LMS) for a cell:
lehrer build test --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings

# Studio (CMS):
lehrer build test --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  --service cms

# Target specific apps / paths / node-ids (e.g. a plugin's integration tests):
lehrer build test --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings \
  --test-paths lms/djangoapps/courseware/tests/test_views.py

# Whole service tree (hours — canary tier), or add --markers for a -m expr:
lehrer build test --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings --full

# edx-platform suite only, without the installed plugins' own suites:
lehrer build test --cell mit-ol/master/mitxonline \
  --custom-settings ./deployments/mit-ol/settings --no-include-plugins
```

**Plugins folded in.** With `--include-plugins` (default), the same pytest run
also executes whatever tests the installed plugins ship — appended to the
edx-platform targets via `--pyargs`, so one run covers edx-platform **and** the
plugins. It uses pytest **discovery**: published plugin packages don't ship their
tests today, so with `--install-test-extras` (default) each maintained
`ol-openedx-*` plugin is re-requested at its pinned version with a `[tests]`
extra (a safe no-op until the plugin defines one; any package the cell removed
via `packages_to_remove` is excluded so the run matches production). A plugin
that ships no tests simply collects nothing (never a failure), so this stays
green today and starts running real plugin suites the moment one is published.
Pass `--no-include-plugins` for the edx-platform suite alone, or
`--no-install-test-extras` to skip the extra install.

### codejail (`codejail test`) and notes (`notes test`)

Small suites — run wholesale in the build container.

```bash
lehrer build codejail-test \
  --release-name master \
  --codejail-config ./deployments/mit-ol/codejail_config

lehrer build notes-test \
  --release-name master \
  --notes-repo https://github.com/openedx/edx-notes-api \
  --notes-config ./deployments/mit-ol/notes_config
```

---

## 10. Publishing images

Pipe any `build-platform` or `codejail build` result into `publish-platform`:

```bash
dagger call \
  platform build-platform --deployment-name mitxonline ... \
  platform publish-platform \
    --registry ghcr.io \
    --repository mitodl/openedx-platform \
    --tag "$(git rev-parse --short HEAD)"
```
