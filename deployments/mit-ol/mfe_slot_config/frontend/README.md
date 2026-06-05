# MIT OL OEP-65 Site Projects

This directory contains three **OEP-65 Site Projects** built on
[@openedx/frontend-base](https://github.com/openedx/frontend-base), one per
MIT OL deployment, plus a `shared/` directory of common TypeScript components.

## Structure

```
frontend/
├── shared/              ← shared TypeScript components (Footer, AI drawer, etc.)
│   └── src/
│       └── Footer.tsx   ← scaffold — needs port from ../legacy/Footer.jsx
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
required — Dagger mounts the directory at `/app/shared` alongside each project.

Currently contains:
- `Footer.tsx` — **scaffold only**, needs TypeScript port from `../legacy/Footer.jsx`
  (see plan task: `plans/03-frontend-base-oep65.md` § Task 6)

## Module libraries wired in

| Deployment | Module library | npm version |
|---|---|---|
| mitxonline | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |
| mitx | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |
| xpro | `@openedx/frontend-app-instructor-dashboard` | `^1.0.0-alpha` |

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
