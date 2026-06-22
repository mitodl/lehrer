# MIT OL OEP-65 Site Projects

This directory contains three **OEP-65 Site Projects** built on
[@openedx/frontend-base](https://github.com/openedx/frontend-base), one per
MIT OL deployment, plus a `shared/` directory of common TypeScript components.

## Structure

```
frontend/
├── shared/              ← shared TypeScript components (footer, header, styles, utils)
│   └── src/
│       ├── footer/      ← createMITOLFooterApp()
│       ├── header/      ← createMITxOnlineHeaderApp(), createMITxHeaderApp(), createXProHeaderApp()
│       ├── styles/      ← mitxonline.scss, mitx.scss (imported directly by each site config)
│       ├── utils/       ← courseContext helpers
│       └── ai-drawer/   ← AIDrawerManagerSidebar, SidebarAIDrawerCoordinator stubs
├── mitxonline/          ← MIT OpenLearning (master branch, latest frontend-base)
├── mitx/                ← MITx + MITx-Staging (named releases, same build artifact)
└── xpro/                ← MIT xPRO (named releases, MARKETING_SITE_BASE_URL nav model)
```

Each project directory contains:
- `package.json` — own dependency pins (allows independent `@openedx/frontend-base` versions)
- `site.config.build.tsx` — production site config
- `site.config.dev.tsx` — development site config
- `tsconfig.json` — extends frontend-base tsconfig; `@shared/*` alias for shared components
- `src/` — deployment-specific overrides (styles, slot registrations)
- `AUDIT.md` — API findings (mitxonline only; see mitxonline/AUDIT.md)

## Why three projects?

| | mitxonline | mitx | xpro |
|---|---|---|---|
| edx-platform branch | master | named release | named release |
| frontend-base version | latest alpha | pinned to release | pinned to release |
| Structural differences | AI drawer, UAI course logic, 57 plugin ops | 26 plugin ops | MARKETING_SITE_BASE_URL nav model |
| mitx-staging | — | same build, runtime config supplies staging URLs | — |

`mitxonline` and `xpro` differ structurally — different plugin slot registrations,
different navigation URL model. `mitx` and `mitx-staging` differ only in URLs,
handled at runtime via `runtimeConfigJsonUrl`.

## Building with lehrer

See `deployments/mit-ol/build.md` section 6 for copy-pasteable `dagger call` commands.

Quick reference:

```bash
# mitxonline production build
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend/mitxonline \
  --shared-src   ./deployments/mit-ol/mfe_slot_config/frontend/shared \
  export --path ./dist/mitxonline
```

## Shared components

Components in `shared/src/` are imported by any Site Project via the `@shared/*`
TypeScript path alias declared in each project's `tsconfig.json`. No npm publishing
required — Dagger mounts the directory at `/app/site/shared` inside each Site Project.

Currently contains:
- `footer/index.tsx` — `createMITOLFooterApp()`: runtime-config-driven footer links
- `header/index.tsx` — `createMITxOnlineHeaderApp()`, `createMITxHeaderApp()`, `createXProHeaderApp()`
- `styles/mitxonline.scss` — mitxonline theme overrides (imported directly in each `site.config.*.tsx`)
- `styles/mitx.scss` — mitx theme overrides (scaffold)
- `utils/courseContext.ts` — URL/course-context detection helpers
- `ai-drawer/AIDrawerManagerSidebar.tsx` — fully typed AI drawer sidebar wrapper
- `ai-drawer/SidebarAIDrawerCoordinator.tsx` — stub, blocked on `frontend-app-learning` migration
- `course-tabs/ResponsiveCourseTabs.tsx` — stub, blocked on `frontend-app-learning` migration

## Module libraries wired in

| Deployment | Module library | npm version |
|---|---|---|
| mitxonline | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |
| mitx | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |
| xpro | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |

## Deployment prerequisites

These Site Projects are **not self-contained** — the instructor-dashboard
integration depends on backend behaviour and runtime configuration that must be
in place in each target LMS environment. Verify all of the following before (or
alongside) deploying a build:

### 1. Backend plugins must provide the MFE filters + APIs

The Canvas and Rapid Responses tabs and their data come entirely from the LMS:

| Capability | Provided by |
|---|---|
| "Canvas" / "Rapid Responses" tabs | `InstructorDashboardTabsRequested` filter steps in `ol_openedx_canvas_integration` / `ol_openedx_rapid_response_reports` |
| Canvas task status (`list_canvas_tasks`), rapid-response runs (`rapid_response_runs`) | endpoints in those same plugins |
| Tab href routing | the filters emit `/apps/instructor-dashboard/<course>/<tab>` to match the `wrapWithAppsPath` routing |

These live in **mitodl/open-edx-plugins** and are pinned in
`deployments/mit-ol/pip_package_lists/*/{mitx,mitx-staging,mitxonline}.txt`:
`ol-openedx-canvas-integration==0.8.0` and `ol-openedx-rapid-response-reports==0.5.0`
are the first releases that carry this work. With older versions the tabs simply do
not appear and the data endpoints 404. (Canvas/Rapid Responses are installed only
on `mitx*` and `mitxonline`, not `xpro`.)

### 2. Runtime site config must be enabled and populated

Each Site Project sources `commonAppConfig` (header/footer URLs) at runtime via
`runtimeConfigJsonUrl: /api/frontend_site_config/v1/` rather than hardcoding it, so
the LMS must run with `ENABLE_MFE_CONFIG_API = True` and a populated
`FRONTEND_SITE_CONFIG`.

For the deployed (k8s) environments this is **already provisioned in
[ol-infrastructure]** — `src/ol_infrastructure/applications/edxapp/k8s_configmaps.py`
sets `ENABLE_MFE_CONFIG_API: True` and builds `FRONTEND_SITE_CONFIG` per deployment.
New deployments must include the equivalent block there.

The exact keys consumed by the MFE are in `shared/src/footer/index.tsx`
(`MITOLFooterConfig`) and `shared/src/header/index.tsx` (`MITOLHeaderConfig`).
Two of them are **not** set in ol-infrastructure today and rely on the components'
built-in fallbacks (acceptable, but set them there if you want explicit control):

- `commonAppConfig.mitolHeader.mitLearnBaseUrl` / `marketingSiteBaseUrl` →
  fall back to `https://learn.mit.edu` / `lmsBaseUrl`.
- `commonAppConfig.mitolFooter.footerLogoUrl` / `footerLogoDestination` →
  footer logo falls back to `headerLogoImageUrl` and renders without a link.

If `ENABLE_MFE_CONFIG_API` is off or `FRONTEND_SITE_CONFIG` is empty (e.g. a fresh
local LMS without the configmap), the header/footer render with empty links and
the default logo.

[ol-infrastructure]: https://github.com/mitodl/ol-infrastructure

## Relationship to legacy JSX files

Files in `../legacy/` are still used by `dagger call mfe build-legacy` and must
not be deleted until `build_legacy` is decommissioned. See `mitxonline/README.md`
for the full legacy → OEP-65 migration mapping table.

## References

- `mitxonline/AUDIT.md` — verified @openedx/frontend-base API findings
- `plans/03-frontend-base-oep65.md` — implementation guide
- [OEP-65](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065-arch-frontend-composability.html)
- [frontend-base repository](https://github.com/openedx/frontend-base)
- [frontend-app-instructor-dashboard](https://github.com/openedx/frontend-app-instructor-dashboard)
