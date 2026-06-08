# Plan 04 — Concourse Pipeline and Fastly Routing for Frontend-Base Site Projects

## Status: In progress — Phase 1 infrastructure implemented

## Context

The three OEP-65 Site Projects (`mitxonline`, `mitx`, `xpro`) build and validate locally
via `dagger call mfe build-site`. This plan covers the infrastructure work required to deploy
them to S3 and serve them through Fastly alongside the existing legacy per-MFE builds.

**Key constraint**: `build_legacy` and the legacy Concourse pipeline must remain fully
functional. Site Project deployment is additive — new Concourse jobs and new S3/Fastly
paths are introduced, nothing is removed until a Site Project has been validated in
production for a given MFE.

**Prerequisite**: ol-infrastructure PR #4730 must be merged before end-to-end
validation is possible. That PR enables `ENABLE_MFE_CONFIG_API` and populates
`FRONTEND_SITE_CONFIG` so that the runtime config API returns the correct values.

---

## Architecture overview

### Legacy (per-MFE)

```
Concourse job (per MFE × env)
  npm install && npm run build   ← env vars injected at build time
  rclone sync dist/  →  s3://{env}-edxapp-mfe/{mfe_path}/

Fastly:
  /apps/learning/*    →  s3://{env}-edxapp-mfe/learning/
  /apps/account/*     →  s3://{env}-edxapp-mfe/account/
  ... (one rule per MFE)
```

### OEP-65 Site Project (per deployment)

```
Concourse job (per deployment × env)
  dagger call mfe build-site     ← no per-env build vars; runtime config does this
    --site-project {deployment}/
    --shared-src shared/
    --public-path /apps/{deployment}-site/
  rclone sync dist/  →  s3://{env}-edxapp-mfe/{deployment}-site/

Fastly:
  /apps/{deployment}-site/*   →  s3://{env}-edxapp-mfe/{deployment}-site/  (chunks)
  /apps/learning/*            →  s3://{env}-edxapp-mfe/{deployment}-site/index.html  (SPA)
  /apps/account/*             →  s3://{env}-edxapp-mfe/{deployment}-site/index.html  (SPA)
  ... (added one rule per migrated MFE; legacy rules remain for unmigrated MFEs)
```

The key difference: the Site Project is one build artifact per deployment that handles all
registered MFEs. Fastly serves `index.html` from the Site Project bucket for all registered
MFE paths, then React Router handles client-side routing. JS/CSS chunks are served from
the dedicated `/apps/{deployment}-site/` path.

---

## S3 layout

Use the existing `{env}-edxapp-mfe` bucket, adding a per-deployment prefix:

| Deployment | S3 prefix |
|---|---|
| mitxonline | `{env}-edxapp-mfe/mitxonline-site/` |
| mitx | `{env}-edxapp-mfe/mitx-site/` |
| xpro | `{env}-edxapp-mfe/xpro-site/` |

Example (mitxonline, production):

```
mitxonline-production-edxapp-mfe/
  mitxonline-site/
    index.html
    app.{hash}.js
    165.{hash}.js
    165.{hash}.css
    runtime.{hash}.js
    ...
  learning/       ← legacy MFE, unchanged
    index.html
    main.{hash}.js
    ...
```

`PUBLIC_PATH` must be set to `/apps/{deployment}-site/` at build time so that
the JS/CSS chunk URLs in `index.html` resolve correctly when Fastly proxies
chunk requests. Pass it as an env var to `dagger call mfe build-site`:

```bash
PUBLIC_PATH=/apps/mitxonline-site/ \
  dagger call mfe build-site \
    --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
    --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared
```

`getPublicPath()` in the frontend-base webpack config already reads
`process.env.PUBLIC_PATH` in Node.js context (not the browser bundle), so this
works without any webpack `DefinePlugin` changes.

### Dagger `build_site` env var support

`build_site` already exposes a `public_path: str | None` parameter (implemented in
PR #51).  Pass it directly:

```bash
dagger call mfe build-site \
    --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
    --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
    --public-path  https://static.mitxonline.mit.edu/ \
    export --path ./dist/mitxonline
```

---

## Concourse pipeline

### Where it lives

Add a new pipeline at:
```
ol-infrastructure/src/ol_concourse/pipelines/open_edx/mfe/site_pipeline.py
```

The existing `pipeline.py` stays unchanged. The Site Project pipeline is a
sibling, registered separately in the `fly set-pipeline` step in CI.

### Inputs

| Resource | Type | Description |
|---|---|---|
| `lehrer-repo` | `git` | `github.com/mitodl/lehrer` — triggers rebuild on changes to `deployments/mit-ol/mfe_slot_config/frontend/` |
| `ol-infrastructure-repo` | `git` | `github.com/mitodl/ol-infrastructure` — triggers rebuild on `k8s_configmaps.py` changes |
| `mfe-site-bucket` | `rclone` | Same S3 config as legacy `mfe-app-bucket` |

### Job structure (one job per deployment × environment stage, mirroring legacy pipeline)

```
build-mitxonline-ci → build-mitxonline-qa → build-mitxonline-production
build-mitx-ci       → build-mitx-qa       → build-mitx-production
build-xpro-ci       → build-xpro-qa       → build-xpro-production
```

CI jobs trigger automatically. QA/Production jobs trigger via GitHub issue
promotion (same pattern as legacy `mfe_job` in `pipeline.py`).

### Task: build and upload

```bash
# Install Dagger CLI (version must match lehrer's dagger.json)
curl -fsSL https://dl.dagger.io/dagger/install.sh | DAGGER_VERSION=0.18.x sh

# Build the Site Project
./dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  --public-path  /apps/mitxonline-site/ \
  export --path ./dist/mitxonline

# Upload to S3
rclone sync ./dist/mitxonline \
  s3-remote:{env}-edxapp-mfe/mitxonline-site/ \
  --s3-acl public-read \
  --checksum
```

No per-environment build parameters are needed because `FRONTEND_SITE_CONFIG` on
the LMS provides all environment-specific values at runtime via
`/api/frontend_site_config/v1/`. The same artifact that was uploaded to CI promotes
unchanged to QA and Production (no rebuild required).

### Promotion model

Unlike the legacy pipeline (where each environment requires a separate build because
env vars are baked in), the Site Project artifact is **environment-agnostic**. The
CI build artifact can be promoted directly:

```
CI build → s3://mitxonline-ci-edxapp-mfe/mitxonline-site/
  → copy to s3://mitxonline-qa-edxapp-mfe/mitxonline-site/    (no rebuild)
  → copy to s3://mitxonline-production-edxapp-mfe/mitxonline-site/  (no rebuild)
```

This is a significant operational improvement over the legacy pipeline. Implement using
rclone `copy` between buckets at the QA/Production promotion steps.

---

## Fastly changes

### Where VCL lives

The Fastly VCL configuration for MIT OL's CDN is managed in the
`ol-infrastructure` Pulumi stack for the edxapp deployments. Locate the VCL
resource before making changes (search for `fastly` or `vcl` in the edxapp
Pulumi `__main__.py`).

### Required new rules (per deployment)

Two new rule types per deployment:

**Rule 1 — Static asset passthrough** (must match before Rule 2)

Serve JS/CSS/font chunk files directly from S3:

```vcl
if (req.url ~ "^/apps/mitxonline-site/") {
  # Pass through to S3 as-is; assets are versioned by content hash
  set req.backend = F_mitxonline_site_bucket;
}
```

**Rule 2 — SPA fallback** (for each MFE path that has been migrated to the Site Project)

Return `index.html` from the Site Project for all app routes:

```vcl
if (req.url ~ "^/apps/(instructor-dashboard)(/|$)") {
  # Rewrite to Site Project index.html; React Router handles client-side routing
  set req.url = "/apps/mitxonline-site/index.html";
  set req.backend = F_mitxonline_site_bucket;
}
```

Add the migrated MFE paths to the alternation as each MFE is added to the Site Project:
`(instructor-dashboard|learning|account|dashboard|...)`.

**Critical ordering**: The static asset rule must evaluate before the SPA fallback
rule, or chunk requests (e.g., `/apps/mitxonline-site/app.abc123.js`) will be
served `index.html` instead of the chunk.

### Cache headers

The Site Project's `index.html` must not be cached aggressively — it is the single
entry point and must always reflect the latest build:

```vcl
if (req.url ~ "^/apps/mitxonline-site/index\.html$"
    || req.url ~ "^/apps/(instructor-dashboard)(/|$)") {
  set beresp.ttl = 0s;
  set beresp.http.Cache-Control = "no-cache, no-store, must-revalidate";
}
```

Versioned chunk files (`.{hash}.js`, `.{hash}.css`) can have long TTLs since
the hash changes with every build.

---

## Transition and rollout order

### Phase 1 — Infrastructure (no user traffic impact)

1. Merge ol-infrastructure PR #4730
2. Deploy updated LMS configmap to CI; verify `/api/frontend_site_config/v1/` returns
   expected values
3. ~~Add `public_path` parameter to `build_site`~~ — already implemented in `src/lehrer/core/mfe.py`
4. Write `site_pipeline.py`; register with CI but do not add Fastly rules yet
5. Trigger CI build; verify S3 upload to `{env}-edxapp-mfe/mitxonline-site/`

### Phase 2 — Validation in CI (parallel to legacy builds)

1. Add Fastly static asset rule for `/apps/mitxonline-site/`
2. Add Fastly SPA rule for the first migrated MFE (start with `instructor-dashboard`
   since it is already wired into the Site Project and not heavily used)
3. Validate end-to-end in CI: navigate to `https://{ci-lms}/apps/instructor-dashboard/`
   and confirm the Site Project loads with correct runtime config
4. Iterate for each additional MFE path

### Phase 3 — QA and Production promotion

1. Promote CI artifact to QA; validate
2. Promote QA artifact to Production; validate
3. Repeat Phase 2–3 for remaining MFE paths as they are migrated

### Phase 4 — Legacy decommission (per MFE, deferred)

After a Site Project MFE has been stable in production for at least two release
cycles, remove the corresponding legacy Concourse job and S3 prefix. Legacy
`build_legacy` remains available in lehrer for operators still on pre-OEP-65
releases.

---

## Open questions

- **Fastly VCL location**: Confirm whether the VCL is in a Pulumi resource in the
  edxapp `__main__.py` or managed separately before writing the Pulumi changes.
- **Dagger in Concourse**: The current MFE pipeline runs `npm` directly in a task
  container. Running `dagger call` in Concourse requires either Docker-in-Docker or
  a Dagger runner. Confirm the CI infrastructure supports one of these, or fall back
  to running `openedx build` directly in a node container (bypassing lehrer's Dagger
  wrapper for CI) and importing the dist via a lehrer git resource.
- **Rclone cache headers**: Confirm whether the existing rclone resource supports
  setting S3 metadata (`Cache-Control`) on sync, or whether a separate `aws s3 cp`
  command is needed for `index.html`.
- **Cross-deployment bucket access**: Confirm that the Concourse task IAM role has
  write access to all three deployment buckets (mitxonline, mitx, xpro) or whether
  separate role assumptions are needed.
