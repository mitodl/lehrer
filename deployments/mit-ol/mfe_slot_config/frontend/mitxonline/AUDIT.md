# @openedx/frontend-base API Audit

**Date:** 2026-06-05
**Version pinned:** `v1.0.0-alpha.41` (latest as of audit date)
**Status:** Still pre-alpha / active development — proceed with caution.

## Stability assessment

The README carries a prominent "active development / may change significantly" warning.
At `v1.0.0-alpha.41` (released 2026-04-27) the library is over 40 alpha iterations in
and has stabilised around a consistent Webpack + CLI model. The `build` / `dev` CLI
surface has not changed structurally since at least alpha.30. The `SiteConfig` type
(`apps` array, runtime config URL) is the load-bearing API surface and appears stable
for practical purposes.

**Recommendation:** Implement `build_site` and `watch_site` now. Hold `build_federated_module`
as a stub until a dedicated module-build command is added to the CLI.

## Verified CLI commands

Source: `tools/cli/openedx.ts` and `tools/types.ts` in the repository.

| `openedx` subcommand | Underlying tool | Notes |
|---|---|---|
| `build` | webpack (production config) | Reads `site.config.build.tsx` |
| `dev` | webpack-dev-server | Reads `site.config.dev.tsx` |
| `dev:shell` | webpack-dev-server | Shell-only dev mode (no app modules) |
| `serve` | express server | Serves a pre-built `dist/` |
| `lint` | eslint | |
| `test` | jest | |
| `formatjs` | @formatjs/cli | |
| `translations:pull` | custom | |
| `translations:prepare` | custom | |

**⚠️ `openedx build:module` does NOT exist.** The plan's `build_federated_module` function
assumed this command, but it is not in the CLI. Module libraries (migrated MFEs) are
currently imported directly by Site Projects as npm package dependencies — they are
bundled at build time, not loaded via webpack module federation at runtime. The
`build_federated_module` stub remains `NotImplementedError` until this is resolved.

## Config file schema — `SiteConfig`

Source: `test-site/site.config.build.tsx` (canonical reference implementation).

```tsx
import {
  footerApp, headerApp, shellApp,
  EnvironmentTypes, SiteConfig,
} from '@openedx/frontend-base';
import '@openedx/frontend-base/shell/style';

const siteConfig: SiteConfig = {
  siteId: 'my-site',           // required: unique identifier
  siteName: 'My Site',         // required: display name
  baseUrl: 'https://apps.example.com',   // required: shell base URL
  lmsBaseUrl: 'https://courses.example.com',  // required
  loginUrl: 'https://courses.example.com/login',   // required
  logoutUrl: 'https://courses.example.com/logout', // required
  environment: EnvironmentTypes.PRODUCTION,  // PRODUCTION | DEVELOPMENT | TEST
  runtimeConfigJsonUrl: '/api/frontend_site_config/v1/',  // optional runtime config
  apps: [
    shellApp,    // always include — provides the Shell
    headerApp,   // always include — provides the header
    footerApp,   // always include — provides the footer
    // ... module library app configs imported from npm packages
  ],
};

export default siteConfig;
```

Two config files are required:
- `site.config.build.tsx` — used by `openedx build` (production)
- `site.config.dev.tsx` — used by `openedx dev` (development; `environment: EnvironmentTypes.DEVELOPMENT`)

The old plan noted a single `site.config.tsx` — **this is incorrect**. Two files are needed.

## Output path

`openedx build` outputs to `dist/` in the project working directory.
Confirmed by `webpack.config.build.ts`:
```ts
output: {
  path: path.resolve(process.cwd(), 'dist'),
  ...
}
```

## Node.js version requirement

`.nvmrc` in the repository: **Node 24**

The plan assumed Node 22. The test-site `package.json` has no `engines` field, but the
repository's `.nvmrc` specifies Node 24. Use `node:24-trixie-slim` in Dagger containers.

## Peer dependencies for Site Projects

From `test-site/package.json`:

```json
"dependencies": {
  "@openedx/frontend-base": "^1.0.0-alpha",
  "@openedx/paragon": "^23",
  "react": "^18",
  "react-dom": "^18",
  "react-router": "^6",
  "react-router-dom": "^6"
}
```

## Required files and config — build checklist

The following are all required by `openedx build` and are not present by default.
Absence of any one causes a hard build failure.

| File / config | Error if missing | Notes |
|---|---|---|
| `src/i18n/index.ts` | `Default site i18n directory does not exist. Aborting.` | `export default []` is sufficient |
| `public/index.html` | `Module not found: Can't resolve '/app/site/public/index.html'` | Minimal HTML shell with `<div id="root">` |
| `browserslist` in `package.json` + `@edx/browserslist-config` devDep | `Cannot find module '@edx/browserslist-config'` | `postcss-loader`/`autoprefixer` reads project-root browserslist config |

## `src/i18n/index.ts` requirement

The build aborts with `Default site i18n directory (/app/site/src/i18n) does not exist`
if `src/i18n/` is missing. Every Site Project must include:

```ts
// src/i18n/index.ts
export default [];
```

This is an empty i18n message list. Populate it with merged translation message
objects once `openedx translations:pull` is integrated into the build pipeline.
The path can be overridden via `SITE_I18N_PATH` env var if needed.

Source: `tools/webpack/utils/getResolvedSiteI18nPath.ts` in the frontend-base repo.

## `tsconfig.json` requirement

The build config references `tsconfig.json` in the project root via `TsconfigPathsPlugin`.
Site Projects must include a `tsconfig.json` — see `test-site/tsconfig.json` for a
minimal example.

## Module library migration path

MFEs migrate to frontend-base by:
1. Removing `@edx/frontend-platform`, `@openedx/frontend-build`, headers/footers, plugin-framework
2. Moving shared deps (`paragon`, `react`, `react-router`) to `peerDependencies`
3. Adding `@openedx/frontend-base` as a peer dependency
4. Exporting app module configs that the Site Project's `apps` array consumes

The Site Project then lists the module library as a `dependency` and adds its exported
app config objects to the `apps` array in `site.config.build.tsx`.

## Summary table

| Property | Value |
|---|---|
| Latest version | `v1.0.0-alpha.41` |
| Production build command | `openedx build` |
| Dev server command | `openedx dev` |
| Build config file | `site.config.build.tsx` |
| Dev config file | `site.config.dev.tsx` |
| Output directory | `dist/` |
| Node.js version | 24 |
| `build:module` command | **Does not exist** |
| Stability | Alpha, but build/dev surface stable enough to implement |
