# Implementation: Declarative Build Manifest (absorb the ol-infrastructure build matrix)

## Context

Today the inputs that decide **what** gets built for each Open edX deployment are split
across two repos:

- **`lehrer`** owns the Python package sets: `deployments/<group>/pip_package_lists/<release>/<deployment>.txt`
  and `pip_package_overrides/<release>/<deployment>.txt` (10 sparse cells across `mit-ol` and
  `generic`).
- **`ol-infrastructure`** owns everything else in `src/bridge/settings/openedx/`
  (`types.py`, `accessors.py`, `version_matrix.py`): per-`(release × deployment)` edx-platform
  repo + branch, python/node version, theme repo + branch, translations repo, and
  `packages_to_remove`. Its Concourse pipeline
  (`src/ol_concourse/pipelines/open_edx/edx_platform_v3/pipeline.py`) reads that matrix and
  invokes `dagger call platform build-platform ... --pip-package-lists ./deployments/mit-ol/...`
  against `lehrer`.

Consequences:

1. **No single source of truth.** A reader of `lehrer` cannot tell which edx-platform branch,
   python version, or theme a given cell builds against — that lives only in `ol-infrastructure`.
2. **Floating build inputs.** Until PR #91, several plugins floated to latest at build time
   (now pinned). But branch/translations/`packages_to_remove` still live only in Concourse and
   change with no signal in `lehrer`.
3. **The plugin-compat CI matrix (`plans/05` Task 4) cannot be built** without re-deriving the
   per-cell branch/namespace/`packages_to_remove` that only exist in `ol-infrastructure`.

**Goal (directional, per @tmacey 2026-07):** make `lehrer` the single declarative source of
truth for each cell's **full edx-platform build parameters**, so `ol-infrastructure`'s Concourse
pipeline (and any other consumer/team) drives a build purely from a cell reference into a
committed manifest. Renovate drives every plugin/param bump through a `lehrer` PR, and the
plugin-compat matrix / canary read the same manifest.

**Scope of THIS iteration:** the **edx-platform build cell** — everything `build_platform` needs
to build one deployment's LMS/CMS image from scratch. The rest of the `bridge.settings.openedx`
matrix (MFEs, codejail, notes, xqueue/xqwatcher — each a *separate* dagger build target) is a
deliberate later iteration; the schema is designed to grow into it. This work is the foundation
`plans/05` Tasks 3–5 sit on and overlaps the **"feature manifest layer"** project — coordinate.

---

## The matrix data to migrate (sourced from `ol-infrastructure@main`)

`OpenEdxSupportedRelease`: `master` (branch `master`, py 3.12, node 24), `ulmo`
(`release/ulmo`, py 3.11, node 24), `verawood` (`release/verawood`, py 3.12, node 24).

Group **`mit-ol`** — uniform across all cells: `settings_namespace: mitol`,
`extra_ssh_hosts: [github.mit.edu]`, `translations_branch: main`,
`extra_npm_packages: ["git+https://github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732"]`,
`custom_settings: ./deployments/mit-ol/settings`.

| release | deployment | platform_repo | platform_branch | py | node | translations_repo | packages_to_remove | theme_repo | theme_branch |
|---|---|---|---|---|---|---|---|---|---|
| master | mitxonline | openedx/edx-platform | `master` | 3.12 | 24 | mitodl/mitxonline-translations | `[edx-name-affirmation]` | mitodl/mitxonline-theme | `main` |
| master | mitx | openedx/edx-platform | `master` | 3.12 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `master` |
| master | mitx-staging | openedx/edx-platform | `master` | 3.12 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `master` |
| ulmo | mitx | **mitodl/edx-platform** | `mitx/ulmo` | 3.11 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `ulmo` |
| ulmo | mitx-staging | **mitodl/edx-platform** | `mitx/ulmo` | 3.11 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `ulmo` |
| ulmo | xpro | openedx/edx-platform | `release/ulmo` | 3.11 | 24 | openedx/openedx-translations | `[]` | mitodl/mitxpro-theme | `ulmo` |
| verawood | mitx | **mitodl/edx-platform** | `mitx/verawood` | 3.12 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `verawood` |
| verawood | mitx-staging | **mitodl/edx-platform** | `mitx/verawood` | 3.12 | 24 | openedx/openedx-translations | `[]` | mitodl/mitx-theme | `verawood` |
| verawood | xpro | openedx/edx-platform | `release/verawood` | 3.12 | 24 | openedx/openedx-translations | `[]` | mitodl/mitxpro-theme | `verawood` |

Group **`generic`** — one cell (`master/generic`), `lehrer`-only (not in the ol-infra matrix):
upstream `openedx/edx-platform@master`, py 3.12, node 24, `openedx/openedx-translations`, no
theme, no npm/ssh/`packages_to_remove`, `custom_settings: ./deployments/generic/settings`.

**Corrections vs stale `deployments/mit-ol/build.md`:** `build.md` shows `mitx` using
`mitodl/mitx-translations` and release `teak` — both wrong. The live pipeline uses
`openedx/openedx-translations` for every non-mitxonline cell, proctortrack + `github.mit.edu` on
**all** cells, and releases `master`/`ulmo`/`verawood`. Trust the table above; refresh `build.md`.

---

## 1. Manifest schema — Pydantic in core, data under `deployments/`

New module `src/lehrer/core/build_manifest.py`: pure (no `dagger`, no OL-specific strings — must
pass the `lehrer-core-boundary` pygrep hook). One manifest per group at
`deployments/<group>/build_manifest.yaml`. Mirrors the existing `core/mfe_config.py` +
`mfe_slot_config/legacy/build_config.yaml` + `build_config.schema.json` pattern exactly.

```yaml
# yaml-language-server: $schema=../../build_manifest.schema.json
version: 1
defaults:                       # group-uniform values; a cell may override any
  settings_namespace: mitol
  platform_repo: https://github.com/openedx/edx-platform
  translations_repo: https://github.com/openedx/openedx-translations
  translations_branch: main
  node_version: "24"
  extra_ssh_hosts: [github.mit.edu]
  extra_npm_packages:
    - git+https://github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732
release_python:                 # release -> python; cell.python_version overrides
  master: "3.12"
  ulmo: "3.11"
  verawood: "3.12"
cells:
  - release: master
    deployment: mitxonline
    platform_branch: master
    translations_repo: https://github.com/mitodl/mitxonline-translations
    packages_to_remove: [edx-name-affirmation]
    theme_repo: https://github.com/mitodl/mitxonline-theme
    theme_branch: main
    packages:                   # verbatim active requirement lines, order-preserved
      - celery-redbeat==2.3.3  # Support for using Redis as the lock for Celery schedules
      - granian==2.7.9
      - ol-openedx-logging==0.3.5
      - openedx-scorm-xblock==19.0.4
      - setuptools==81.0.0
      # ...
    overrides:
      - git+https://github.com/verificient/edx-proctoring-proctortrack.git@31c6c99...#egg=edx_proctoring_proctortrack
      - lxml==5.3.0
      - xmlsec==1.3.14
      - ol-openedx-course-translations==0.8.0
  # ... 8 more mit-ol cells; generic has its own build_manifest.yaml
```

Models (all with `model_config = ConfigDict(extra="forbid")`):

- `BuildManifest`: `version: int`, `defaults: CellDefaults = CellDefaults()`,
  `release_python: dict[str,str] = {}`, `cells: list[Cell]` (min_length 1). Validator: no
  duplicate `(release, deployment)` pairs.
- `CellDefaults`: optional group-wide `settings_namespace`, `platform_repo`, `translations_repo`,
  `translations_branch`, `node_version`, `extra_ssh_hosts: list[str] = []`,
  `extra_npm_packages: list[str] = []`.
- `Cell`: `release: str`, `deployment: str`, `packages: list[str]` (min_length 1),
  `overrides: list[str] = []`, and optional per-cell overrides of every `CellDefaults` field
  plus `platform_branch`, `python_version`, `theme_repo`, `theme_branch`,
  `packages_to_remove: list[str] = []`.
- Pure methods (unit-testable, no dagger): `resolve_cell(release, deployment) -> Cell` (raises a
  clear `ValueError` listing available cells — replaces today's opaque "missing .txt" failure,
  earlier); `Cell.resolved(field, manifest)` helpers that apply cell→defaults→release fallback;
  `Cell.render_packages()/render_overrides() -> str` (`"\n".join(lines) + "\n"`, order preserved).
- `json_schema() -> dict` + `if __name__ == "__main__"` printer — identical to `mfe_config.py`.

**Representation:** `packages`/`overrides` are `list[str]` of verbatim **active** requirement
lines (specifier + optional inline `# comment` kept — valid pip syntax). Blank lines and
standalone `#`-header lines are dropped (cosmetic). **DRY:** verbatim-per-cell for this migration
(no shared-base/diff model yet) so the faithfulness proof (§3) is a direct equality; revisit DRY
only once the matrix CI can catch regressions.

---

## 2. Migration mechanics — lowest-risk, additive

**Leave `install_deps` (`platform.py:228`) 100% unchanged** — it stays the tested primitive
taking two `dagger.Directory`s and doing the `edx_base.txt`/`edx_assets.txt` copy + `uv pip
install`. Do **not** teach it YAML.

Add an **additive** `build_manifest: dagger.File | None = None` parameter to `build_platform`
(`platform.py:934`) and `regenerate_aqueduct_settings` (`platform.py:1134`). When provided:

1. `manifest = BuildManifest.model_validate(yaml.safe_load(await build_manifest.contents()))`
2. `cell = manifest.resolve_cell(release_name, deployment_name)`
3. Materialize the two dirs in the layout `install_deps` already expects:
   ```python
   lists     = dag.directory().with_new_file(f"{release_name}/{deployment_name}.txt", cell.render_packages())
   overrides = dag.directory().with_new_file(f"{release_name}/{deployment_name}.txt", cell.render_overrides())
   ```
   (empty overrides → present-but-empty file, so the existing `-r .../overrides.txt` resolves —
   matches today's comment-only generic override.)
4. Resolve `platform_repo`, `platform_branch`, `python_version`, `node_version`,
   `settings_namespace`, `translations_repo`, `translations_branch`, `extra_npm_packages`,
   `extra_ssh_hosts`, `packages_to_remove`, `theme_repo`, `theme_branch` from the cell **only
   when the caller did not pass an explicit value** (explicit CLI arg always wins — keeps
   `--source`-based Concourse builds working).
5. Feed the materialized dirs into the unchanged `install_deps`.

The dagger-coupled materialization helper lives in `platform.py`; all parsing/rendering/resolution
lives in pure `build_manifest.py`. Keep `pip_package_lists`/`pip_package_overrides` as optional
params (fallback when no manifest) so external Concourse migrates on its own schedule.

Add thin CLI conveniences in `src/lehrer/cli/build.py`:
- `lehrer build platform --cell <group>/<release>/<deployment>` resolves the group's manifest path
  + cell coordinates and forwards to `platform build-platform --build-manifest ...`.
- `lehrer build cells [--manifest PATH]` prints the `(release, deployment)` cells in a manifest —
  the **consumption API** ol-infra's Concourse generator calls to cross-check its topology
  coordinates against the manifest (see §8). Backed by the pure `BuildManifest.load_manifest()` so
  external consumers can `import` it instead of shelling out.

**Node version caveat (implementation detail to settle in PR 1):** the manifest stores major
`"24"`; the live pipeline resolves the latest `24.x.y` from the nodejs GitHub releases at build
time, whereas `build_platform`'s current default is a stale `20.18.0`. Options: (a) store a
concrete pinned `node_version` (Renovate-managed) — simplest & reproducible; (b) keep `"24"` and
have `nodeenv` resolve latest. Recommend (a) with a pinned value, flagged below.

---

## 3. Faithfulness test (behavior-preservation proof)

`tests/core/test_build_manifest.py` (pytest, pure — imports `BuildManifest`, reads files off
disk; no dagger). Canonical comparison strips pip inline comments without harming `#egg=`:

```python
def effective_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()  # space-then-# only
        if line and not line.startswith("#"):
            out.append(line)
    return out
```

For each of the 10 cells assert order-preserving list equality between
`effective_lines(cell.render_packages())` and `effective_lines(<committed .txt>)` (and
overrides). Install order matters (overrides last; translation plugins at the end).

Also assert against the §-matrix table: each cell's resolved `platform_repo`, `platform_branch`,
`python_version`, `translations_repo`, `packages_to_remove`, `theme_*`, `settings_namespace`
equals the expected value — this pins the ol-infra values we migrated so drift is caught.

Permanent tests independent of the `.txt`: schema round-trip, all 10 expected `(release,
deployment)` cells present, no duplicates, `resolve_cell` raises on unknown pair, every rendered
line is a valid pinned/range/`git+`/bare requirement.

**Sequencing:** keep the `.txt` trees in the migration PR so the equality test runs against the
real committed files (self-evident proof, runs in fast-checks CI). Delete `.txt` in the next PR.

---

## 4. Renovate custom manager

In `renovate.json`:

```json
"customManagers": [
  {
    "customType": "regex",
    "managerFilePatterns": ["/deployments/.+/build_manifest\\.ya?ml$/"],
    "matchStrings": ["(?<depName>[A-Za-z0-9][A-Za-z0-9._-]*?)(\\[[^\\]]+\\])?==(?<currentValue>[0-9][^\\s#]*)"],
    "datasourceTemplate": "pypi",
    "versioningTemplate": "pep440"
  }
]
```

Matches `name==x.y.z` and `pydantic-settings[yaml]==2.14.2` (extras excluded from `depName`).
Git URLs (`#egg=`, no `==`), ranges (`nodeenv>=1.7.0`), and bare names (`opentelemetry-api`) are
intentionally unmanaged. **Add a disable rule** so the deliberate `setuptools==81.0.0` (<82 for
`pkg_resources`), plus `pip`/`wheel`, are never bumped:
`{ "matchDepNames": ["setuptools","pip","wheel"], "enabled": false }`. Keep the old
`pip_requirements` block only while the `.txt` overlap exists; remove it in the deletion PR.

---

## 5. Schema JSON + pre-commit hook

Commit `build_manifest.schema.json` at repo root (next to `build_config.schema.json`), regenerated
from `build_manifest.json_schema()` by a new **local** hook mirroring `build-config-schema`:

```yaml
- id: build-manifest-schema
  name: regenerate build_manifest JSON schema from the Pydantic models
  language: system
  entry: "bash -c 'uv run python -c \"import json; from lehrer.core.build_manifest import json_schema; print(json.dumps(json_schema(), indent=2))\" > build_manifest.schema.json'"
  files: ^(src/lehrer/core/build_manifest\.py|build_manifest\.schema\.json)$
  pass_filenames: false
```

Add to `ci.skip` (pre-commit.ci lacks the uv env, same as `build-config-schema`) and enforce it in
the fast-checks GH Actions job (`plans/05` Task 2 pattern; already live in `.github/workflows/ci.yml`).
`mypy` already covers `src/lehrer/core/` so the model is type-checked.

---

## 6. Consumer / doc updates

- **`local-dev/lehrer-core.star:208-228`** — swap `--pip-package-lists .../pip_package_lists
  --pip-package-overrides .../pip_package_overrides` for `--build-manifest
  <dep_cfg>/build_manifest.yaml`; update the Tilt `deps=[...]` list.
- **`deployments/mit-ol/build.md`** — rewrite with `--build-manifest` and the corrected matrix.
- **`README.md`**, **`docs/creating-a-deployment.md`**, **`deployments/mit-ol/README.md`**,
  **`.github/copilot-instructions.md`**, **`local-dev/Tiltfile`** / **`cli/local_dev.py`** usage
  strings — describe the manifest and `--build-manifest`; drop the `pip_package_lists/<r>/<d>.txt`
  layout docs.
- **External `ol-infrastructure`** — its Concourse `build-platform` call must switch to
  `--build-manifest ./deployments/mit-ol/build_manifest.yaml` and stop reading
  `bridge.settings.openedx` for the edx-platform build params. Coordinate before the `.txt`
  deletion PR (below).

---

## 7. PR sequencing

- **PR 0 — done:** pin floating plugins (#91).
- **PR 1 — manifest foundation:** `build_manifest.py` + `json_schema()` +
  `build_manifest.schema.json` + pre-commit hook; both `build_manifest.yaml` files (verbatim
  packages, all params from §-matrix); additive `--build-manifest` on `build_platform` /
  `regenerate_aqueduct_settings` + materialization; `lehrer build platform --cell`; faithfulness
  test; Renovate `customManagers` + disable rule (keep old block); switch star file + docs.
  **Keep `.txt` trees.** Green faithfulness test = behavior-preservation proof.
- **PR 2 (ol-infra) — cutover:** Concourse switches to `--build-manifest`. Land before PR 3.
- **PR 3 — remove legacy:** delete `pip_package_lists`/`pip_package_overrides` trees + old
  `renovate.json` `pip_requirements` block; retire the render↔txt test (keep schema/matrix tests).
- **PR 4+ (`plans/05`):** plugin-compat matrix / `verify_plugins`, dagger `test` targets, canary —
  all read the manifest as source of truth.

---

## 8. Concourse pipeline generation & deployment topology

The `edx_platform_v3` pipeline is **generated dynamically** from `bridge.settings.openedx`, not
hand-written. Its generator does two fan-outs:

```
for release in OpenEdxSupportedRelease:
    for deployment in filter_deployments_by_release(release):   # ← BUILD fan-out
        build job "build-{release}-{deployment}-edxapp-image"   (dagger build-platform)
        pulumi deploy chain over deployment.envs_by_release(release)   # ← DEPLOY fan-out
            stacks = [f"{deployment}.{stage}" for stage in ...]; OPENEDX_RELEASE=release
```

So `bridge.settings.openedx` supplies **two distinct things**: (1) the per-cell **build params**
(this spec's target) and (2) the **deployment × env-stage × release topology**
(`env_release_map`) that decides *which* build jobs exist and *which env stages* each built image
deploys to (`mitx`/`mitx-staging`: CI=master, QA=verawood, Prod=ulmo; `mitxonline`: all=master;
`xpro`: CI=verawood, QA=ulmo, Prod=ulmo).

Moving only (1) to Lehrer leaves Concourse reading both repos, with a **silent-drift hazard**: if
the topology pins a `(release, deployment)` that has no Lehrer manifest cell (or vice-versa),
pipeline generation emits a deploy chain for an image that never builds.

**Decided boundary (one home per fact) — ol-infra owns the topology and consumes Lehrer's
manifests.** Lehrer's schema deliberately has **no** concept of env stages, so no operator
deployment-topology assumptions leak into the generic core:

- **Lehrer manifest** = the *build definition* of each `(release, deployment)` cell (this spec's
  fields). Source of truth for **what/how to build**.
- **ol-infra `bridge.settings.openedx`** = the *target topology* only: `deployment → {env_stage:
  release}` (today's `env_release_map` + the deployment enum). Source of truth for **which env
  runs which release**. Its `version_matrix` is **slimmed**: the edxapp + theme build-param
  records (`OpenEdxApplicationVersion` for `edxapp`/`theme`) are removed and delegated to Lehrer;
  it references Lehrer cells purely by `(release, deployment)` coordinate. MFE/codejail/notes/xqueue
  records stay in `version_matrix` until later iterations delegate them too.

**How the deployment × release mapping is managed under this split:**

1. The Concourse **generator keeps fanning out from `env_release_map`** — nothing about "which env
   runs which release" moves. Build jobs and deploy chains are still enumerated there.
2. Each build job calls `dagger call platform build-platform --build-manifest
   <lehrer>/deployments/mit-ol/build_manifest.yaml --release-name R --deployment-name D`; **Lehrer
   resolves every build param from the manifest at build time.** ol-infra no longer passes
   `--platform-branch/--translations-repo/--packages-to-remove/--extra-*` (they come from the cell).
3. Lehrer exposes a tiny typed **consumption API** — `lehrer.core.build_manifest.load_manifest(path)
   -> BuildManifest` (already the model) plus a `lehrer build cells [--manifest PATH]` CLI that
   prints the `(release, deployment)` cells. ol-infra's generator **consumes** this to assert
   `{topology coordinates} ⊆ {manifest cells}` at generation time — one authoritative cross-repo
   check that fails `fly set-pipeline` on drift, instead of duplicating the cell list. (The manifest
   may legitimately contain **more** cells than any env references — e.g. `generic`, or a
   not-yet-wired release — that is fine; only the reverse is an error.)

Image tag (`{release}-{deployment}`) and `OPENEDX_RELEASE` semantics are unchanged. PR 2 (ol-infra
cutover) is exactly: slim `version_matrix` (drop edxapp/theme build params), switch the generator's
`build-platform` invocation to `--build-manifest`, and add the manifest-consumption consistency
check.

## Open decisions (recommendations noted; confirm before PR 1)

1. **`generic` `settings_namespace`** — `production` (build_platform default + `docs/creating-a-deployment.md:291`)
   vs `generic` (`local-dev/tilt-settings.yaml`). *Recommend `production`*; reconcile the Tiltfile.
2. **Commented-out OTel packages** (`# opentelemetry-distro`, …) — drop (behavior-neutral) vs keep
   in an optional per-cell `notes` field. *Recommend drop.*
3. **`node_version`** — pin a concrete `24.x.y` (Renovate-managed) vs store `"24"` and resolve
   latest. *Recommend concrete pin.*
4. **ol-infra cutover owner/timing** — who lands the Concourse `--build-manifest` switch (PR 2)
   between PR 1 and PR 3.
5. **Project home** — track under the current CI-verification project as its foundation, or fold
   into the **"feature manifest layer"** project (overlapping). *Recommend: foundation task under
   the CI project, cross-linked to the feature-manifest project.*
6. **Concourse ownership boundary (§8)** — *Decided:* ol-infra keeps the deployment×env×release
   topology (`env_release_map`) and **consumes** Lehrer's manifests; Lehrer owns build definitions
   only (no env-stage concept in the schema); `version_matrix` edxapp/theme build params are
   delegated to Lehrer and a manifest-consumption consistency check guards coordinate drift.

---

## Verification

- `uv run pytest tests/core/test_build_manifest.py -v` — faithfulness (render↔`.txt`) + matrix +
  schema round-trip all green.
- `uv run pre-commit run build-manifest-schema --all-files` — no schema drift.
- `uv run python -c "from lehrer.core.build_manifest import BuildManifest; import yaml; BuildManifest.model_validate(yaml.safe_load(open('deployments/mit-ol/build_manifest.yaml')))"` — both manifests validate.
- Local dagger smoke (needs engine + network): `lehrer build platform --cell mit-ol/master/mitxonline export --path /tmp/img.tar` resolves the cell and builds — diff the materialized requirements against the old `.txt` to confirm identical install sets.
- Renovate dry-run (or inspect the next dependency-dashboard) confirms the custom manager detects
  `==` pins in the manifest and that `setuptools`/`pip`/`wheel` are not proposed for bump.
