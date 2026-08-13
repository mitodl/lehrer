# RFC: Feature Manifests — one declaration, cross-layer fan-out

**Status:** Draft for discussion
**Repo:** mitodl/lehrer
**Related:** [06 Build Manifest](./06-build-manifest.md), [03 Frontend-Base / OEP-65](./03-frontend-base-oep65.md)

## 1. Summary

Turning on one user-facing Open edX feature today means editing up to ten unrelated
places, in two repositories, in three languages, with no mechanism that connects them
and nothing that fails when you miss one. This RFC proposes a **feature manifest**: one
declarative YAML per feature per deployment group, validated by Pydantic models in
lehrer core, that names the complete fan-out across every layer a feature touches — and
a `lehrer features compile` step that emits per-layer artifacts in a documented,
versioned contract.

The design goal that shapes every decision below: **lehrer is a stand-alone toolchain
intended for operators beyond MIT Open Learning.** The manifest schema therefore
contains no notion of environment stages, promotion pipelines, deployment enums, or any
other MIT OL topology. Where an environment axis is unavoidable, it is an *opaque
operator-defined label* that lehrer stores and matches but never interprets. How any
particular operator ingests the compiled artifacts is deliberately outside the schema;
MIT OL's own integration appears only in a non-normative appendix.

## 2. Problem

### 2.1 The ten mechanisms

Feature state is spread across these, verified against lehrer `e14e3f0` and
ol-infrastructure `c120a1d87`:

| # | Mechanism | Where it lives |
|---|---|---|
| 1 | Env var → aqueduct Pydantic field | `deployments/<group>/settings/{lms,cms}/models/aqueduct.py` (394 LMS / 170 CMS fields for mit-ol) |
| 2 | `OL_SETTINGS_DIR` YAML deep-merge for `FEATURES`/`MFE_CONFIG` | `src/lehrer/settings/base.py:112,277`; files supplied by the operator at runtime |
| 3 | `@model_validator` derivation cascades | e.g. `_apply_structural_overrides` in `deployments/mit-ol/settings/lms/aqueduct.py:192` |
| 4 | `FEATURES_COMPAT_KEYS` mirroring | `deployments/mit-ol/settings/lms/aqueduct.py:59-129` — ~70 keys mirrored into `FEATURES` |
| 5 | Waffle DB flags | `set_waffle_flags.py` (baked into the image at `src/lehrer/core/platform.py:1221`) reading a YAML the operator supplies |
| 6 | MFE build-time env vars | **no declarative home** — raw `list[str]` of `KEY=VALUE` at `src/lehrer/core/mfe.py:63,212` |
| 7 | `build_config.yaml` slot files / npm bundles / styles | `deployments/<group>/mfe_slot_config/legacy/build_config.yaml` |
| 8 | OEP-65 runtime config | `ENABLE_MFE_CONFIG_API` + `FRONTEND_SITE_CONFIG`, supplied by the operator |
| 9 | Service image existence | notes / codejail — built by separate lehrer targets |
| 10 | Data population | management commands (OAuth clients, `saml_pull`) run by the operator |

Mechanisms 1–7 and 9 are lehrer's; 8 and 10 are the operator's. Nothing ties any of them
together, and no gate detects a partial rollout. The failure mode is silent: the feature
simply does not appear, or appears half-configured, and the diagnosis is a manual walk
through all ten.

### 2.2 Worked example — the AI drawer today

Enabling the slot-based AskTIM drawer for a deployment currently requires:

1. **MFE build env** — `enable_ai_drawer_slot="true"` on the correct entry in the
   operator's build configuration (mechanism 6), threaded through a hand-maintained
   field and a params dict.
2. **Slot files** — `AIDrawerManagerSidebar.jsx` and a release-selected
   `SidebarAIDrawerCoordinator.jsx` listed under the learning MFE's `extra_slot_files`
   in `build_config.yaml`.
3. **npm bundle** — `@mitodl/smoot-design@^6.33.0|public/static/smoot-design` in
   `extra_npm_bundles`.
4. **Stylesheet** — the deployment's entry in the `styles:` map.
5. **Config JSX** — `learning-mfe-config.env.jsx:14` reads
   `process.env.ENABLE_AI_DRAWER_SLOT`, and at line 40 the whole `pluginSlots` block is
   *additionally* gated on `process.env.DEPLOYMENT_NAME?.includes("mitxonline")` — a
   second, hard-coded deployment test that no schema knows about.
6. **Inverse branch** — when the flag is off, the same file dynamically imports
   `/learn/static/smoot-design/aiDrawerManager.es.js`, a hard-coded path. The flag is
   not on/off; it *switches between two implementations*.
7. **LMS plugin + settings** — the chat plugin must be in the cell's `packages` in
   `build_manifest.yaml`, with its settings supplied at runtime.
8. **Waffle** — a per-course gate for the companion feedback drawer, in a YAML the
   operator maintains separately.

Eight coupled edits, of which exactly one (`ENABLE_AI_DRAWER_SLOT`) looks like a feature
flag. Item 5 in particular is an operator assumption hard-coded into a JSX file — the
class of thing this RFC exists to make declarative.

## 3. Goals and non-goals

**Goals**

- One declarative home per feature, naming its full cross-layer fan-out.
- Compile-time validation: an unknown setting name, an unsatisfied plugin requirement,
  or two features fighting over the same key fails before anything is built.
- A documented, versioned artifact contract any consumer can read.
- `lehrer features explain <feature>` answers "what does flipping this actually touch?"
  — today an unwritten oral tradition.
- Graceful degradation: operators who do not adopt manifests keep today's explicit
  arguments, unchanged.

**Non-goals**

- Not a runtime feature-flag service. Waffle remains the mechanism for per-user and
  per-course targeting; the manifest declares *which* flags a feature needs.
- No environment-stage, promotion, or rollout model. Scopes are opaque labels (§4.2).
- Does not replace `build_manifest.yaml` (build definitions) or `build_config.yaml`
  (baseline MFE customisation); it composes with both (§6).
- Does not prescribe how an operator ingests artifacts (§7, Appendix A).

## 4. Design

### 4.1 Layout

```
deployments/<group>/features/
  scopes.yaml          # the group's scope labels, declared once
  ai-drawer.yaml       # one file per feature
  course-notes.yaml
```

New core module `src/lehrer/core/feature_manifest.py`, following the established
precedent of `mfe_config.py` and `build_manifest.py`: Pydantic models that serve as both
validator and JSON Schema source, with a `# yaml-language-server: $schema=` modeline for
editor and agent validation.

### 4.2 Scopes are opaque labels

A feature is rarely on everywhere at once, so the manifest needs *some* axis. That axis
must not encode anyone's topology. A **scope** is an operator-chosen string that lehrer
stores, matches, and passes through — never parses.

```yaml
# deployments/<group>/features/scopes.yaml
version: 1
scopes:
  mitxonline-ci:
    cell: {release: master, deployment: mitxonline}
  mitxonline-production:
    cell: {release: master, deployment: mitxonline}
  mitx-ci:
    cell: {release: master, deployment: mitx}
```

`cell` points at an existing `build_manifest.yaml` coordinate. That join is what lets
compile check a feature's plugin requirements against the packages the cell actually
installs. Multiple scopes may share one cell — which is exactly the case a bare
`(release, deployment)` coordinate cannot express, since a deployment may be built from
one release but operated in several places with different features on.

Declaring scopes centrally means a typo in a feature file fails at load rather than
silently matching nothing. This follows the `settings_model_release` validator precedent
in `build_manifest.py:134` — *a gate that quietly stops gating is worse than no gate.*

### 4.3 Feature schema

```yaml
# deployments/mit-ol/features/ai-drawer.yaml
version: 1
feature: ai-drawer
summary: Slot-based AskTIM chat drawer in the learning MFE right sidebar.

requires:
  plugins: [ol-openedx-chat]      # checked against the scope's cell packages
  services: []                    # e.g. [notes], [codejail]

layers:                           # defaults, applied wherever enabled
  settings:
    lms:
      SOME_SETTING: value         # validated against the AqueductSettings inventory
  features:                       # FEATURES dict entries
    lms:
      ENABLE_SOMETHING: true
  waffle:
    - flag: feedback.feedback_enabled
      args: ["--create", "--everyone"]
  mfe_build_env:
    learning:
      ENABLE_AI_DRAWER_SLOT: "true"
  mfe_assets:
    learning:
      extra_slot_files:
        - AIDrawerManagerSidebar.jsx
        - dest: SidebarAIDrawerCoordinator.jsx
          by_release:
            ulmo: SidebarAIDrawerCoordinator.ulmo.jsx
            default: SidebarAIDrawerCoordinator.jsx
      extra_npm_bundles:
        - "@mitodl/smoot-design@^6.33.0|public/static/smoot-design"
  site_config:                    # FRONTEND_SITE_CONFIG / MFE_CONFIG keys
    commonAppConfig:
      aiDrawer: {enabled: true}
  commands:                       # data population this feature depends on
    - id: chat-oauth-client
      service: lms
      argv: [manage.py, lms, create_dot_application, ...]
      stage: post-migrate

scopes:
  mitxonline-ci:         {enabled: true}
  mitxonline-production: {enabled: true}
  mitx-ci:               {enabled: false}
```

Per-scope overrides deep-merge over `layers`:

```yaml
scopes:
  mitxonline-ci:
    enabled: true
    layers:
      waffle:
        - flag: feedback.feedback_enabled
          args: ["--create", "--everyone"]
```

`mfe_assets` deliberately reuses the existing `build_config.yaml` vocabulary
(`extra_slot_files`, `extra_npm_bundles`, the `by_release` mapping), sharing the
`SlotFileByRelease` model from `mfe_config.py` rather than inventing a parallel one.

### 4.4 Validation

Everything here runs in plain Python with no container and no Django. The generated
`AqueductSettings` model is a *static* codegen-v2 file, so `ast.parse` recovers the full
field inventory in milliseconds — the settings gate costs nothing to run on every commit.

1. **Settings names** — every key under `layers.settings.<service>` must be a field of
   that service's committed `models/aqueduct.py`. Unknown key → compile error. This is
   the single highest-value check: it turns a typo that silently does nothing into a
   failure at PR time.
2. **Scope names** — must appear in `scopes.yaml`.
3. **Plugin requirements** — `requires.plugins` ⊆ the packages of the scope's cell in
   `build_manifest.yaml`.
4. **MFE names** — must appear in the group's `build_config.yaml` `mfes` map.
5. **Slot files** — every referenced source file must exist in the slot config dir.
6. **Shapes** — waffle flags as `namespace.name`; npm bundles as `spec|target`.
7. **Conflicts** — two features enabled in the same scope that assign different values
   to the same setting, FEATURES key, waffle flag, or MFE build var is a hard error.
   Nothing detects this today.
8. **FEATURES keys** are *not* statically checkable — `FEATURES` is typed `Any` in the
   generated model (`models/aqueduct.py:689`), and the authoritative key set lives in
   edx-platform's `common.py`. This check belongs in the existing settings-verify CI
   tier, which already boots a real container, rather than in compile.

### 4.5 CLI

```
lehrer features compile --group <g> --scope <s> --out <dir>
lehrer features check   --group <g>              # validate all scopes, emit nothing
lehrer features list    --group <g> [--scope <s>]
lehrer features explain <feature> --group <g> --scope <s>
```

`check` is a cheap CI gate alongside the existing `build-config-schema` /
`build-manifest-schema` hooks. `explain` prints the resolved fan-out for one feature —
the answer to "what does turning this on touch?"

Path-reasoning logic lives in `src/lehrer/cli/`, not `core/`: the `lehrer-core-boundary`
pre-commit hook forbids the literal string `deployments` under `src/lehrer/core/`.

### 4.6 Artifact contract

`compile` writes a versioned tree. `contract_version` is independent of the manifest
`version`, so consumers pin against output format, not input schema.

```
<out>/
  manifest.json            # {contract_version: 1, group, scope, generated_from: {...}}
  waffles.yaml             # {waffles: [[flag, arg, ...]]}
  settings/lms.yaml        # OL_SETTINGS_DIR-shaped fragment
  settings/cms.yaml
  site_config.yaml         # FRONTEND_SITE_CONFIG / MFE_CONFIG keys
  mfe_build_env/<mfe>.env  # KEY=VALUE
  checklist.yaml           # required services, plugins, commands
```

`waffles.yaml` matches byte-for-byte what `set_waffle_flags.py` already consumes
(`{"waffles": [[flag, *args]]}`), so it is drop-in for any operator already using that
script — which lehrer bakes into every image.

### 4.7 Self-served versus emitted layers

Two of these layers describe steps **lehrer itself performs**. For those, requiring a
consumer to read a file and hand values back to lehrer is a pointless round trip:
`build_legacy_configured` already receives `--deployment-name` and `--release-name`, so
it can resolve the manifest directly given `--scope`.

| Layer | lehrer self-serves | Also emitted |
|---|---|---|
| `mfe_build_env` | yes, via `--scope` | yes |
| `mfe_assets` | yes, via `--scope` | yes |
| `settings`, `features` | no | yes |
| `waffle` | no | yes |
| `site_config` | no | yes |
| `commands`, `requires` | no | yes (checklist) |

Everything is emitted regardless, so an operator using a different build system is never
locked out. `--scope` is purely additive: omit it and every existing explicit argument
behaves exactly as it does today.

## 5. AI drawer as a manifest

The §2.2 walk-through collapses to one file plus one flag. The hard-coded
`DEPLOYMENT_NAME?.includes("mitxonline")` test in `learning-mfe-config.env.jsx:40`
becomes the scope's `enabled:` value, and the JSX reads a single build var. The
implementation-switch nature of the flag (§2.2 item 6) is expressible because
`mfe_build_env` sets a value rather than a boolean presence.

## 6. Relationship to existing configuration

- **`build_manifest.yaml`** — unchanged. It owns build definitions per cell; feature
  manifests reference cells through `scopes.yaml` and never duplicate their content.
- **`build_config.yaml`** — remains the *baseline*, unconditional MFE customisation.
  Feature manifests contribute the *conditional* subset. `build_legacy_configured`
  merges baseline with the resolved feature layer for the requested scope; no second
  generated file, so no drift gate is needed. Migrating an existing entry from
  `build_config.yaml` into a feature manifest is a deliberate, reviewable move.
- **Settings trees** — feature manifests emit `OL_SETTINGS_DIR` fragments; they do not
  edit the generated models, and never introduce validators. (Reminder for
  implementation: no validator may import from `lms.*`, `cms.*`, or `openedx.*` — that
  is a circular-import hazard during settings load.)

## 7. Consumer integration

lehrer's responsibility ends at §4.6. How an operator moves those artifacts into a
running deployment is theirs, and the plausible channels differ enough in operational
character that baking one into the schema would be exactly the over-indexing this
project exists to avoid. Three that we know work:

- **Bake into the image** — copy the compiled scope tree to `/openedx/config/features/`
  during the platform build, alongside the `set_waffle_flags.py` lehrer already injects.
  No external plumbing whatsoever. Cost: a flag flip becomes an image rebuild.
- **Read at deploy time** — the deployment tool reads the artifact tree and materialises
  it (ConfigMaps, env, mounted files). Keeps flips at deploy latency; costs the operator
  a way to obtain the tree.
- **Vendor the artifacts** — sync compiled output into the deployment repo, reviewed
  there. Explicit, at the cost of a two-repo dance and a drift surface.

An operator may mix these per layer — waffle flags are deliberately the *fast* lever in
most Open edX deployments, and an operator who values that may keep them at deploy
latency while sourcing build-time layers from lehrer. The manifest supports this
directly: a scope can declare waffle flags for `checklist.yaml` only, making them a
stated requirement that something else satisfies.

## 8. Rollout

- **Phase 0** — schema, `compile`, `check`, validation. No consumer changes. Emit
  artifacts for existing deployments and diff them against what each operator produces
  by hand; equivalence is the acceptance test.
- **Phase 1** — AI drawer pilot. Add `--scope` to `build_legacy_configured`.
- **Phase 2** — runtime layers (waffle, settings fragments, site config), per whichever
  channel each operator selects.
- **Phase 3** — migrate remaining features; add `features check` to CI.

Every phase is independently revertable, and Phase 0 changes no behaviour at all.

## 9. Open questions

1. **Scope granularity.** Is one flat label per (deployment, place-it-runs) right, or do
   operators need composition (a scope inheriting another's defaults)? Flat is proposed;
   inheritance is easy to add later and hard to remove.
2. **Conflict policy.** §4.4.7 makes conflicting assignments a hard error. Should an
   explicit precedence declaration be allowed instead, or does that reintroduce exactly
   the implicit-override confusion this replaces?
3. **`commands` scope.** Is declaring management commands as a *checklist* enough, or
   should lehrer eventually run them? Running them implies a runtime role lehrer does
   not currently have.
4. **`site_config` overlap.** `FRONTEND_SITE_CONFIG` is largely topology (URLs, cookie
   names) with a little feature content. Does the manifest carry only the feature-owned
   subset, and if so how is the boundary kept honest?

## Appendix A — MIT OL integration (non-normative)

Illustrative only; no part of the schema depends on it.

MIT OL builds via Concourse pipelines that already clone lehrer as a git resource with a
path filter (`src/ol_concourse/pipelines/open_edx/mfe/pipeline.py:265`), so compiled
artifacts committed under a filtered path would both be present on disk in the build
task and trigger a rebuild when they change. Build-time layers would be self-served: the
per-feature `--env-vars` flags currently generated from `values.py` collapse into a
single `--scope`, while topology vars (domains, logos, URLs) stay where they are.

Runtime layers have no existing channel — the edxapp Pulumi stack never sees lehrer.
Waffle data is stack config (`edxapp:waffle_flags`), rendered to a ConfigMap
(`k8s_configmaps.py:801`) and consumed by an `lms-waffleflag` pre-deploy command
(`k8s_resources.py:825`); `FRONTEND_SITE_CONFIG` is a Python literal
(`k8s_configmaps.py:211`). Adopting any of §7's channels for these is a separate
ol-infrastructure decision, to be taken there.
