# MIT OL OEP-65 Site Project

> **Status:** Scaffold — `npm install` not yet run; module libraries not yet migrated.
> See `AUDIT.md` for API findings and `plans/03-frontend-base-oep65.md` for the full
> implementation guide.

This directory is MIT OL's **OEP-65 Site Project** built on
[@openedx/frontend-base](https://github.com/openedx/frontend-base).

In the OEP-65 model, a single Site Project replaces the per-MFE builds that
`dagger call mfe build-legacy` currently produces. The Shell (provided by
`@openedx/frontend-base`) bundles the header, footer, and all imported module
libraries into one deployable `dist/` artifact.

## Building with lehrer

```sh
# Production build
dagger call mfe build-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend \
  export --path ./dist

# Dev server
dagger call mfe watch-site \
  --site-project ./deployments/mit-ol/mfe_slot_config/frontend \
  up --ports 8080:8080
```

## Local development (outside Dagger)

```sh
npm install
npm run dev      # openedx dev — reads site.config.dev.tsx
npm run build    # openedx build — reads site.config.build.tsx
```

## Directory layout

```
frontend/
├── AUDIT.md                  ← @openedx/frontend-base API audit (2026-06-05)
├── package.json
├── tsconfig.json
├── site.config.build.tsx     ← production site config (PRODUCTION environment)
├── site.config.dev.tsx       ← development site config (DEVELOPMENT environment)
├── src/
│   └── Footer.tsx            ← MIT OL custom footer (scaffold — needs porting)
└── .gitignore
```

## Legacy slot config migration mapping

| Legacy file | OEP-65 equivalent | Status |
|---|---|---|
| `../legacy/Footer.jsx` | `src/Footer.tsx` | Moved to shared: `shared/src/footer/index.tsx` |
| `../legacy/learning-mfe-config.env.jsx` | plugin slot entries in `site.config.build.tsx` | HIDE operations completed; custom widgets blocked on frontend-app-learning |
| `../legacy/mitxonline/common-mfe-config.env.jsx` | environment-specific config in `site.config.build.tsx` | Complete — Header apps, custom user menu overrides, and dashboard routing verified |
| `../legacy/mitx/common-mfe-config.env.jsx` | separate Site Project or runtime config | Complete — custom Header application injected |
| `../legacy/mitx-staging/common-mfe-config.env.jsx` | separate Site Project or runtime config | Complete — maps to mitx Site Project config |
| `../legacy/AIDrawerManagerSidebar.jsx` | `src/AIDrawerManagerSidebar.tsx` | Complete — `shared/src/ai-drawer/AIDrawerManagerSidebar.tsx` fully typed and migrated |
| `../legacy/SidebarAIDrawerCoordinator.jsx` | `src/SidebarAIDrawerCoordinator.tsx` | Documented typescript stub created in shared (blocked on frontend-app-learning) |
| `../legacy/mitxonline-styles.scss` | CSS override via frontend-base theme API (verify) | Complete — loaded dynamically using `createStyleOverrideApp` from `shared/src/styles/` |
| `../legacy/mitx-styles.scss` | CSS override via frontend-base theme API (verify) | Complete — loaded dynamically using `createStyleOverrideApp` from `shared/src/styles/` |

> The files in `../legacy/` remain in use by `dagger call mfe build-legacy` and
> must not be deleted until `build_legacy` is decommissioned.

## Open questions (from plans/03-frontend-base-oep65.md)

- **One Site Project per deployment vs one with env branches** — mitxonline, mitx, and
  mitx-staging currently have distinct slot configs. Decide before completing Task 6.
- **Module build strategy** — `openedx build:module` does not exist yet (see `AUDIT.md`).
  All module libraries are imported at build time for now.
- **`build_legacy` decommission timeline** — set once frontend-base reaches stable and
  OL's MFEs are migrated.

## References

- `AUDIT.md` — verified CLI commands, config schema, and blocking findings
- `plans/03-frontend-base-oep65.md` — implementation guide
- [OEP-65](https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065-arch-frontend-composability.html)
- [frontend-base repository](https://github.com/openedx/frontend-base)
