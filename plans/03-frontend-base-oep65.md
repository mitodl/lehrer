# Implementation: Frontend-Base / OEP-65 MFE Migration

## Context

The Open edX frontend is migrating from the legacy micro-frontend architecture — where each
`frontend-app-*` repository is an independently built and deployed standalone SPA — to the
OEP-65 module architecture implemented in `@openedx/frontend-base`. In the new architecture,
a single **Shell** (provided by `frontend-base`) owns initialisation, the header and footer,
and shared dependencies (React, Paragon, etc.). Individual MFE repositories become
**module libraries** whose application modules are loaded into the Shell either at build time
(imported modules, bundled together) or at runtime (federated modules, loaded via webpack
module federation). Operators create a **Site Project** — an operator-owned repository with
a `site.config.tsx` — which is the single build input instead of individual MFE repos.

This plan implements the three stub functions added to `OpenedxMfe` in Phase 1
(`build_site`, `build_federated_module`, `watch_site`) and creates MIT OL's Site Project
under `deployments/mit-ol/frontend/`. It assumes Phase 1 is complete and all OL legacy MFE
builds continue to work via `build_legacy` during and after this migration.

## Prerequisites

- Phase 1 structural refactor complete (`plans/01-structural-refactor.md` all tasks done)
- `src/lehrer/core/mfe.py` contains the three `NotImplementedError` stubs from Phase 1 Task 5
- `deployments/mit-ol/mfe_slot_config/frontend/` placeholder directory exists
- Familiarity with the OEP-65 ADRs:
  - [OEP-65](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065-arch-frontend-composability.html)
  - [ADR 0001 — Unified platform repository (frontend-base)](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065/decisions/0001-unified-platform-repository.html)
  - [ADR 0002 — Frontend app migrations](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065/decisions/0002-frontend-app-migrations.html)
  - [ADR 0003 — Frontend Projects](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065/decisions/0003-frontend-projects.html)
- `@openedx/frontend-base` repository reviewed: https://github.com/openedx/frontend-base
  (⚠️ still pre-alpha / active development as of mid-2025; verify API stability before
  beginning Task 1)

## Terminology (OEP-65 glossary)

| Term | Meaning |
|---|---|
| **Shell** | The runtime host application provided by `@openedx/frontend-base`; owns init, header, footer, and shared deps |
| **Module library** | A migrated `frontend-app-*` repo; exports application modules, no longer a standalone app |
| **Site Project** | Operator-owned repo with `site.config.tsx`; the build input for an imported or linked site |
| **Module Project** | Operator-owned repo for building federated module remotes independently |
| **Imported module** | Module bundled into the Site at build time (static, single deployable) |
| **Federated module** | Module loaded at runtime via webpack module federation (independently deployable) |
| **`openedx` CLI** | The build/dev CLI provided by `@openedx/frontend-base`, replacing `fedx-scripts` |

## Architecture: what changes for lehrer

### Legacy model (current, `build_legacy`)

```
frontend-app-learning/     ← cloned, slot config injected, `npm run build`
  → dist/                  ← deployed as static files

frontend-app-account/      ← separate clone, separate build, separate deployment
  → dist/

... (one clone + build + deployment per MFE)
```

### OEP-65 model (`build_site` + optional `build_federated_module`)

```
mit-ol-site-project/       ← operator-owned Site Project
  site.config.tsx          ← declares which modules to import/federate
  package.json             ← depends on @openedx/frontend-base + module libraries
  src/                     ← operator's custom module overrides (previously slot configs)
  → `openedx build`
  → dist/                  ← ONE deployable containing Shell + all imported modules

frontend-app-learning/     ← (optional) built separately as a federated remote
  → `openedx build:module`
  → dist/remoteEntry.js + chunks  ← deployed to its own CDN path
```

The **slot config files** in `deployments/mit-ol/mfe_slot_config/legacy/` (Footer.jsx,
env.config.jsx, per-MFE plugin slot registrations) are replaced by:
- Operator module overrides in the Site Project's `src/` directory
- Plugin slot configuration in `site.config.tsx` using the `@openedx/frontend-base`
  plugin slot API (which absorbs and replaces `@openedx/frontend-plugin-framework`)

## Task status

| Task | Status |
|---|---|
| 1 — API audit | ✅ Done — `deployments/mit-ol/mfe_slot_config/frontend/mitxonline/AUDIT.md` |
| 2 — `build_site` | ✅ Done |
| 3 — `build_federated_module` | ✅ Done (raises `NotImplementedError`; `openedx build:module` does not exist yet) |
| 4 — `watch_site` | ✅ Done |
| 5 — Site Project skeleton | ✅ Done — three separate Site Projects (mitxonline, mitx, xpro) under `deployments/mit-ol/mfe_slot_config/frontend/` |
| 6 — Slot config migration | ✅ Done — footer + header user-menu/logo/secondary-links + SCSS theme style loaders complete; learning slots documented as stubs blocked on frontend-app-learning |
| 7 — Docs update | ✅ Done — updated `docs/creating-a-deployment.md` with `build-site`/`watch-site` parameter additions and OEP-65 documentation |
| 8 — Concourse + Fastly | ❌ Not started — see `plans/04-concourse-fastly-deployment.md` |

---

## Tasks

---

### Task 1 — Audit `@openedx/frontend-base` API stability and CLI commands

Before writing any Dagger code, verify the current state of `frontend-base`:

1. Check the latest release tag at https://github.com/openedx/frontend-base/releases
   and confirm the `openedx` CLI commands (`build`, `build:module`, `dev`, `serve`)
   are present and documented.
2. Verify the `site.config.tsx` schema — the file the Shell imports as its entry point.
   Confirm the required exports (at minimum: `modules`, `apps`, or equivalent top-level
   config keys).
3. Identify the minimum Node.js version required (expected: Node 22; verify in `package.json`
   `engines` field).
4. Check whether `openedx build` produces a `dist/` directory or a different output path.
5. Note any breaking changes since the pre-alpha warning was added.

Produce `deployments/mit-ol/frontend/AUDIT.md` summarising findings, the version pinned,
and any API surface that differs from the descriptions in ADR 0003.

**Done condition:** `AUDIT.md` exists with the verified `openedx` CLI command signatures,
the `site.config.tsx` required structure, and the Node version. This is the source of truth
for Tasks 2–4. *No code changes in this task.*

**Status: ✅ Done.** Results in `deployments/mit-ol/mfe_slot_config/frontend/mitxonline/AUDIT.md`.
Version pinned: `@openedx/frontend-base@1.0.0-alpha.41`. Node 24 required (not 22).
Two config files needed: `site.config.build.tsx` + `site.config.dev.tsx`. Output path: `dist/`.

---

### Task 2 — Implement `build_site()` in `core/mfe.py`

Replace the `build_site()` stub with a working implementation. The function must:

1. Start from `node:{node_version}-trixie-slim`
2. Install system deps (`git`, `build-essential`, `python3`, `python-is-python3`)
3. Mount `site_project` at `/app/site`
4. Set working directory to `/app/site`
5. Run `npm install` (installs `@openedx/frontend-base` and module library deps)
6. Run `npx openedx build` (or equivalent; verify exact command from Task 1 audit)
7. Return `container.directory("/app/site/dist")` (verify output path from Task 1 audit)

Function signature (confirmed from Phase 1 stub):

```python
@function
async def build_site(
    self,
    site_project: dagger.Directory,
    node_version: str = "22",
) -> dagger.Directory:
```

The `site_project` directory is the complete Site Project including `package.json`,
`site.config.tsx`, and any `src/` overrides. It is provided by the caller (not fetched
by lehrer). This keeps the function pure and composable: callers can pass a local
directory or a git-cloned directory from another Dagger function.

Note: `build_site` does NOT clone any repos. The caller is responsible for assembling
the Site Project directory before passing it in. If a caller needs to pull module libraries
from git, they should use standard Dagger directory operations upstream of this call.

**Done condition:** `dagger call mfe build-site --site-project ./deployments/mit-ol/frontend --help`
shows the live docstring (not the `NotImplementedError` stub). A test Site Project
(minimal `package.json` + `site.config.tsx`) builds without error. *Depends on Task 1.*

**Status: ✅ Done.** Implemented in `src/lehrer/core/mfe.py`. Accepts `--shared-src` optional
`dagger.Directory` mounted at `/app/site/shared/` (aliased as `@shared/*` in tsconfig).
All three Site Projects build successfully via `dagger call mfe build-site`.

**Outstanding**: `--public-path` parameter not yet added. Required for Concourse/S3 deployment.
See `plans/04-concourse-fastly-deployment.md`.

---

### Task 3 — Implement `build_federated_module()` in `core/mfe.py`

Replace the `build_federated_module()` stub with a working implementation.

The function must:
1. Start from `node:{node_version}-trixie-slim` with same system deps as `build_site`
2. Mount `module_project` at `/app/module`
3. Set working directory to `/app/module`
4. Run `npm install`
5. Run `npx openedx build:module` (verify exact command from Task 1 audit)
6. Return the output directory containing `remoteEntry.js` and chunk files
   (verify path from Task 1 audit; likely `dist/`)

Federated modules are deployed separately from the Shell site, typically to a versioned
CDN path. The Shell's `site.config.tsx` references the federated module's `remoteEntry.js`
URL at runtime.

**Done condition:** `dagger call mfe build-federated-module --module-project ./test-module`
runs without error against a minimal Module Project. *Depends on Task 1.*

**Status: ✅ Done (blocked upstream).** Raises `NotImplementedError` with a message explaining
that `openedx build:module` does not exist in `@openedx/frontend-base` as of v1.0.0-alpha.41.
Module libraries are currently bundled at build time into the Site Project (imported modules);
runtime federated remotes are not yet supported upstream. Revisit when upstream ships the CLI command.

---

### Task 4 — Implement `watch_site()` in `core/mfe.py`

Replace the `watch_site()` stub with a working implementation.

The function must:
1. Same base setup as `build_site`
2. Run `npx openedx dev` (or `npm run dev`; verify from Task 1 audit) instead of `build`
3. Expose `port` (default 8080) via `container.with_exposed_port(port)`
4. Return `container.as_service()`

**Done condition:** `dagger call mfe watch-site --site-project ./deployments/mit-ol/frontend up --ports 8080:8080`
starts a dev server accessible at `http://localhost:8080`. *Depends on Task 1.*

**Status: ✅ Done.** Implemented in `src/lehrer/core/mfe.py`. Accepts same parameters as
`build_site`. Runs `npx openedx dev` and returns a `dagger.Service`.

---

### Task 5 — Create the MIT OL Site Project skeleton

Create the OEP-65 Site Project for MIT OL under `deployments/mit-ol/frontend/`.

This is the Site Project that replaces the legacy per-MFE builds for OL's deployments.

Minimum viable structure:
```
deployments/mit-ol/frontend/
├── package.json            ← declares @openedx/frontend-base + module library deps
├── site.config.tsx         ← imports modules, configures plugin slots
├── src/                    ← OL's custom module overrides
│   ├── Footer.tsx          ← migrated from legacy/Footer.jsx
│   └── ...
├── .gitignore              ← ignores node_modules/, dist/, .env*
└── README.md
```

**`package.json` scaffold:**
```json
{
  "name": "@mitodl/openedx-site",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "build": "openedx build",
    "build:module": "openedx build:module",
    "dev": "openedx dev",
    "serve": "openedx serve"
  },
  "dependencies": {
    "@openedx/frontend-base": "^<version from Task 1 audit>",
    "@openedx/frontend-app-learning": "<version>",
    "@openedx/frontend-app-account": "<version>"
  }
}
```

**`site.config.tsx` scaffold** (exact API from Task 1 audit):
```tsx
// site.config.tsx — MIT OL Site Project configuration
// See: plans/03-frontend-base-oep65.md for migration notes

import type { SiteConfig } from '@openedx/frontend-base';

// TODO: import OL module libraries as they are migrated to OEP-65
// import { LearningModule } from '@openedx/frontend-app-learning';

const config: SiteConfig = {
  // modules: [LearningModule],   // uncomment as modules are migrated
  pluginSlots: {
    // Migrate plugin slot registrations from:
    // deployments/mit-ol/mfe_slot_config/legacy/learning-mfe-config.env.jsx
    // and deployments/mit-ol/mfe_slot_config/legacy/*/common-mfe-config.env.jsx
  },
};

export default config;
```

**Migration mapping** — document in `README.md` the correspondence between legacy slot
config files and their new locations in the Site Project:

| Legacy file | OEP-65 equivalent |
|---|---|
| `legacy/Footer.jsx` | `src/Footer.tsx` (custom Shell footer override) |
| `legacy/learning-mfe-config.env.jsx` | plugin slot entries in `site.config.tsx` |
| `legacy/mitxonline/common-mfe-config.env.jsx` | environment-specific config in `site.config.tsx` |
| `legacy/AIDrawerManagerSidebar.jsx` | `src/AIDrawerManagerSidebar.tsx` |
| `legacy/SidebarAIDrawerCoordinator.jsx` | `src/SidebarAIDrawerCoordinator.tsx` |
| `legacy/mitxonline-styles.scss` | CSS override mechanism in `@openedx/frontend-base` (verify API) |

**Done condition:** The Site Project directory exists with `package.json`, `site.config.tsx`,
`src/Footer.tsx` (migrated from legacy), and a `README.md` with the migration mapping table.
`npm install` inside the directory completes without error. *Depends on Task 1.*

**Status: ✅ Done.** Three Site Projects created: `mitxonline/`, `mitx/`, `xpro/` under
`deployments/mit-ol/mfe_slot_config/frontend/`. Shared components in `shared/src/`.
Decision: Option C hybrid — three separate Site Projects (not one monolithic config).
`@openedx/frontend-app-instructor-dashboard` wired into all three as the first module library.
Runtime config via `runtimeConfigJsonUrl: "/api/frontend_site_config/v1/"` — site configs are
environment-agnostic; all URL/cookie config comes from the LMS at startup.

---

### Task 6 — Migrate OL legacy slot configs to the Site Project

**Status: 🔶 Partial.**
- Footer: ✅ `shared/src/footer/index.tsx`
- `AIDrawerManagerSidebar`: ✅ `shared/src/ai-drawer/AIDrawerManagerSidebar.tsx`
- `SidebarAIDrawerCoordinator`: ✅ stub at `shared/src/ai-drawer/SidebarAIDrawerCoordinator.tsx` (see note below)
- Header user-menu / logo / secondary links: ✅ `shared/src/header/index.tsx` (`createMITxOnlineHeaderApp`, `createMITxHeaderApp`, `createXProHeaderApp`)
- All three site configs updated to include deployment-specific header App
- `externalLinkUrlOverrides` (proctoring link override): ✅ added to `mitxonline/site.config.build.tsx`
- Learning-MFE slot operations (6d) and remaining 6e items: ❌ blocked on `frontend-app-learning` module library migration

Remaining migrations are documented below.

**Source files** (canonical in `ol-infrastructure`, NOT in lehrer):
```
ol-infrastructure/src/bridge/settings/openedx/mfe/slot_config/
  Footer.jsx                    ← MIGRATED (footer slot app in shared/src/footer/)
  AIDrawerManagerSidebar.jsx    ← MIGRATED (shared/src/ai-drawer/AIDrawerManagerSidebar.tsx)
  SidebarAIDrawerCoordinator.jsx ← STUB (blocked: needs frontend-app-learning)
  ResponsiveCourseTabs.jsx      ← not present in legacy dir; skip
  learning-mfe-config.env.jsx   ← partial: HIDE ops done; component-based ops blocked on frontend-app-learning
  mitxonline/common-mfe-config.env.jsx  ← partial: footer ✅, header user-menu/logo/secondary ✅, per-app conditionals pending module libraries
  mitx/common-mfe-config.env.jsx        ← partial: footer ✅, header user-menu ✅
  mitx-staging/common-mfe-config.env.jsx ← same as mitx (same Site Project)
  xpro/common-mfe-config.env.jsx         ← partial: footer ✅, header user-menu ✅, cert status blocked on frontend-app-learning
```

#### API mapping: legacy → frontend-base (verified against alpha.49)

**⚠️ Critical finding:** The slot IDs in the 6e section below (`org.openedx.frontend.layout.header_logo.v1` etc.) are from the OLD `frontend-app-header` and **do not exist** in `@openedx/frontend-base`. The actual slot IDs are in the verified table below; `shared/src/header/index.tsx` uses the correct IDs.

| Legacy import | frontend-base equivalent |
|---|---|
| `@edx/frontend-platform` `getConfig()` | `getSiteConfig()` or `useSiteConfig()` hook |
| `@edx/frontend-platform/react` `AppContext.authenticatedUser` | `useAuthenticatedUser()` hook |
| `@edx/frontend-platform/auth` `getAuthenticatedHttpClient` | `getAuthenticatedHttpClient` from `@openedx/frontend-base` |
| `@edx/frontend-platform/i18n` `useIntl`, `FormattedMessage` | Same — from `@openedx/frontend-base` |
| `@openedx/frontend-plugin-framework` `PLUGIN_OPERATIONS.Insert` | `WidgetOperationTypes.APPEND` or `PREPEND` |
| `PLUGIN_OPERATIONS.Hide` (widgetId) | `WidgetOperationTypes.REMOVE` with `relatedId: widgetId` |
| `PLUGIN_OPERATIONS.Modify` (fn) | No direct equivalent — REPLACE widget with custom component; `WidgetOperationTypes.OPTIONS` for options-only |
| `type: DIRECT_PLUGIN, RenderWidget: () => <.../>` | `component: MyComponent` |
| `process.env.VARIABLE` | `useSiteConfig().commonAppConfig.VARIABLE` |
| `configData.APP_ID` | `SlotOperation.condition: { active: ['<route-role>'] }` — applies only when a route with that role is active |

#### Verified frontend-base header slot and widget IDs (from `package/dist/shell/header/app.js`)

| Slot ID | Default widget IDs |
|---|---|
| `org.openedx.frontend.slot.header.desktopLeft.v1` | `desktopLogo.v1`, `desktopPrimaryLinks.v1` |
| `org.openedx.frontend.slot.header.desktopRight.v1` | `desktopSecondaryLinks.v1`, `desktopAuthenticatedMenu.v1`, `desktopAnonymousMenu.v1` |
| `org.openedx.frontend.slot.header.mobileCenter.v1` | `mobileLogo.v1` |
| `org.openedx.frontend.slot.header.mobileRight.v1` | `mobileAuthenticatedMenu.v1`, `mobileAnonymousMenu.v1` |
| `org.openedx.frontend.slot.header.secondaryLinks.v1` | (empty; help button also appended here) |
| `org.openedx.frontend.slot.header.authenticatedMenu.v1` | `desktopAuthenticatedMenuProfile.v1`, `desktopAuthenticatedMenuAccount.v1`, `desktopAuthenticatedMenuLogout.v1` |
| `org.openedx.frontend.slot.footer.desktopCenterLink1.v1`–4 | (empty; LabeledLinkColumn layout) |
| `org.openedx.frontend.slot.footer.desktopLegalNotices.v1` | `desktopCopyrightNotice.v1` |

Widget ID full prefix: `org.openedx.frontend.widget.header.` or `org.openedx.frontend.widget.footer.`

**Critical note on `APP_ID` conditional logic**: The legacy configs check
`configData.APP_ID` at runtime to apply different slot operations per MFE (e.g.,
different user menu for `learning` vs `gradebook`). In frontend-base, this is done at
build time by adding slot operations to specific `App` objects in `site.config.*.tsx`
rather than checking app ID at runtime. Each `App` in `apps[]` can have its own
`slots[]` array that only applies when that app is active.

**Critical note on `process.env.*` reads in slot components**: In the legacy config,
slot components read `process.env.MIT_LEARN_BASE_URL`, `process.env.SUPPORT_URL`, etc.
In frontend-base, these values must come from `useSiteConfig().commonAppConfig` (populated
via `FRONTEND_SITE_CONFIG` in the LMS). Add the necessary keys to the `mitolFooter` or
a new `mitolHeader` namespace in `FRONTEND_SITE_CONFIG.commonAppConfig` in
`ol-infrastructure/k8s_configmaps.py`. See `shared/src/footer/index.tsx` for the pattern.

#### 6a — `AIDrawerManagerSidebar.jsx` → `shared/src/ai-drawer/AIDrawerManagerSidebar.tsx` ✅

Migrated. Key changes:
- `getConfig().LMS_BASE_URL` → `useSiteConfig().lmsBaseUrl`
- `getAuthenticatedHttpClient` → from `@openedx/frontend-base`
- `process.env.AI_DRAWER_BUNDLE_PATH` → `useSiteConfig().commonAppConfig.mitolAIDrawer` (optional)
- Full TypeScript types added.

#### 6b — `SidebarAIDrawerCoordinator.jsx` → `shared/src/ai-drawer/SidebarAIDrawerCoordinator.tsx` ✅ (stub)

Cannot be fully ported. The component is tightly coupled to `frontend-app-learning` internals:
- `SidebarContext`, `NewSidebarContext`, `Sidebar`, `NewSidebar` — internal components
- `useModel('courseHomeMeta', courseId)` — internal model store

When `frontend-app-learning` is migrated to a module library, the slot operation for
`org.openedx.frontend.learning.notifications_discussions_sidebar.v1` should live inside
the learning app's own slot definitions, not in shared/. A stub file documents this
dependency at `shared/src/ai-drawer/SidebarAIDrawerCoordinator.tsx`.

#### 6c — `ResponsiveCourseTabs.jsx` → `shared/src/course-tabs/ResponsiveCourseTabs.tsx`

Check for any `@edx/frontend-platform` imports and replace per the mapping table above.

#### 6d — `learning-mfe-config.env.jsx` → per-deployment `site.config.*.tsx` slots

This file adds slot operations **only for mitxonline** (gated by `DEPLOYMENT_NAME.includes("mitxonline")`)
plus unconditional AI drawer initialization and responsive tabs. The AI drawer feature flag
(`ENABLE_AI_DRAWER_SLOT`) must come from `useSiteConfig().commonAppConfig.ENABLE_AI_DRAWER_SLOT`
(add to `FRONTEND_SITE_CONFIG` in `k8s_configmaps.py` — currently `False` for all deployments,
`True` only when the AI drawer is enabled per-environment via Pulumi config).

Slot operations to add to **`mitxonline/site.config.build.tsx`** `apps[]` (inside the
`instructorDashboardApp` App or as a new `mitolLearningApp` App object):

```
Slot ID                                                    | Operation  | What it does
---------------------------------------------------------------------------
org.openedx.frontend.learning.course_breadcrumbs.v1        | APPEND     | CourseBreadcrumbs component (mitxonline only)
org.openedx.frontend.learning.sequence_navigation.v1       | APPEND     | SequenceNavigation component (mitxonline only)
org.openedx.frontend.learning.course_outline_sidebar.v1    | HIDE       | Hide default sidebar (mitxonline only)
org.openedx.frontend.learning.unit_title.v1                | APPEND     | Custom unit title + BookmarkButton (mitxonline only)
org.openedx.frontend.learning.course_outline_sidebar_trigger.v1      | HIDE |
org.openedx.frontend.learning.course_outline_mobile_sidebar_trigger.v1 | HIDE |
org.openedx.frontend.learning.course_tab_links.v1          | APPEND     | ResponsiveCourseTabs (all deployments)
org.openedx.frontend.learning.notifications_discussions_sidebar.v1 | APPEND | SidebarAIDrawerCoordinator (mitxonline, when ENABLE_AI_DRAWER_SLOT=true)
```

The `CourseBreadcrumbs`, `SequenceNavigation`, `BookmarkButton` components are internal
to `@openedx/frontend-app-learning`. Check whether they are exported from the package's
public API before importing them directly — if not, they must be copied into `shared/src/`.

The AI drawer JS initialization (`/learn/static/smoot-design/aiDrawerManager.es.js`
dynamic import) is a side effect that currently runs at module load time. In frontend-base,
place it in a component registered with `WidgetOperationTypes.APPEND` on a shell-level
slot (e.g., `org.openedx.frontend.slot.shell.head.v1` or equivalent) so it runs once on
app startup regardless of which MFE is active. Read the `messageOrigin` from
`useSiteConfig().lmsBaseUrl`.

#### 6e — `mitxonline/common-mfe-config.env.jsx` → per-deployment site configs and shared components

This is the most complex file. Break it into discrete concerns:

**Footer** — ✅ Already migrated to `shared/src/footer/index.tsx`.

**Header slot overrides** — Add to a new `mitolHeaderApp` App in `shared/src/header/index.tsx` (already fully migrated).

**Style overrides & SCSS loader** — ✅ Already migrated. Styles are structured inside `shared/src/styles/mitxonline.scss` and `shared/src/styles/mitx.scss` (copied directly from the legacy SCSS). A shared helper app `createStyleOverrideApp(stylesheetPath)` inside `shared/src/styles/styleLoader.tsx` registers a slot operation that appends a style loader component to the core Shell head slot `org.openedx.frontend.slot.shell.head.v1`. When the shell is initialized, the corresponding style file is dynamically imported and injected onto the page.

The individual Site Projects for `mitxonline`, `mitx`, and `xpro` include this styled loader in their respective `site.config.build.tsx` configurations.

**URL reads**: `process.env.MIT_LEARN_BASE_URL`, `process.env.MARKETING_SITE_BASE_URL`, etc.

#### 6f — `mitx/`, `mitx-staging/`, `xpro/` `common-mfe-config.env.jsx`

These follow the same pattern as the mitxonline file but are smaller. Differences:
- No `isMITxOnlineCourse()` / UAI course-key detection (those are mitxonline-specific)
- Different URL domains
- xpro has no AI drawer slot
- Migrate after mitxonline is validated

**Done condition (Task 6):** All slot config logic from the legacy files has an OEP-65
equivalent in the Site Projects. Each Site Project builds without error. The legacy
`ol-infrastructure` slot config files are annotated with `# MIGRATED` comments
(do not delete until `build_legacy` is decommissioned).

---

### Task 7 — Update `docs/creating-a-deployment.md` with OEP-65 section

Add an **OEP-65 / frontend-base** section to `docs/creating-a-deployment.md` covering:

1. The two MFE build models and when to use each
2. `build_site` parameters and what a Site Project must contain
3. `build_federated_module` parameters and the Module Project layout
4. `watch_site` for local development
5. An end-to-end example: `dagger call mfe build-site --site-project ./my-site-project export --path ./dist`
6. Migration guidance: how to move from `build_legacy` to `build_site`
   (legacy remains available indefinitely for operators still on older releases)

**Done condition:** The OEP-65 section exists in the doc, includes at least one
end-to-end `dagger call` example, and links to the `deployments/mit-ol/frontend/`
directory as a reference Site Project. *Depends on Tasks 2, 5.*

**Status: 🔶 Partial.** `docs/creating-a-deployment.md` updated:
- `build-site` / `watch-site` parameter tables added
- MIT OL reference examples in `deployments/mit-ol/build.md` section 6
- "OEP-65 stubs" language removed from the MFE table

Still needed: full narrative OEP-65 section explaining the two build models,
migration guidance, and Site Project layout requirements.

## Open Questions

❓ **`frontend-base` pre-alpha stability** — as of mid-2025 the repository carries a
prominent "active development / may change significantly" warning. Task 1's API audit
is essential; if the `openedx build` CLI command or `site.config.tsx` schema are still
unstable, Tasks 2–4 should be deferred until a stable release is tagged. The stubs from
Phase 1 are sufficient in the interim.

❓ **Per-deployment vs per-environment Site Projects** — MIT OL currently has distinct
slot configs for `mitxonline`, `mitx`, and `mitx-staging` (and `xpro`). In OEP-65 this
could be:
  - **One Site Project per deployment** (three Site Projects): cleanest isolation, more
    build processes
  - **One Site Project with environment branches/flags**: single build input, config
    controlled by environment variables at build time or runtime
Decide before Task 5 — the `package.json` and `site.config.tsx` structure differs significantly
between these approaches.

❓ **Federated vs imported modules** — for OL's initial rollout, decide whether MFEs
are imported (bundled with Shell, one deployment artifact) or federated (loaded at runtime,
independently deployable). Federated offers more flexibility for independent MFE deployments
but requires a more complex CDN/routing setup and the `build_federated_module` path.
Imported is simpler to operate initially. This decision affects Task 5's `site.config.tsx`
structure.

❓ **`build_legacy` decommission timeline** — once the Site Project is in production,
`build_legacy` (and the legacy slot config files) can be retired. Set a deprecation
timeline tied to the Open edX release when `frontend-base` reaches stable status for
the releases OL is on.
