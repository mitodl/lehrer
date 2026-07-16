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

## 9. Publishing images

Pipe any `build-platform` or `codejail build` result into `publish-platform`:

```bash
dagger call \
  platform build-platform --deployment-name mitxonline ... \
  platform publish-platform \
    --registry ghcr.io \
    --repository mitodl/openedx-platform \
    --tag "$(git rev-parse --short HEAD)"
```
