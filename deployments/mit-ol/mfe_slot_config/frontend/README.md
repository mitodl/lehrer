# OEP-65 Frontend-Base Site Project (Future)

> **Status:** Planned — not yet implemented.

This directory will become MIT OL's **OEP-65 Site Project** — an
operator-owned frontend application built on
[@openedx/frontend-base](https://github.com/openedx/frontend-base).

## What goes here (Phase 2)

Once `lehrer.core.mfe.build_site()` is implemented (see
`plans/03-frontend-base-oep65.md`), this directory will contain:

```
frontend/
├── package.json                 # @openedx/frontend-base dependency + config
├── site.config.build.tsx        # module declarations for production build
├── site.config.dev.tsx          # module declarations for dev server
└── src/                         # custom module overrides (optional)
```

## Relationship to legacy JSX files

The files in `../legacy/` (`Footer.jsx`, `*-config.env.jsx`, etc.) are used
by `dagger call mfe build-legacy` and will continue to work until the
migration to frontend-base is complete.

## References

- `plans/03-frontend-base-oep65.md` — full implementation guide
- OEP-0065: https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065-arch-frontend-composability.html
- frontend-base: https://github.com/openedx/frontend-base
