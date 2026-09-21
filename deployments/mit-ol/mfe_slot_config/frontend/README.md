# MIT OL OEP-65 Site Projects

This directory contains three **OEP-65 Site Projects** built on
[@openedx/frontend-base](https://github.com/openedx/frontend-base), one per
MIT OL deployment, plus a `shared/` directory of common TypeScript components.

## Structure

```
frontend/
├── dev-ports.yaml       ← host port each site's hot-reload dev server binds
├── shared/              ← shared TypeScript components (footer, header, styles, utils)
│   └── src/
│       ├── dev-hosts.json ← local-dev hostnames for every site in this deployment
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
| frontend-base version | latest alpha | `1.x` (Verawood) | `1.x` (Verawood) |
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

Only Dagger mounts it, though: `@shared/*` resolves to `./shared/src/*` *inside* the
Site Project, so `npm run dev` needs a local snapshot of this directory. Create or
refresh it with:

```bash
rm -rf ./shared && cp -R ../shared ./shared
```

Keep the `rm -rf`. A bare `cp -R ../shared ./shared` nests a second copy at
`./shared/shared/` once the snapshot exists rather than refreshing it, leaving the
stale sources in place — webpack keeps resolving those, so edits to the canonical
`frontend/shared/` appear to have no effect.

Currently contains:
- `dev-hosts.json` — the deployment's local-dev hostnames (`lmsBaseUrl` plus a
  `baseUrl` per site), imported by every `site.config.dev.tsx` and read by
  `lehrer dev check` and `lehrer-core.star`. Change a local-dev domain here and
  nowhere else. Not TypeScript, but it lives with the shared source because
  `shared/` is the only per-deployment directory Dagger mounts into a Site
  Project build.
- `footer/index.tsx` — `createMITOLFooterApp()`: runtime-config-driven footer links
- `header/index.tsx` — `createMITxOnlineHeaderApp()`, `createMITxHeaderApp()`, `createXProHeaderApp()`.
  The mitxonline app also hides the course number on UAI courses and keeps the Dashboard
  user-menu item to viewports at or below 991px, both matching the legacy learning header.
- `styles/mitxonline.scss` — mitxonline theme overrides (imported directly in each `site.config.*.tsx`)
- `styles/mitx.scss` — mitx theme overrides (scaffold)
- `utils/courseContext.ts` — URL/course-context detection helpers
- `ai-drawer/AIDrawerManagerSidebar.tsx` — fully typed AI drawer sidebar wrapper
- `ai-drawer/SidebarAIDrawerCoordinator.tsx` — stub, blocked on `frontend-app-learning` migration
- `course-tabs/ResponsiveCourseTabs.tsx` — stub, blocked on `frontend-app-learning` migration

## Module libraries wired in

| Deployment | Module library | npm version |
|---|---|---|
| mitxonline | `@openedx/frontend-app-instructor-dashboard` | `^2.0.0-alpha` |
| mitx | `@openedx/frontend-app-instructor-dashboard` | `1.x` |
| xpro | `@openedx/frontend-app-instructor-dashboard` | `mitodl/…#verawood` (see below) |

### Version lines

Which version a Site Project may use is decided by the edx-platform branch its
cells build from, not by what is newest.

Apps built on `frontend-base` are **never branched or tagged for an Open edX
release** — they declare `openedx.org/release: null` and participate by published
version only ([OEP-10 ADR 0003][adr3]). Only two branches publish:
`main` → the `alpha` dist-tag, which takes breaking changes with no DEPR process
and is explicitly not supported in production, and `stable` → `latest`.
`openedx/frontend-template-site` is the only frontend repo branched per release,
and ADR 0003 makes its `release/*` branch the authoritative record of which
frontend versions that release ships.

| edx-platform | instructor-dashboard | frontend-base | source |
|---|---|---|---|
| `master` | `^2.0.0-alpha` | `^2.0.0-alpha` | [`frontend-template-site@main`][ts-main] |
| `open-release/verawood` | `1.2.x` | `1.0.x` | [`frontend-template-site@release/verawood`][ts-vera] |

**mitx** and **xpro** build from `release/verawood`, so they follow the Verawood
row. They take the whole **`1.x`** line rather than template-site's exact `1.2.x`
— the major-line range the upstream README gives as the way for consumers to
select a maintained line. The major is the meaningful boundary: 2.x is published
from the app's `main` branch, which takes breaking changes with no DEPR process
and is not supported in production, and frontend-base 2 moves the whole site to
react-intl 10. Within 1.x, updates are ordinary reviewable bumps, and
`renovate.json` bounds them at `<2` for these two directories so crossing the
major stays a deliberate decision.

The cost of `1.x` over `1.2.x` is that these sites carry features published after
Verawood's frontend set was fixed. Both lockfiles resolve **1.3.0**, one minor ahead
of template-site's `1.2.x`, which adds CCX coach pages, the grading policy view and
Schedule — features that call LMS endpoints `release/verawood` may not serve. Nothing
in `shared/` or either site's `src/` registers against them, so they surface only as
upstream tabs that may fail against a Verawood backend. Narrow the range to `1.2.x`
if that turns out to matter; it resolves to 1.2.0, whose public API is identical.

Write a stable line as an explicit range (`1.x`), never as a caret on a prerelease:
`^1.1.0-alpha` expands to `>=1.1.0-alpha <2.0.0`, which is how mitx ended up on
1.3.0 without anyone choosing it (#206). A prerelease line is the exception and has
to stay a caret — npm excludes prereleases from a range that does not name one, so a
bare `2.x` matches no published `frontend-base` version at all, while `^2.0.0-alpha`
admits the alpha line.

[adr3]: https://docs.openedx.org/projects/openedx-proposals/en/latest/processes/oep-0010/decisions/0003-frontend-release-strategy.html
[ts-main]: https://github.com/openedx/frontend-template-site/blob/main/package.json
[ts-vera]: https://github.com/openedx/frontend-template-site/blob/release/verawood/package.json

### Fork pin: xpro instructor-dashboard (Verawood line)

xpro builds the instructor dashboard from `mitodl/frontend-app-instructor-dashboard`
instead of npm, tracking that fork's `verawood` branch (currently at commit `7d6de02`).
That branch is upstream `v1.2.0` (commit `272b8290`, which is the `gitHead` npm records
for the published `1.2.0`, so it is the same code the Verawood line ships) plus two
Course Team fixes needed to unblock Verawood CI testing:

- inactive accounts are reported instead of silently skipped
- failures with no reason attached raise an alert instead of closing the modal quietly

Upstream PR: https://github.com/openedx/frontend-app-instructor-dashboard/pull/234
Issue: https://github.com/mitodl/hq/issues/13068

The branch also carries a `prepare` script, which the published package does not need: npm runs
`prepare` rather than `prepack` for a git dependency, and without it the install produces no
`dist/` and the site build fails on the package's `"."` export.

The dependency names the branch, not a commit. `package-lock.json` still records the
commit it resolved, so an install is reproducible and a re-resolution shows as a lockfile
diff — but Renovate's weekly lock file maintenance deletes the lockfile and re-resolves,
so a commit pushed to the fork's `verawood` branch is absorbed by that run rather than
arriving as a deliberate bump. Treat the branch as frozen, or name a commit instead, if
that matters.

**Merging upstream #234 is not on its own enough to retire this pin.** The fixes have to
reach npm on a line xpro can install. `stable` is the only 1.x line that publishes — there
is no `1.2.x` maintenance branch, and `1.2.1` exists solely as a git tag — so they arrive
either as `1.3.x` (if cherry-picked to `stable`) or only in `2.x`. Because xpro's
frontend-base range is `1.x`, a `1.3.x` publish **is** in range: at that point replace the
git pin with `"1.x"`, re-run `npm install` in `xpro/`, and delete this section. If the
fixes only ever land in `2.x`, the pin stays until xpro adopts a named release built on
frontend-base 2.

Meanwhile, if #234 merges and xpro needs it on Verawood before any of that, rebase the
fork branch on the tag the Verawood line is at plus the merged commit and push it to
`verawood`. `xpro/package.json` needs no edit; re-run `npm install` in `xpro/` so the
lockfile records the new commit.

## Deployment prerequisites

These Site Projects are **not self-contained** — the instructor-dashboard
integration depends on backend behaviour and runtime configuration that must be
in place in each target LMS environment. Verify all of the following before (or
alongside) deploying a build:

### 1. Backend plugins must provide the MFE filters + APIs

The Canvas, Rapid Responses and Course Sync Actions tabs and their data come entirely from the LMS:

| Capability | Provided by |
|---|---|
| "Canvas" / "Rapid Responses" tabs | `InstructorDashboardTabsRequested` filter steps in `ol_openedx_canvas_integration` / `ol_openedx_rapid_response_reports` |
| "Course Sync Actions" tab | an `InstructorDashboardTabsRequested` filter step in `ol_openedx_course_sync`, emitted only for platform staff on courses that are an active sync source |
| Canvas task status (`list_canvas_tasks`), rapid-response runs (`rapid_response_runs`) | endpoints in those same plugins |
| Course Sync Actions problem endpoint (`sync_problem_actions`) | endpoint in `ol_openedx_course_sync`, gated on `is_staff` |
| Tab href routing | the filters emit `/apps/instructor-dashboard/<course>/<tab>` to match the `wrapWithAppsPath` routing |

These live in **mitodl/open-edx-plugins** and are pinned in the `mitx`/`mitx-staging`/
`mitxonline` cells' `packages` in `deployments/mit-ol/build_manifest.yaml`:
`ol-openedx-canvas-integration==0.8.0` and `ol-openedx-rapid-response-reports==0.5.0`
are the first releases that carry this work. With older versions the tabs simply do
not appear and the data endpoints 404. (Canvas/Rapid Responses are installed only
on `mitx*` and `mitxonline`, not `xpro`.)

Course Sync Actions needs `ol-openedx-course-sync==1.2.0` or later, which is the first
release carrying its filter step and endpoint; the pin is currently `1.0.1`. It is
registered only in the `mitxonline` Site Project, since that is the only deployment
running the plugin.

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
Each key has a built-in fallback, so a deployment that omits one still renders —
just not correctly:

- `commonAppConfig.mitolHeader.mitLearnBaseUrl` / `marketingSiteBaseUrl` →
  fall back to `https://learn.mit.edu` / `lmsBaseUrl`, which sends the Dashboard
  button to production MIT Learn and Profile / Settings to the LMS instead of the
  marketing site.
- `commonAppConfig.mitolFooter.footerLogoUrl` / `footerLogoDestination` →
  footer logo falls back to `headerLogoImageUrl` and renders without a link. For
  mitxonline that fallback is drawn `fill="white"` for the dark header, so it is
  invisible on the light footer and the footer reads as having no logo.

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
