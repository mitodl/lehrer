# MIT OL — Canonical Build Commands

Copy-pasteable `dagger call` commands for every service built by MIT OL.
All commands are run from the repository root.

> **Note:** Commands that pull private packages (proctortrack, private themes)
> require an SSH agent with the appropriate keys forwarded, or a `--ssh`
> secret argument.  Those are not shown here for brevity.

---

## 1. edx-platform — MITx Online (mitxonline), master branch

```bash
dagger call platform build-platform \
  --deployment-name mitxonline \
  --release-name master \
  --settings-namespace mitol \
  --pip-package-lists ./deployments/mit-ol/pip_package_lists \
  --pip-package-overrides ./deployments/mit-ol/pip_package_overrides \
  --custom-settings ./deployments/mit-ol/settings \
  --platform-branch master \
  --translations-repo mitodl/mitxonline-translations \
  --translations-branch main \
  --extra-ssh-hosts '["github.mit.edu"]' \
  --packages-to-remove '["edx-name-affirmation"]' \
  --extra-npm-packages '["git+https://git@github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732"]'
```

---

## 2. edx-platform — MITx (mitx), teak release

```bash
dagger call platform build-platform \
  --deployment-name mitx \
  --release-name teak \
  --settings-namespace mitol \
  --pip-package-lists ./deployments/mit-ol/pip_package_lists \
  --pip-package-overrides ./deployments/mit-ol/pip_package_overrides \
  --custom-settings ./deployments/mit-ol/settings \
  --platform-branch open-release/teak.master \
  --translations-repo mitodl/mitx-translations \
  --translations-branch main \
  --extra-ssh-hosts '["github.mit.edu"]' \
  --extra-npm-packages '["git+https://git@github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732"]'
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

## 5. MFE (legacy) — learning MFE with smoot-design bundle

```bash
dagger call mfe build-legacy \
  --mfe-name learning \
  --mfe-repo https://github.com/openedx/frontend-app-learning \
  --mfe-branch master \
  --deployment-name mitxonline \
  --slot-config ./deployments/mit-ol/mfe_slot_config/legacy \
  --enable-ai-drawer true \
  --styles-file mitxonline-styles.scss \
  --extra-npm-bundles '["@mitodl/smoot-design@^6.12.0|public/static/smoot-design"]'
```

---

## 6. OEP-65 Site Project builds (frontend-base)

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

## Regenerating aqueduct settings models

After adding or removing pip packages, regenerate the AqueductSettings pydantic
models and commit the result:

```bash
# mitxonline
dagger call platform regenerate-aqueduct-settings \
  --deployment-name mitxonline \
  --pip-package-lists ./deployments/mit-ol/pip_package_lists \
  --pip-package-overrides ./deployments/mit-ol/pip_package_overrides \
  --packages-to-remove '["edx-name-affirmation"]' \
  export --path ./generated

cp generated/lms/models/aqueduct.py deployments/mit-ol/settings/lms/models/aqueduct.py
cp generated/cms/models/aqueduct.py deployments/mit-ol/settings/cms/models/aqueduct.py
```

---

## Publishing images

Pipe any `build-platform` or `codejail build` result into `publish-platform`:

```bash
dagger call \
  platform build-platform --deployment-name mitxonline ... \
  platform publish-platform \
    --registry ghcr.io \
    --repository mitodl/openedx-platform \
    --tag "$(git rev-parse --short HEAD)"
```
