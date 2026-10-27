# RFC: Feature Manifests — one declaration, cross-layer fan-out

**Status:** Spec. Revised 2026-10-26 against lehrer `d168aec`; §9 resolutions proposed for review.
**Repo:** mitodl/lehrer
**Related:** [06 Build Manifest](./06-build-manifest.md), [03 Frontend-Base / OEP-65](./03-frontend-base-oep65.md), `src/lehrer/bootstrap/` (bootstrap spec and runner)

> **Revision note (2026-10-26).** The RFC merged in #154 on 2026-08-21. Four things
> changed under it before implementation started, and this revision folds them in:
> `lehrer.bootstrap` landed (#274) and now owns waffle flags, OAuth applications and
> third-party auth, so those operations become a bootstrap fragment (§4.3.3); the
> generated settings models now include plugin settings and the inventory spans the
> lehrer mixins (§4.4.1); MIT OL's frontends are split between legacy MFE builds and
> frontend-base Site Projects, which take build-time input differently (§4.3.4); and
> the AI drawer's real structure turned out narrower than §2.2 described (§5).

## 1. Summary

Turning on one user-facing Open edX feature today means editing up to ten unrelated
places, in two repositories, in three languages, with no mechanism that connects them
and nothing that fails when you miss one. This RFC proposes **feature manifests**, split
into a per-feature *definition* — the complete set of operations that feature requires,
plus the parameters it accepts — and a per-deployment *adoption* file that names which
features it takes and with what values. Both are validated by Pydantic models in
lehrer core, and together they name the complete fan-out across every layer — and
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

Feature state is spread across these, verified against lehrer `d168aec` (originally
`e14e3f0` and ol-infrastructure `c120a1d87`):

| # | Mechanism | Where it lives |
|---|---|---|
| 1 | Env var → aqueduct Pydantic field | `deployments/<group>/settings/{lms,cms}/models/aqueduct.py` plus the lehrer mixins in `src/lehrer/settings/base.py` (935 LMS / 674 CMS fields for mit-ol) |
| 2 | `OL_SETTINGS_DIR` YAML deep-merge for `FEATURES`/`MFE_CONFIG` | `src/lehrer/settings/base.py:132,451-463`; files supplied by the operator at runtime |
| 3 | `@model_validator` derivation cascades | e.g. `_apply_structural_overrides` in `deployments/mit-ol/settings/lms/aqueduct.py:196` |
| 4 | `FEATURES_COMPAT_KEYS` mirroring | `deployments/mit-ol/settings/lms/aqueduct.py:64-134` — 69 keys mirrored into `FEATURES` |
| 5 | Waffle DB flags | `lehrer.bootstrap` `waffle_flags` (`src/lehrer/bootstrap/spec.py:210`), or the older `set_waffle_flags.py` still baked into the image (`src/lehrer/core/platform.py:1367`), each reading a file the operator supplies |
| 6 | MFE build-time env vars | **no declarative home** — raw `list[str]` of `KEY=VALUE` at `src/lehrer/core/mfe.py:94,243` |
| 7 | `build_config.yaml` slot files / npm bundles / styles | `deployments/<group>/mfe_slot_config/legacy/build_config.yaml` |
| 8 | OEP-65 runtime config | `ENABLE_MFE_CONFIG_API` + `FRONTEND_SITE_CONFIG`, supplied by the operator |
| 9 | Service image existence | notes / codejail — built by separate lehrer targets |
| 10 | Data population | `lehrer.bootstrap` for users, OAuth applications, OAuth2 IdPs and service tokens; management commands (`saml --pull`) run by the operator |

Mechanisms 1–7 and 9 are lehrer's; 8 is the operator's; 10 is split, with lehrer
shipping the bootstrap runner and the operator deciding when it runs. Nothing ties any of them
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
4. **Stylesheet** — the deployment's entry in the `styles:` map. Note what that
   actually means: `mitxonline-styles.scss` is a 598-line *deployment-wide*
   stylesheet whose lines 354+ are the drawer's layout rules. The feature owns a
   fragment of a file it does not own, and nothing marks the boundary.
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

**Corrections as of `d168aec`.** A closer reading changes what a manifest can take over:

- Items 2 and 3 are not conditional. `learning-mfe-config.env.jsx:10` imports
  `SidebarAIDrawerCoordinator.jsx` unconditionally, the coordinator imports
  `FeedbackDrawerSlot.jsx` and `useSidebarContext.js`, and both implementations load
  the same smoot-design bundle (now `^6.38.1`, `build_config.yaml:53`). Moving those
  files into a feature would break the build of every scope that does not adopt it, so
  they stay in `build_config.yaml`.
- Item 5's `DEPLOYMENT_NAME` test gates the whole `pluginSlots` block (breadcrumbs,
  certificate hiding and other mitxonline slot changes), of which the drawer's
  `right_sidebar` entry is one. With the flag on outside mitxonline, the drawer is
  silently absent.
- Item 4: the stylesheet is now 656 lines, with the drawer rules at 411-656. They
  select only the drawer's own classes, so they are inert when the drawer is not
  rendered.
- Item 6 means there is no "off" state: not setting the flag selects the standalone
  bundle.

## 3. Goals and non-goals

**Goals**

- One declarative home per feature, naming its full cross-layer fan-out.
- A feature's contract stated independently of anyone's adoption of it, so the set of
  available features is enumerable and an upstream-native definition is shareable
  between operators rather than rewritten by each.
- Values, not just on/off: a feature may take typed parameters (integers, strings,
  enums), since most real toggles configure something as well as enabling it.
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

A feature's **definition** and its **adoption** are separate artifacts. The definition
is a contract — the complete set of operations that must happen for the feature to work,
plus the parameters it accepts. Adoption is a deployment stating which features it takes
and with what values. Conflating the two is what makes today's situation
undiagnosable: there is no artifact anywhere that answers "what does this feature
require?" independently of "where is it on?"

```
src/lehrer/features/               # upstream-native definitions, shipped with lehrer
  course-notes.yaml

deployments/<group>/features/
  definitions/                     # operator-specific, and plugin features not yet shipped by their plugin
    ai-drawer.yaml
  vendored/<dist>/<version>/       # reserved: definitions copied from installed plugins (§9.7)
  scopes.yaml                      # scope labels -> build cells, sets, frontends
  adoption.yaml                    # which features each scope takes, with values
```

A definition's `feature` name is unique across lehrer's catalog, `definitions/` and
`vendored/`. A duplicate fails compile; nothing shadows anything. That rule, the
`vendored/` directory and the `lehrer.features` entry-point group (§9.7) are reserved in
v1 so plugin-shipped definitions can arrive later without a layout change.

Splitting them buys three things beyond tidiness. Definitions become *enumerable* — a
catalog of what can be turned on, independent of anyone's deployment. Upstream-native
definitions are operator-agnostic by construction, so lehrer can ship them and every
operator inherits them (the catalog may start empty and grow). And adoption becomes a
short, reviewable file: the diff for turning a feature on is one block, not a hunt
across ten mechanisms.

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
    frontends: {learning: legacy}
  mitxonline-qa:
    cell: {release: master, deployment: mitxonline}
    frontends: {learning: legacy}
  mitxonline-production:
    cell: {release: master, deployment: mitxonline}
    frontends: {learning: legacy, instructor-dashboard: {site: mitxonline}}
  mitx-ci:
    cell: {release: master, deployment: mitx}
    frontends: {learning: legacy}
```

`cell` points at an existing `build_manifest.yaml` coordinate. That join is what lets
compile check a feature's plugin requirements against the packages the cell actually
installs. Multiple scopes may share one cell — which is exactly the case a bare
`(release, deployment)` coordinate cannot express, since a deployment may be built from
one release but operated in several places with different features on.

Declaring scopes centrally means a typo in a feature file fails at load rather than
silently matching nothing. This follows the `settings_model_release` validator precedent
in `build_manifest.py:168` — *a gate that quietly stops gating is worse than no gate.*

**Scopes are flat.** A scope has no parent and inherits nothing. Several scopes
typically adopt mostly the same features (mit-ol runs four deployments, each in CI, QA
and Production, backed by seven cells; mitxonline runs master in all three), so
`scopes.yaml` may also declare `sets`: named, unordered lists of scopes.

```yaml
sets:
  mitxonline-all: [mitxonline-ci, mitxonline-qa, mitxonline-production]
```

Sets cannot contain sets, and set and scope names share one namespace. An adoption
block (§4.3.1) may be keyed by a scope or a set. A scope takes each feature from its own
block if it has one, otherwise from the one set containing it that adopts that feature;
two sets containing the same scope that both adopt a feature fail compile. A scope
block replaces the set block for that feature parameter by parameter, and there is no
deeper precedence. This is the same one-level shape as `build_manifest.yaml`'s
`defaults` block under a cell (`Cell.resolved`, `build_manifest.py:105`), which is the
only layering precedent lehrer has.

A scope also declares `frontends`, how it builds the MFEs features may touch (§4.3.4).

### 4.3 Feature definitions — the contract

A definition names every operation the feature needs and every parameter it accepts. It
says nothing about where the feature is on. The example below is illustrative and shows
every operation group; §5 has the real AI drawer definition, which uses only one.

```yaml
# deployments/<group>/features/definitions/course-chat.yaml
version: 1
feature: course-chat
summary: Illustrative plugin feature exercising every operation group.

origin: plugin                    # upstream | plugin | operator
provided_by: example-chat-plugin  # required when origin: plugin

frontend_paths: [legacy]          # build paths this definition supports (§4.3.4)

parameters:
  history_limit:
    type: integer
    default: 20
  chat_model:
    type: string
    default: null
    description: Overrides the plugin default when set.
  layout:
    type: enum
    choices: [sidebar, overlay]
    default: sidebar

requires:
  plugins: [example-chat-plugin]  # checked against the scope's cell packages
  services: []                    # e.g. [notes], [codejail]
  frontends: [learning]           # resolved against the scope's frontends (§4.3.4)
  features: []                    # other features that must be adopted in the same scope

operations:                       # the complete fan-out
  settings:
    lms:
      CHAT_HISTORY_LIMIT: ${history_limit}
      CHAT_MODEL: ${chat_model}
  features:                       # FEATURES dict entries
    lms:
      ENABLE_SOMETHING: true
  bootstrap:                      # a lehrer.bootstrap BootstrapSpec fragment (§4.3.3)
    users:
      - {username: course_chat_worker, email: course-chat@example.invalid}
    oauth_applications:
      - name: course-chat
        user: course_chat_worker
        grant_type: client-credentials
        client_id_env: COURSE_CHAT_OAUTH_CLIENT_ID
        client_secret_env: COURSE_CHAT_OAUTH_CLIENT_SECRET
    waffle_flags:
      - {name: course_chat.enabled, everyone: true}
  mfe_build_env:                  # legacy build path only (§4.3.4)
    learning:
      CHAT_LAYOUT:
        by_parameter: layout
        cases: {sidebar: "sidebar", overlay: "overlay"}
  mfe_assets:                     # legacy build path only (§4.3.4)
    learning:
      extra_slot_files:
        - ChatSidebar.jsx
        - dest: ChatCoordinator.jsx
          by_release:
            ulmo: ChatCoordinator.ulmo.jsx
            default: ChatCoordinator.jsx
      extra_npm_bundles:
        - "@example/chat-ui@^1.4.0|public/static/chat-ui"
  site_config:                    # runtime config API keys (§4.3.5)
    frontend_site_config:
      commonAppConfig:
        courseChat: {enabled: true}
  commands:                       # declared, never executed by lehrer (§4.3.3)
    - id: chat-index-backfill
      service: lms
      argv: [manage.py, lms, chat_backfill_index]
      recurring: false
```

**`origin` selects which obligations apply.** It no longer changes how settings are
validated. The generated models now carry the settings of every plugin the model cell
pins (codegen runs with `--openedx-plugins`; 74 LMS and 42 CMS fields for mit-ol are
marked `aqueduct_plugin`), so every feature's settings are checked against the same
inventory (§4.4.1). What `plugin` adds is an obligation: `provided_by` must appear in
the adopting scope's cell packages (§4.4.3). `upstream` marks a definition lehrer can
ship in its own catalog. `operator` asserts neither and gets the common checks only.

`mfe_assets` reuses the existing `build_config.yaml` vocabulary
(`extra_slot_files`, `extra_npm_bundles`, the `by_release` mapping), sharing the
`SlotFileByRelease` model from `mfe_config.py` rather than inventing a parallel one. A
file may be listed in `mfe_assets` only if no baseline file imports it statically;
otherwise a scope that does not adopt the feature fails to build. Compile cannot check
this, so it is a rule for definition authors, and the reason the AI drawer's files stay
in `build_config.yaml` (§5).

The earlier draft also proposed `style_fragments`. It is dropped from v1. The case that
motivated it, the drawer's rules inside the mitxonline stylesheet, selects only the
drawer's own classes and is inert when the drawer is not rendered; xpro has no `styles:`
host sheet to append to; and Site Projects import styles statically. Extracting
feature rules out of baseline sheets is left as later work (§9.6).

**Parameters.** A parameter has a `type` of `integer`, `string`, `boolean` or `enum`; an
`enum` lists its `choices`. `${name}` substitutes a scalar parameter into any operation
value. An operation value may instead be a lookup on an enum parameter:

```yaml
SOME_KEY:
  by_parameter: layout
  cases: {sidebar: "true", overlay: null}
```

`cases` must cover every choice or include a `default` case, so a new choice cannot
compile to nothing. A case value of `null` omits the key, as does a `${name}` whose
value is `null`. That is the whole of the
conditional vocabulary: no expressions, no comparisons, and no conditional inclusion of
whole operation groups. It mirrors `by_release`, which already selects a value by a
closed set of names, and stops there deliberately (§9.8).

### 4.3.1 Adoption — what a deployment turns on

Adoption names features and supplies parameter values. Presence means adopted; values
are typed by the definition, not restricted to booleans.

```yaml
# deployments/<group>/features/adoption.yaml
version: 1
adoption:
  mitxonline-production:
    course-chat:
      history_limit: 50
      chat_model: gpt-4o
    course-notes: {}              # adopted with definition defaults
  mitxonline-ci:
    course-chat:
      history_limit: 20
  mitx-ci:
    course-chat: {enabled: false} # deliberate non-adoption, recorded
```

`enabled` is a reserved key, not a parameter — a definition may not declare a parameter
by that name. Omitting a feature and writing `enabled: false` both leave it off; the
latter exists so a deliberate decision leaves a trace rather than looking like an
oversight.

A parameter value must satisfy its declared type, and a parameter the definition does
not declare is an error rather than an ignored key. Unsupplied parameters take the
definition's default; a parameter with no default that is never supplied fails compile
for that scope.

### 4.3.2 Per-scope operation overrides and merge semantics

Parameters cover the values a definition anticipated. A scope may also need to override
an *operation* the definition did not parameterise — an escape hatch that should be rare
and visible, since anything overridden repeatedly is a missing parameter:

```yaml
  mitxonline-ci:
    course-chat:
      history_limit: 20
      operations:                 # escape hatch, merged over the definition
        bootstrap:
          waffle_flags:
            - {name: course_chat.enabled, everyone: null, staff: true}
```

"Deep merge" alone is underspecified for the list-valued operations, and the three
plausible policies (replacement, concatenation, identity-keyed) produce different
compiled artifacts and different conflict results, so the contract fixes it:

- **Mappings** merge recursively; the scope's value wins at each leaf key.
- **Lists whose elements have an identity** merge by that identity. A scope entry
  whose identity matches a default entry replaces it wholesale (not field-by-field);
  an unmatched identity is appended. Identities: `extra_slot_files` → `dest`,
  `extra_npm_bundles` → target directory, `commands` → `id`, and for the `bootstrap`
  lists the identities in §4.3.3.
- **Ordering is deterministic**: defaults in declared order, then appended scope
  entries in declared order. Compiled output must be byte-stable across runs so it can
  be diffed and drift-checked.
- **`requires`** belongs to the definition and is not overridable from adoption. A
  feature's dependencies do not change based on where it is turned on.

So the override above carries the same flag `name` as the definition's entry, which
means it *replaces* that entry. It does not add a second registration of the same flag.

### 4.3.3 Bootstrap data and commands

Runtime data a feature depends on (waffle flags, OAuth applications, third-party auth
providers, service accounts and their tokens, users) is declared under
`operations.bootstrap` and validated as a `lehrer.bootstrap.spec.BootstrapSpec`
fragment. That is the model the `lehrer_bootstrap` runner already applies in the
platform image; every model in it sets `extra="forbid"`, so a misspelled field fails at
compile. Anything a `BootstrapSpec` field can hold must be declared there and never as
a command. In particular `create_dot_application` is the wrong contract for an OAuth
client: it logs `client_secret` at INFO, which is why the runner writes through the ORM
instead (`src/lehrer/bootstrap/__main__.py:79`).

`BootstrapSpec` needs two additions before a SAML feature can be expressed:
`saml_configurations` (identity `site_id` + `slug`) and `saml_providers` (identity
`slug`). Both are `ConfigurationModel`s and are applied the way
`third_party_auth_providers` already is, by comparing against the newest row, with the
SP private key read from an env var. The pilot does not need them.

**Composition.** A scope's bootstrap data is the operator's base spec followed by each
adopted feature's fragment, ordered by feature name. (Adoption may come from a scope
block or a set block, so declaration order is not well defined; sorting keeps the
output byte-stable as §4.3.2 requires.) The base spec is the operator's (local
dev declares a superuser with a password, a deployment would not), so compile does not
emit it. Lists concatenate, and entries are compared by identity:

| List | Identity |
|---|---|
| `users`, `service_access_tokens` | `username` |
| `oauth_applications` | `name` (decides replacement under §4.3.2); `client_id_env` must also be unique |
| `third_party_auth_providers` | `backend_name` (the runner keys on it within `SITE_ID`, not on `slug`) |
| `waffle_flags` | `name` |

Two entries with the same identity and equal `model_dump()` collapse into one. Two that
differ are a conflict, and a conflict is a hard error (§4.4.7). Two cross-list clashes
are conflicts too, because the runner would otherwise rewrite one entry with the
other: a `service_access_tokens.application_name` equal to an `oauth_applications.name`
(the token's application is upserted by name), and a `service_access_tokens.username`
equal to a `users.username`. `BootstrapSpec` enforces all of this in a validator, so a
single hand-written file and a merged set fail the same way. Names containing
`{SETTING}` placeholders are compared unresolved; the runner's existing name-clash check
covers what remains after resolution.

The merge function lives in `lehrer.bootstrap.spec`, which may import only pydantic,
PyYAML and the standard library (it runs in the platform image), so compile and the
runner share one implementation. The runner accepts `lehrer_bootstrap SPEC [SPEC ...]`,
merges them by these rules, and refuses to apply anything on a conflict.

**Secrets.** Parameters carry env var names, never secret values. A parameter
substituted into a `*_env` field must match `^[A-Z_][A-Z0-9_]*$`, and a parameter
substituted into any other bootstrap field must not contain `{` or `}`: the runner
resolves `{SETTING}` with `str.format_map` at apply time, so a brace in a compiled value
would be looked up as a Django setting.

**No silent skips for feature entries.** Today the runner skips a third-party auth
provider or service token whose env vars are unset. For a base spec that is the right
default; for an entry a feature contributes it reproduces the silent partial rollout
this RFC exists to remove. Those two models gain `optional: bool = True`, compile emits
`optional: false` on every entry it contributes, and the runner fails on a
non-optional entry whose env vars are unset. `manifest.json` lists every env var the
fragment reads (§4.6) so an operator can check them before the runner does.

**Commands.** `operations.commands` is for work that cannot converge on declared state:
network fetches (`saml --pull` pulls IdP metadata and depends on the remote IdP),
backfills, and recurring jobs. Each entry has an `id`, a `service`, an `argv` and
`recurring: bool`. lehrer emits commands in `checklist.yaml` and never executes them.
When a command turns out to establish state that should simply exist, the fix is a new
`BootstrapSpec` field, not running the command.

### 4.3.4 Frontend build paths

lehrer builds an MFE one of two ways, and they take feature input differently:

- **Legacy MFEs** (`build_legacy_configured`) are built per deployment from a
  `build_config.yaml` baseline plus env vars. `mfe_build_env` and `mfe_assets` apply
  here and merge over the baseline.
- **Site Projects** (`build_site`, frontend-base / OEP-65) are a TypeScript project
  whose `site.config.build.tsx` composes apps and slot operations. `build_site` takes
  the project, shared source, node version and `PUBLIC_PATH`, and nothing else. A Site
  Project artifact is commonly built once and served by every place it is deployed, so
  it cannot take per-scope build input at all.

A Site Project therefore takes no build-time feature input, and `build_site` gains no
new arguments. The code a feature needs is part of the Site Project's own source and is
included unconditionally; its slot operations gate at runtime on keys the feature sets
in `site_config`. frontend-base slot operations accept a `condition` with a `callback`
for this; that is checked against the 1.0.0-alpha.49 types only, and has to be
confirmed on 1.0.1 and 2.0.0-alpha.16 before the first Site Project feature.
`site_config` is the only operation group that reaches a Site Project.

Each scope declares how it builds the MFEs features may touch:

```yaml
scopes:
  mitxonline-production:
    cell: {release: master, deployment: mitxonline}
    frontends:
      learning: legacy                           # built for this scope alone
      instructor-dashboard: {site: mitxonline}   # opaque label for the shared artifact
```

`legacy` means the MFE is built for this scope alone. An operator that builds one legacy
artifact and promotes it between places writes `{legacy: <label>}` instead, and compile
fails if scopes sharing a label resolve different `mfe_build_env` or `mfe_assets` for
that MFE, since one build cannot satisfy both. `manifest.json` records a
`build_digest` per MFE (a hash of the resolved build-time operations) so the same
comparison is available to anyone reading the artifacts.

A definition names the MFEs it needs in `requires.frontends` and the paths it supports
in `frontend_paths`. The keys of `mfe_build_env` and `mfe_assets` must be a subset of
`requires.frontends`. For each required MFE, compile looks it up in the adopting
scope's `frontends`: an MFE the scope does not list is an error, and so is a path the
definition does not support. That is what keeps a feature from silently disappearing
when an MFE moves between paths: when mitxonline's learning MFE becomes a Site Project,
`frontends.learning` changes and every legacy-only definition that needs it stops
compiling for that scope until it gains a `site` implementation.

`frontends` is required only for scopes that adopt a feature with `requires.frontends`.
It also answers the question of an MFE inventory (§9.5): its keys are the inventory,
declared where it is needed and nowhere else.

### 4.3.5 Runtime frontend config (`site_config`)

The MFE runtime config API serves LMS settings: `FRONTEND_SITE_CONFIG` (frontend-base
Site Projects, `/api/frontend_site_config/v1/`) and `MFE_CONFIG` / `MFE_CONFIG_OVERRIDES`
(legacy MFEs, `/api/mfe_config/v1`). Most of their content is topology (URLs, cookie
names, logo, theme), which belongs to the operator. Upstream already draws that line
(checked on master only; verawood's copy still needs reading):
`mfe_config_api/views.py` promotes the keys in `SITE_CONFIG_TRANSLATION_MAP` (and
`PARAGON_THEME_URLS`) to site level and puts every other key under `commonAppConfig`.

`site_config` follows the same line. It may write only:

- `frontend_site_config.commonAppConfig.*`
- `mfe_config.*`
- `mfe_config_overrides.<mfe>.*`

Any other path fails compile, as does any key upstream promotes to site level, in every
target. `FRONTEND_SITE_CONFIG.apps` is not writable: it is a list, and the settings
YAML merge replaces lists whole, so a feature writing it would erase the operator's
apps. App-scoped values go through `mfe_config_overrides`.

These are LMS settings, so compile emits them into `settings/lms.yaml`, where they
deep-merge with the operator's own values; there is no separate `site_config.yaml`.
The settings differ by release (master no longer has the `ENABLE_MFE_CONFIG_API`
toggle; verawood has it alongside `MFE_CONFIG` and `FRONTEND_SITE_CONFIG`; ulmo lacks
`FRONTEND_SITE_CONFIG`), and lehrer's single settings model per group cannot tell a
cell's release apart (§4.4.1), so `site_config` accepts `by_release` and a definition
targets each release explicitly. Like every operation that lands in `settings/`, it is
rejected for cells without django-aqueduct (§4.4.1). Mistakes surface in the extended boot check (§4.4.8), not at
compile.

Features never set `ENABLE_MFE_CONFIG_API`. Upstream removed that toggle on master
(edx-platform `2694cb83b`, 2026-08-26) and both endpoints now answer unconditionally;
on older releases it remains operator configuration. `checklist.yaml` records that the
feature needs the runtime config API, and that a `SiteConfiguration` row for the site
replaces these values whole (upstream reads them through
`configuration_helpers.get_value`).

### 4.4 Validation

Everything here runs in plain Python with no container and no Django, so `check` costs
little enough to run on every commit.

1. **Settings names.** A scope resolves to one cell, and the cell to its deployment
   group's settings tree. There is one committed model per group, serving every aqueduct
   cell in it; `settings_model_release` / `settings_model_deployment` in
   `build_manifest.yaml` name the cell it was generated from (for drift checks), they
   do not select among models. A scope whose cell does not satisfy
   `Cell.uses_aqueduct()` has no settings inventory and nothing to read a settings
   fragment, so `operations.settings`, `operations.features` and
   `operations.site_config` on it are each a compile error.

   The inventory for a service is the union of fields declared along the production
   entry class's bases: the entry class in `settings/<svc>/aqueduct.py` (e.g.
   `LMSProductionSettings`), the lehrer mixins in `src/lehrer/settings/base.py`
   (`ProductionSettingsMixin`, and `StudioSettingsMixin` for CMS; the build injects
   that file as `models/base.py`), and `AqueductSettings` in
   `settings/<svc>/models/aqueduct.py`. The generated model cannot be imported outside
   the platform image (it imports Django, `corsheaders`, `lms.*`), so compile walks the
   classes with `ast.parse`, following `ClassDef.bases` and failing on any base it
   cannot resolve other than `BaseSettings`. It records each field's name and
   `validation_alias`, and skips `ClassVar` (e.g. `FEATURES_COMPAT_KEYS`),
   `model_config` and private names. For mit-ol today this is 935 LMS and 674 CMS
   fields, in about 100 ms. A test asserts the walker's mixin inventory equals the
   mixins' `model_fields`, so the walker cannot drift from the classes it reads. The
   helper does not go in `src/lehrer/settings/base.py` (that file is copied into the
   image); the existing test-only `_declared_field` lookup
   (`tests/settings/test_base.py:412`) is rebuilt on top of it.

   Every key under `operations.settings.<service>` must be in that inventory, for every
   `origin`. Unknown key → compile error. This is the single highest-value check: it
   turns a typo that silently does nothing into a failure at PR time. A setting the
   platform reads but nothing declares is declared on the group's entry class (as
   mit-ol's CMS entry class does for `BULK_EMAIL_*`), not exempted. Two limits to state
   plainly: for cells other than the model cell the check proves the field is declared,
   not that that release reads it; and an env var named after an aliased field is
   ignored by pydantic-settings, so emitters must use the alias (§4.6).
2. **Scope and feature names** — scopes and sets must appear in `scopes.yaml`; every
   feature named in `adoption.yaml` must resolve to exactly one definition, and every
   parameter supplied must be declared by it, with a value matching its declared type.
   Every feature in `requires.features` must be adopted in the same scope; it is never
   adopted implicitly.
3. **Plugin requirements** — `requires.plugins` ⊆ the packages of the scope's cell in
   `build_manifest.yaml`. This is not a literal subset test: `Cell.packages` holds
   verbatim requirement lines (`ol-openedx-chat==0.5.9`) while `requires.plugins`
   names bare distributions, so both sides are canonicalised to PEP 503 normalised
   project names first. `plugin_imports._distribution_name` already implements exactly
   this and should be reused rather than reimplemented. One caveat to state plainly:
   it returns `None` for VCS and direct-reference lines, so a plugin satisfied only by
   a `git+https://…` override is invisible to the check. Such a requirement must fail
   loudly as unverifiable rather than silently pass.
4. **MFE names and build paths.** Every MFE in `requires.frontends` must appear in the
   adopting scope's `frontends`, with a path the definition's `frontend_paths`
   supports (§4.3.4). `build_config.yaml`'s `mfes` map is not used for this: it lists
   only MFEs with baseline customisation (`BuildConfig.mfe()` returns an empty default
   for absent keys, `mfe_config.py:120`).
5. **Slot files.** Every referenced source file must exist in the slot config dir.
6. **Shapes.** Waffle flags as `namespace.name`; npm bundles as `spec|target`; enum
   lookups cover every choice (§4.3).
7. **Conflicts.** A conflict is two features adopted in one scope that resolve one
   target to unequal values. Equal values are not a conflict, and `explain` lists both
   owners. The targets are:
   - one key space per service, in which `features.<svc>.K` and `settings.<svc>.K` are
     the same target (upstream defines `FEATURES = FeaturesProxy(globals())` on ulmo,
     verawood and master, so the two spellings name one setting);
   - mapping leaves, compared individually, and lists, compared whole;
   - MFE build vars per MFE, including against explicit `--env-vars` passed to the
     same build (which stay the channel for values no feature owns, such as domains
     and logos);
   - identity-keyed entries (§4.3.2, §4.3.3), which conflict when one identity has
     different content;
   - slot-file `dest` paths and npm bundle target directories, including against the
     `build_config.yaml` baseline.

   There is no precedence between peers: order-dependent resolution is what makes
   today's configuration unexplainable. A conflict is resolved by making the values
   agree, parameterising one feature, or moving the key into a third feature that both
   list under `requires.features`. The error names the target, both features, both
   values and both source files. Nothing detects this today, and it only becomes
   possible once definitions are separate from adoption.

   One limit is outside lehrer's view: operator-supplied settings. An environment
   variable of the same name overrides an emitted YAML fragment
   (`src/lehrer/settings/base.py:14`), and so may an operator YAML file that sorts
   later. `explain --scope` lists every target a scope's features write so the
   operator can check.
8. **FEATURES keys** are not statically checkable. `FEATURES` is typed `Any` with a
   `FeaturesProxy(globals())` default (`lms/models/aqueduct.py:757`), and only 38 of
   mit-ol's 69 `FEATURES_COMPAT_KEYS` are generated fields, so no complete static key
   set exists. The earlier draft deferred this to the settings-verify CI tier, but that
   tier does not check it: `verify_settings` (`src/lehrer/core/platform.py:3108`) runs
   the boot self-test with no `OL_SETTINGS_DIR`, `manage.py check` and the drift check,
   and never loads a settings fragment. Checking FEATURES keys means extending it to
   boot with each scope's compiled `settings/` fragment. That is Phase 3 work (§8);
   until then FEATURES keys get shape checks only.
9. **Bootstrap fragments.** Each fragment validates as a `BootstrapSpec`, with the
   parameter restrictions in §4.3.3. `features check --base-spec <file>` additionally
   merges each scope's fragment with the operator's base spec and reports conflicts.

### 4.5 CLI

```
lehrer features compile  --group <g> --scope <s> --out <dir>
lehrer features check    --group <g> [--base-spec <file>]  # validate all scopes, emit nothing
lehrer features catalog  [--group <g>]           # every definition, with parameters
lehrer features adopted  --group <g> --scope <s> # what this scope takes, resolved
lehrer features explain  <feature> [--group <g>] [--scope <s>]
```

`check` is a cheap CI gate alongside the existing `build-config-schema` /
`build-manifest-schema` hooks.

`catalog` and `adopted` are the two halves the split makes possible: what *can* be
turned on (definitions, independent of any deployment — with no `--group`, lehrer's
shipped upstream-native catalog alone) versus what a given scope *has* turned on.
`explain` prints one feature's fan-out; without `--scope` it prints the contract with
parameter placeholders intact, with `--scope` the values resolved for that deployment.

Path-reasoning logic lives in `src/lehrer/cli/`, not `core/`: the `lehrer-core-boundary`
pre-commit hook forbids a `deployments/` path or import under `src/lehrer/core/`.

### 4.6 Artifact contract

`compile` writes a versioned tree. `contract_version` is independent of the manifest
`version`, so consumers pin against output format, not input schema.

```
<out>/
  manifest.json            # {contract_version: 1, group, scope, generated_from, frontends,
                           #  build_digest: {<mfe>: ...}, bootstrap_env: [...]}
  settings/lms.yaml        # OL_SETTINGS_DIR-shaped fragment, including site_config (§4.3.5)
  settings/cms.yaml
  bootstrap.yaml           # BootstrapSpec holding feature-contributed entries only
  mfe_build_env/<mfe>.env  # KEY=VALUE, legacy-path MFEs only
  mfe_assets/<mfe>.yaml    # resolved slot files and npm bundles, legacy-path MFEs only
  checklist.yaml           # required services, plugins, commands, runtime config API
```

Settings fragments are keyed by field name. A consumer that materialises them as
environment variables instead uses the field's `validation_alias` where one is set
(three fields today, e.g. `ENABLE_AUTHN_MICROFRONTEND` ← `EDXAPP_ENABLE_AUTHN_MFE`),
because pydantic-settings reads only the alias from the environment and silently drops
the field name. The settings models use no `env_prefix` and no nested delimiter, so a
nested value as an env var is one JSON string. Emitting YAML avoids both issues, which
is why YAML is the contract.

`mfe_assets/<mfe>.yaml` holds the *resolved* result — `by_release` already collapsed
to concrete filenames for the scope's cell, merge order already applied — so a
non-lehrer build system gets a flat list it can act on without reimplementing
resolution. For `course-chat` on an ulmo cell:

```yaml
contract_version: 1
extra_slot_files:
  - {source: ChatSidebar.jsx, dest: ChatSidebar.jsx}
  - {source: ChatCoordinator.ulmo.jsx, dest: ChatCoordinator.jsx}
extra_npm_bundles:
  - {spec: "@example/chat-ui@^1.4.0", target: public/static/chat-ui}
```

`bootstrap.yaml` is passed to `lehrer_bootstrap` alongside the operator's base spec
(§4.3.3). The earlier draft emitted a `waffles.yaml` for `set_waffle_flags.py`; that is
dropped, because a waffle list cannot carry the OAuth and auth-provider data a feature
also needs, and the bootstrap runner already covers waffle flags. `set_waffle_flags.py`
stays in the image for operators who use it directly; the manifest does not feed it.

### 4.7 Self-served versus emitted operations

Two of these operation groups describe steps **lehrer itself performs**. For those, requiring a
consumer to read a file and hand values back to lehrer is a pointless round trip.

A `--scope` string alone is not sufficient to close that loop, though.
`build_legacy_configured` receives `slot_config` as a `dagger.Directory` plus
`deployment_name`/`release_name` as plain strings; it has no path to a group's manifest
tree, and the `lehrer-core-boundary` pre-commit hook forbids a `deployments/` path or
import anywhere under `src/lehrer/core/`, so core cannot construct one. Scopes
are also group-local, and two groups may legitimately use the same cell coordinates.

The build functions therefore take **two** new inputs: `--features`, a
`dagger.Directory` holding the group's `features/` tree (mirroring how `--slot-config`
is already passed), and `--scope`, the label to resolve within it. Path reasoning stays
in `src/lehrer/cli/`, which is where the group layout is allowed to be known.

| Operation group | lehrer self-serves | Also emitted |
|---|---|---|
| `mfe_build_env` | yes, legacy path, via `--features` + `--scope` | yes |
| `mfe_assets` | yes, legacy path, via `--features` + `--scope` | yes |
| `settings`, `features`, `site_config` | no | yes (`settings/<svc>.yaml`) |
| `bootstrap` | applied by `lehrer_bootstrap` in the image; the operator decides when it runs | yes (`bootstrap.yaml`) |
| `commands`, `requires` | no | yes (checklist) |

Only `build_legacy_configured` gains the two flags; `build_site` gains nothing (§4.3.4).

Everything is emitted regardless, so an operator using a different build system is never
locked out. Both new flags are purely additive: omit them and every existing explicit
argument behaves exactly as it does today.

## 5. AI drawer as a manifest

The corrections in §2.2 shrink the drawer's definition to one operation. The slot
files and the smoot-design bundle are imported by both implementations, so they stay in
`build_config.yaml` as baseline; the stylesheet rules are inert without the drawer and
stay in the deployment sheet. What is left is the choice between the two
implementations, which is an enum:

```yaml
# deployments/mit-ol/features/definitions/ai-drawer.yaml
version: 1
feature: ai-drawer
summary: AskTIM chat drawer in the learning MFE, slot-based or standalone bundle.
origin: plugin
provided_by: ol-openedx-chat
frontend_paths: [legacy]
parameters:
  implementation:
    type: enum
    choices: [slot, standalone]
    default: standalone
requires:
  plugins: [ol-openedx-chat]
  frontends: [learning]
operations:
  mfe_build_env:
    learning:
      ENABLE_AI_DRAWER_SLOT:
        by_parameter: implementation
        cases: {slot: "true", standalone: "false"}
```

```yaml
# adoption.yaml
adoption:
  mitxonline-all:
    ai-drawer: {implementation: slot}
```

One JSX change comes first. The `right_sidebar` entry moves out of the
`DEPLOYMENT_NAME?.includes("mitxonline")` block in `learning-mfe-config.env.jsx` so the
build var alone picks the implementation; the rest of that block is mitxonline's
baseline slot customisation and is not part of this feature. Until it moves, adopting
the drawer outside mitxonline compiles but has no effect.

Two limits of the pilot to state plainly. The current code has no "off" state, so not
adopting the feature compiles the same as `standalone`; an off state is a code change
in the drawer, not something the manifest can add. And the pilot is legacy-only: the
Site Project copy under `frontend/shared/src/ai-drawer/` is not registered in any site
config and its coordinator is a stub. When mitxonline's learning MFE moves to a Site
Project, its scopes' `frontends.learning` changes to `{site: ...}` and compile rejects
the drawer for them until the definition adds `site` to `frontend_paths` and a
`site_config` key that the slot operation's condition checks. (The Site Project
component already reads its bundle path from `commonAppConfig.mitolAIDrawer`; an
enable key would be new.)

The companion feedback drawer's `feedback.feedback_enabled` waffle flag is a per-course
gate. Whether it needs course-override rows, which `BootstrapSpec` cannot express, is
not yet known, so it is left out of the pilot.

## 6. Relationship to existing configuration

- **`build_manifest.yaml`** — unchanged. It owns build definitions per cell; feature
  manifests reference cells through `scopes.yaml` and never duplicate their content.
- **`build_config.yaml`** — remains the *baseline*, unconditional MFE customisation.
  Feature definitions contribute the *conditional* subset. `build_legacy_configured`
  merges baseline with the operations resolved for the requested scope; no second
  generated file, so no drift gate is needed. Migrating an existing entry from
  `build_config.yaml` into a definition is a deliberate, reviewable move.
- **`lehrer.bootstrap`** — unchanged in role. It stays the applier for users, OAuth
  applications, auth providers, tokens and waffle flags; the manifest contributes
  fragments to it. The changes it needs are additive: multi-file input with the merge
  rules of §4.3.3, the uniqueness validator, `optional` on providers and tokens, and
  (when a SAML feature arrives) the two SAML lists.
- **Site Projects** — unchanged. Their `site.config.build.tsx` stays the place apps and
  slot operations are composed; features reach them only through `site_config` (§4.3.4).
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
  during the platform build, next to the `lehrer_bootstrap` runner the image already
  carries. No external plumbing whatsoever. Cost: a flag flip becomes an image rebuild.
- **Read at deploy time** — the deployment tool reads the artifact tree and materialises
  it (ConfigMaps, env, mounted files). Keeps flips at deploy latency; costs the operator
  a way to obtain the tree.
- **Vendor the artifacts** — sync compiled output into the deployment repo, reviewed
  there. Explicit, at the cost of a two-repo dance and a drift surface.

An operator may mix these per layer. Waffle flags are deliberately the *fast* lever in
most Open edX deployments, and an operator who values that can keep `bootstrap.yaml`
at deploy latency (read at deploy time and passed to the runner by a pre-deploy job)
while sourcing build-time layers from lehrer. The runner is idempotent and reports
created / updated / unchanged per object, so running it on every deploy is safe.

## 8. Rollout

- **Phase 0** — schema (`src/lehrer/core/feature_manifest.py`, including scope sets,
  `frontends`, enum parameters and `requires.features`, plus the reserved `vendored/`
  directory and entry-point group), `compile`, `check`, `catalog`, `adopted` and
  `explain`, and the static settings inventory walker with its parity test.
  In `lehrer.bootstrap`: the merge function, the uniqueness validator, multi-file
  input, and `optional` on providers and tokens. No consumer changes. Write
  definitions for what already exists and diff the compiled artifacts against what each
  operator produces by hand; equivalence is the acceptance test. Definitions can be
  written and validated before any deployment adopts them, so this phase carries no
  deployment risk at all.
- **Phase 1** — AI drawer pilot, legacy path only. Move the `right_sidebar` entry out
  of the `DEPLOYMENT_NAME` block (§5), then add `--features` and `--scope` to
  `build_legacy_configured` (`src/lehrer/core/mfe.py:300`).
- **Phase 2** — runtime operations: settings fragments (including `site_config`) and
  `bootstrap.yaml`, per whichever channel each operator selects. The bootstrap runner
  already exists, so this phase is wiring, not a new runtime role. Cells without
  django-aqueduct (mit-ol's ulmo/xpro today) have nothing to read a settings fragment,
  and compile rejects settings operations for them (§4.4.1).
- **Phase 3** — migrate remaining features; add `features check` to CI; extend
  settings-verify to boot with each scope's compiled `settings/` fragment, which is what
  finally checks FEATURES keys and per-release `site_config` targets (§4.4.8).

Every phase is independently revertable, and Phase 0 changes no behaviour at all.

## 9. Open questions and their resolutions

Each question from the August draft is kept, followed by the proposed resolution this
revision adopts. Review of this revision is where they are accepted or reopened.

1. **Scope granularity.** Is one flat label per (deployment, place-it-runs) right, or do
   operators need composition?
   *Resolved: flat, plus one level of sets (§4.2).* Inheritance chains are not added.
   Sets cover the real case (one cell run in CI, QA and Production with mostly the same
   features) with the same one-level shape as `build_manifest.yaml`'s defaults, and a
   scope's own block still wins per parameter.
2. **Conflict policy.** Hard error, or an explicit precedence declaration?
   *Resolved: hard error, with the targets defined exactly and no precedence field
   (§4.4.7).* Every overlap in today's configuration is resolved silently by order
   (env over YAML, later YAML file over earlier, explicit FEATURES over the compat
   mirror); that is the confusion this replaces. The way out of a conflict is agreement,
   a parameter, or a shared feature named in `requires.features`.
3. **`commands` scope.** Checklist, or should lehrer run them?
   *Resolved: lehrer applies declarative data and does not run commands (§4.3.3).*
   Data that converges (users, OAuth applications, auth providers, tokens, waffle
   flags, later SAML) is a `BootstrapSpec` fragment applied by the `lehrer_bootstrap`
   runner lehrer already ships; the operator decides when it runs. Arbitrary commands
   stay a checklist, because they cannot report created / updated / unchanged.
4. **`site_config` overlap.** Does the manifest carry only the feature-owned subset,
   and how is the boundary kept honest?
   *Resolved: yes, enforced by path (§4.3.5).* Features may write
   `commonAppConfig.*`, `mfe_config.*` and `mfe_config_overrides.<mfe>.*` only, and
   never keys upstream promotes to site level. They never set `ENABLE_MFE_CONFIG_API`.
5. **MFE inventory.** Should lehrer gain an authoritative list of the MFEs an operator
   builds?
   *Resolved: yes, as the keys of each scope's `frontends` (§4.3.4)*, required only
   for scopes that adopt a feature touching an MFE. The same declaration carries the
   build path, which is what lets compile reject a feature when an MFE moves to a Site
   Project.
6. **Style fragments vs. extraction.**
   *Resolved for v1: neither.* `style_fragments` is dropped (§4.3), and extraction of
   feature rules from baseline sheets is deferred. Rules that select only a feature's
   own classes are inert when the feature is off, so neither is needed for
   correctness. Revisit when a feature's rules restyle shared elements.
7. **Where plugin-contributed definitions belong.**
   *Resolved: in the plugin, eventually; reserved now (§4.1).* A distribution ships
   `<feature>.yaml` as package data and advertises it in the `lehrer.features`
   entry-point group. Compile runs without plugins installed, so a later
   `lehrer features vendor --cell <release>/<deployment>` reads those files in the
   cell's built image (as codegen already reads `plugin_settings()` there) and writes
   them to `features/vendored/<dist>/<version>/`; compile uses the copy matching the
   cell's exact pin and fails on ranges or VCS lines as unverifiable. Vendored
   definitions must be `origin: plugin` with `provided_by` set to the distribution. v1
   reserves the directory and the entry-point group and enforces cross-source name
   uniqueness; it implements none of the rest. `requires.features`, which lets an
   operator definition build on a plugin's, is implemented in v1 (§4.4.2). (ol-openedx-chat's wheel
   includes only `*.py` and `static/`, so shipping YAML needs a packaging change
   there.)
8. **Parameter expressiveness.** Enums? Conditional operations?
   *Resolved: enums and `by_parameter` lookups, nothing more (§4.3).* A lookup must
   cover every choice, and `null` omits a key. Conditional inclusion of operation
   groups, expressions and comparisons are out. The drawer needs only the enum (§5).

New open items from this revision:

- **Off states that code does not have.** The drawer has no "off" (§5). Other
  features will be the same; the manifest can only select among states the code
  implements.
- **Course-level waffle overrides.** `BootstrapSpec` sets global flag state only.
  Whether any pilot-adjacent feature needs per-course override rows is unconfirmed.
- **frontend-base slot conditions** need confirming on 1.0.1 and 2.0.0-alpha.16 before
  the first Site Project feature (§4.3.4).

## Appendix A — MIT OL integration (non-normative)

Illustrative only; no part of the schema depends on it. ol-infrastructure references are
at `b3c996f92`.

MIT OL builds via Concourse pipelines that already clone lehrer as a git resource with a
path filter (`src/ol_concourse/pipelines/open_edx/mfe/pipeline.py:275`), so compiled
artifacts committed under a filtered path would both be present on disk in the build
task and trigger a rebuild when they change. Build-time layers would be self-served: the
per-feature `--env-vars` flags currently generated from `values.py` collapse into a
single `--scope`, while topology vars (domains, logos, URLs) stay where they are.

Runtime layers have no existing channel — the edxapp Pulumi stack never sees lehrer.
Waffle data is stack config (`edxapp:waffle_flags`), rendered to a ConfigMap
(`k8s_configmaps.py:934`) and consumed by an `lms-waffleflag` pre-deploy command
(`k8s_resources.py:1145`); `FRONTEND_SITE_CONFIG` is a Python literal
(`k8s_configmaps.py:242`). One plausible path is for that pre-deploy command to run
`lehrer_bootstrap` against the compiled `bootstrap.yaml` instead of the stack's waffle
list. Today's lists are mostly shared across environments (for mitxonline, 40 flags
are common to CI, QA and Production out of 42, 43 and 40), which is the case scope sets
exist for. Adopting any of §7's channels is a separate ol-infrastructure decision, to be
taken there.

Site Projects are built once and promoted CI → QA → Production
(`docs/creating-a-deployment.md:386`), which is why §4.3.4 gives them no build-time
input. Legacy MFEs are rebuilt per environment from the revision that passed CI
(ol-infrastructure `mfe/pipeline.py:213`), so `frontends.<mfe>: legacy` fits them.
