# Implementation: CI Verification Pipeline (Plugin × Platform Compatibility)

## Context

Lehrer has zero build/test CI today. The only PR gate is pre-commit.ci running lint hooks
(and even there, `build-config-schema` is explicitly skipped — see `ci: skip:` in
`.pre-commit-config.yaml` — because it needs `uv run` inside a real environment that
pre-commit.ci does not provide). There are no unit tests. `mypy` explicitly excludes
`src/lehrer/` (see `[tool.mypy].exclude` in `pyproject.toml`) as well as `deployments/`
(the latter exclusion is correct — those files import Django/`openedx.*` that only exist
inside the edx-platform container — but `src/lehrer/` has no such excuse; it is pure
generic Python with no runtime coupling to edx-platform).

The consequence: a Renovate plugin-version bump to `deployments/*/pip_package_lists` merges
on lint-only green, and incompatibility with the pinned edx-platform release surfaces only
when the external `ol-infrastructure` Concourse pipeline builds an image — often days later,
and at that point it blocks a release rather than a PR.

This plan builds a layered verification pyramid, cheapest/fastest checks first:

1. **Fast checks** — pytest unit tests + mypy over `src/lehrer/`, and promoting two
   pre-commit hooks (`build-config-schema`, `lehrer-core-boundary`) from
   lint-only/skipped to actual enforced CI.
2. **Settings boot self-test** — the `AqueductSettings` instantiation check that already
   exists inside `regenerate_aqueduct_settings` (`src/lehrer/core/platform.py:1408-1423`)
   but only runs when a developer manually regenerates models — extracted into a
   standalone, CI-triggered check.
3. **Plugin-compat matrix** — on changes to `deployments/*/pip_package_lists` or
   `pip_package_overrides`, resolve + install the affected (release × deployment) cells
   and verify they actually import and boot against the matching edx-platform branch.
4. **Scheduled canary** — a full `dagger call platform build-platform` for
   master × mitxonline on a schedule, to catch upstream edx-platform drift that no PI in
   this repo would otherwise trigger.

A prerequisite chore threads through layers 1 and 3: today `deployments/mit-ol/pip_package_lists`
mixes pinned and floating plugin versions on the `master` lists (`ol-openedx-checkout-external`,
`ol-openedx-logging`, `ol-openedx-chat`, `ol-openedx-sentry`, `openedx-scorm-xblock` all float;
everything else is pinned). A floating plugin bumps silently at build time with no PR and no
CI signal — pinning them is what lets Renovate (already configured to watch
`pip_package_lists/**` per `renovate.json`) drive every future bump through the matrix in
Layer 3.

## Prerequisites

- `uv` available locally and in CI (`astral-sh/setup-uv` GitHub Action)
- Existing `.pre-commit-config.yaml` hooks (`build-config-schema`, `lehrer-core-boundary`)
  continue to work standalone via `pre-commit run <hook-id> --all-files`
- Dagger CLI available in CI runners for Layers 2–4 (`dagger/dagger-for-github` Action, or
  direct `curl | sh` install pinned to the same version the repo's `dagger.json` expects)
- A GitHub Actions secret for whatever channel the canary failure notification uses
  (Slack webhook URL, or rely on `gh issue create` with the default `GITHUB_TOKEN`)

## Tasks

---

### Task 1 — Pin floating `ol-openedx-*` plugin versions

**Files:** `deployments/mit-ol/pip_package_lists/{master,ulmo,verawood}/*.txt`

Audit every `pip_package_lists` and `pip_package_overrides` file across all three release
lines (`master`, `ulmo`, `verawood`) and both deployments (`generic`, `mit-ol`). For each
unpinned entry — currently, on the `master` lists:

- `ol-openedx-checkout-external`
- `ol-openedx-logging`
- `ol-openedx-chat` (and `ol-openedx-chat-xblock`, same plugin family)
- `ol-openedx-sentry`
- `openedx-scorm-xblock`

determine the currently-resolved version (`uv pip install` into a scratch venv against the
matching edx-platform branch and read `uv pip freeze`, or check the plugin's PyPI release
history against when the line was last touched) and pin it with `==`.

Reconcile cross-release drift while here: `ulmo` already pins `ol-openedx-logging==0.3.5`
while `master` leaves it unpinned — after this task every release line should show its
actual intentional version, not an accidental side effect of whichever version happened to
resolve on a given build day.

Do not touch already-pinned entries (`canvas`, `rapid-response`, `django-aqueduct`, etc.) —
those are already Renovate-managed per the recent bump history (`django-aqueduct` v0.6.0,
`ol-openedx-canvas-integration` v0.8.0/0.8.1, `rapid-response-reports` v0.5.1 — see git log).

Verify: `git grep -n '^ol-openedx-\|^openedx-scorm-xblock' deployments/*/pip_package_lists/*/*.txt`
shows every line ending in `==<version>` (comments-only or blank lines aside).

---

### Task 2 — Bootstrap fast-checks CI: pytest, mypy, promoted pre-commit hooks

**Files:** `pyproject.toml`, `tests/`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`

**2a. Test scaffolding.** Add `pytest` to the `dev` dependency group in `pyproject.toml`:

```toml
[dependency-groups]
dev = ["pre-commit>=4.5.1", "pytest>=8"]
```

Create `tests/` mirroring `src/lehrer/` package layout:

- `tests/core/test_mfe_config.py` — `BuildConfig`/`MfeBuildConfig`/`SlotFileByRelease`:
  - `SlotFileByRelease.resolve()` picks the exact-release match over `default`
  - falls back to `default` when the release isn't in `by_release`
  - raises when neither the release nor `default` is present
  - `_relative_mfe_path` (used via the `dest` validator) rejects absolute paths and `../`
    escapes, accepts plain relative paths
  - `BuildConfig.mfe()` returns an empty `MfeBuildConfig` default for an unconfigured MFE
    name, and is case-insensitive (lowercases the lookup)
  - `MfeBuildConfig.resolve_extra_slot_files()` mixes plain strings and `SlotFileByRelease`
    entries correctly
  - `json_schema()` / `BuildConfig.model_json_schema()` round-trips without raising, and its
    output stays consistent with the committed `build_config.schema.json` (a regression
    guard distinct from the pre-commit hook in Task 2c, since this runs the same
    generator via the test suite rather than shell)

- `tests/core/test_mfe.py` — `_safe_mfe_path` (`src/lehrer/core/mfe.py:16`): same class of
  traversal-guard cases as `_relative_mfe_path` above, since it's the sibling guard used at
  `extra_slot_files` / `styles_file` call sites (lines 202, 207) — reject absolute paths and
  `../` escapes with a clear `field=` name in the error, accept relative paths unchanged.

- `tests/cli/test_local_dev.py` — `_cluster_state` (`src/lehrer/cli/local_dev.py:69`):
  parametrize over the k3d/kubectl states it distinguishes (cluster absent, cluster present
  but context not current, cluster present and active) by mocking the underlying `_proc.run`
  / subprocess calls — do not require a real k3d cluster in CI. `_preflight_host_ports`
  (line 123): verify it raises/reports on a port already bound (bind a throwaway socket in
  the test) and passes cleanly when the required ports are free.

- `tests/cli/test_paths.py` — `repo_root()` / `RepoNotFoundError`: exercise the
  `LEHRER_REPO_ROOT` override, the upward-search-from-cwd success path (via `tmp_path` with
  a fake `local-dev/k3d-config.yaml` marker), and the failure path when no marker exists in
  any parent directory. Use `monkeypatch` for `os.environ` and `Path.cwd()`/`__file__`
  resolution — `repo_root()` is `@cache`d, so tests must either clear the cache
  (`repo_root.cache_clear()`) between cases or isolate via subprocess for the environment
  override case.

All of the above are pure-Python, no Dagger/Django/network required — they run in
milliseconds and belong in Layer 1.

**2b. mypy over `src/lehrer/`.** Remove `src/lehrer/` from `[tool.mypy].exclude` in
`pyproject.toml` (keep the `deployments/` exclusion — that one is correct, see the Context
section). Run `uv run mypy --config-file=pyproject.toml src/lehrer` locally and fix every
finding — expect issues mainly in `cli/` (subprocess/Popen return types) and possibly
`core/platform.py`/`core/mfe.py`'s Dagger `@function`-decorated methods, since Dagger's
codegen types may need `# type: ignore[...]` in specific narrow spots rather than a blanket
exclude. Do not silence with a blanket `# type: ignore` file header — same standard as any
other first-party module in this org (see `[[project.django-aqueduct-ownership]]` memory:
we hold first-party code to full type-checking, not exclusion).

**2c. Promote skipped/local hooks into CI.** `build-config-schema` is listed under
`ci: skip:` in `.pre-commit-config.yaml` specifically because it shells out to
`uv run python -c ...` — pre-commit.ci's sandboxed environment doesn't have the repo's own
venv. `lehrer-core-boundary` is a `pygrep` hook and *does* run on pre-commit.ci today, but
promoting it into the same explicit CI job as `build-config-schema` gives a clearer signal
(a failed schema regen or an OL-string leak into `core/`/`infra/` shows up as a named CI
check, not buried in a pre-commit.ci comment) and guarantees it also runs on forks/local
runs where pre-commit.ci doesn't apply. In the new workflow (below), run:

```yaml
- run: uv run pre-commit run build-config-schema --all-files
- run: uv run pre-commit run lehrer-core-boundary --all-files
```

after `uv sync`, so both hooks execute with the real project environment. Once this job
exists, drop `build-config-schema` from the `ci: skip:` list in `.pre-commit-config.yaml`
only if pre-commit.ci's own sandbox turns out to be sufficient after testing — if not,
leave the skip in place and rely on the new GH Actions job as the sole enforcement point
for that hook (do not require both to pass identically; one authoritative CI signal is
enough). Also delete the stale exclude entries pre-commit.ci and mypy inherited when
`.pre-commit-config.yaml` was copied from `ol-infrastructure` (any `ol_infrastructure/`,
`charts/`, `sdk/`, `poetry.lock` path references that don't exist in this repo) so the
config only mentions paths that are real.

**2d. GitHub Actions workflow.** Create `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  fast-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.13"
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy --config-file=pyproject.toml src/lehrer
      - run: uv run pytest tests/ -v
      - run: uv run pre-commit run build-config-schema --all-files
      - run: uv run pre-commit run lehrer-core-boundary --all-files
```

Verify: open a throwaway PR that breaks each check individually (a failing test, a mypy
error, a `mitxonline` string added under `src/lehrer/core/`) and confirm the workflow fails
on the right step with a legible message; then confirm a clean PR passes.

---

### Task 3 — Wire the aqueduct settings boot self-test into CI and `build_platform`

**Files:** `src/lehrer/core/platform.py`, `.github/workflows/ci.yml`

The only settings-correctness check in the repo today is the boot self-test embedded inside
`regenerate_aqueduct_settings` (`platform.py:1408-1423`): it force-imports
`lms.envs.models.aqueduct` / `cms.envs.models.aqueduct`, instantiates `AqueductSettings()`,
and asserts `INSTALLED_APPS` is non-empty. It only runs when a developer manually invokes
`dagger call platform regenerate-aqueduct-settings` — never automatically.

**3a. Extract a standalone Dagger function.** Add `verify_settings` (or similar) to
`OpenedxPlatform` in `platform.py` that takes the same container-building steps up through
model generation and runs *only* the self-test block (lines 1408–1423), returning
success/failure rather than the generated files. This lets it be called independently of a
full model regeneration.

**3b. PR-triggered check.** Add a job to `ci.yml` (or a separate workflow, since it needs
Dagger + a real edx-platform checkout and so is heavier than Layer 1) that runs
`dagger call platform verify-settings ...` whenever `deployments/*/settings/**` or
`src/lehrer/settings/**` changes — use `dorny/paths-filter` or the workflow's own
`on.pull_request.paths` trigger to scope it.

**3c. Post-build verification stage in `build_platform`.** Add an opt-out stage (default-on,
disable via a function parameter for operators who want faster non-gated builds) to
`build_platform` that runs `manage.py lms check` and `manage.py cms check` — and optionally
`manage.py lms migrate --plan` — inside the already-built image, so a broken plugin or
settings regression fails the Dagger build itself rather than surfacing only at deployment.
This is the same principle as the existing self-test, extended from "does the settings
model instantiate" to "does the full Django app boot."

**3d. Stop swallowing translation failures silently.** `fetch_translations`
(`platform.py:679–762`) suffixes eleven `manage.py`/`atlas` invocations with `|| true`,
so `pull_plugin_translations`, `compile_plugin_translations`, `pull_xblock_translations`,
`compile_xblock_translations`, and `atlas pull` (×3, LMS+CMS) failures are invisible —
only the final `compilemessages`/`compilejsi18n` calls (which have no `|| true`) fail the
build. Change each of those calls to capture stdout/stderr and either: surface as a
GitHub Actions warning annotation when running in CI, or fail outright when a
`strict_translations: bool = False` parameter is set to `True`. Leave the default lenient
(operators without a translations repo configured should not be blocked), but give CI a way
to opt into strict mode so silent translation regressions don't ride along unnoticed.

Verify: run `verify_settings` against a settings change that intentionally breaks
`AqueductSettings` instantiation (e.g. a required field with no default) and confirm it
fails with the assertion message from the self-test, not a bare traceback.

---

### Task 4 — Plugin-compat matrix CI job

**Files:** `.github/workflows/plugin-compat.yml` (new), possibly a small script under
`bin/` or `src/lehrer/cli/` to enumerate affected cells

Trigger: `pull_request` with `paths: ["deployments/*/pip_package_lists/**", "deployments/*/pip_package_overrides/**"]`,
plus a weekly `schedule` cron for the full matrix (not just the diff-affected cells).

For each affected `(release_name, deployment_name)` cell — e.g. `master` × `mitxonline`,
`ulmo` × `mitxonline`, `verawood` × `mit-ol`/`generic`, however the actual cross-product of
`pip_package_lists/<release>/<deployment>.txt` resolves — the job should:

1. Check out the matching edx-platform branch (`master`, or
   `open-release/<release>.master` for named releases).
2. Install base `edx-platform` requirements + the lehrer package list + overrides with
   `uv`. Reuse the existing `install_deps` Dagger function (`platform.py:229`) rather than
   re-implementing pip resolution in shell — call it via
   `dagger call platform install-deps --release-name ... --deployment-name ...` so CI
   verifies the exact same resolution path production builds use, not a parallel one that
   can drift from it.
3. Run `uv pip check` inside that environment to catch resolver conflicts.
4. `python -c "import <pkg>"` for every `ol-openedx-*` / plugin package listed in that
   cell's `pip_package_lists`/`pip_package_overrides` files (parse the `.txt`, strip
   version pins and comments, derive each import name — most `ol-openedx-*` packages
   import as `ol_openedx_...` per PEP 503 name normalization; handle the few exceptions
   explicitly, e.g. `openedx-scorm-xblock` → `scorm`).
5. Run `manage.py lms check` with the deployment's aqueduct settings loaded.

**Scope control:** on PRs, run only the cells whose `pip_package_lists`/`pip_package_overrides`
files actually changed (diff the PR against `main` to determine affected release/deployment
pairs — a change to `deployments/mit-ol/pip_package_lists/master/mitxonline.txt` affects
only `master`×`mitxonline`, not every cell). On the weekly schedule, run the full matrix
across every `(release, deployment)` pair that exists, to catch drift even when no PR
touched that specific cell recently. Log which cells were skipped/run in the job summary —
no silent narrowing.

This task benefits from Task 1 being done first (pinned versions make the matrix
deterministic — an unpinned plugin resolving to a different version between the PR run and
a later merge would make this check flaky/non-reproducible), but is not strictly blocked on
it; it can be built and validated against the plugins that are already pinned while Task 1
proceeds in parallel.

Verify: submit a throwaway PR that bumps a plugin to a version with an import-time error
(or a syntax error stubbed into a local override) and confirm the matrix job fails on the
correct cell with a message identifying which package failed to import.

---

### Task 5 — Scheduled canary build (master × mitxonline)

**Files:** `.github/workflows/canary.yml` (new)

Add a `schedule`-triggered workflow (nightly, or 2–3×/week — nightly is simplest and Dagger
caching should keep runtime tolerable) that runs the *full*
`dagger call platform build-platform --deployment-name mitxonline --release-name master ...`
pipeline end-to-end, without publishing the resulting image anywhere. This is the only
layer that catches upstream edx-platform `master` commits breaking MIT OL's plugin pins or
settings *without* any change to this repo — everything in Tasks 1–4 is only triggered by a
change inside lehrer itself.

Use Dagger's caching (local cache volume persisted between runs via `actions/cache`, or
Dagger Cloud if the org has a plan for it) to keep nightly runtime reasonable — a from-empty
`build-platform` run is the most expensive operation in this repo.

On failure, notify via whichever channel is cheapest to stand up first — a Slack webhook
(`slackapi/slack-github-action`) if a webhook URL is already available as an org secret, else
fall back to `gh issue create --label ci-canary-failure` using the default `GITHUB_TOKEN` so
there's always a fallback with no new secret to provision. Include the failing step and a
link to the run in the notification body.

This is explicitly the top of the pyramid — the cheap layers (unit tests, boot self-test,
plugin matrix) gate PRs fast; the canary is allowed to be slow and catches what the fast
layers structurally cannot (drift with no lehrer-side change to trigger on).

Verify: manually trigger the workflow (`workflow_dispatch` as a secondary trigger is useful
for this) and confirm both the success path (green run, no notification) and, if feasible,
force a failure to confirm the notification fires with a legible message.

---

## Dependency notes

- Task 1 (pin plugin versions) is a prerequisite for Task 4 (matrix) being *meaningful* and
  reproducible, but not a hard blocker — Task 4's scaffolding can be built in parallel.
- Task 2 (fast checks) has no dependency on the others and should land first — it is the
  cheapest to build and gives the fastest signal.
- Task 3 (settings boot self-test) is independent of Tasks 1/4 — it verifies settings model
  correctness, not plugin resolution.
- Task 5 (canary) benefits from Tasks 3 and 4 existing first (so a canary failure can be
  triaged against "did the matrix already catch this on a PR" before assuming it's genuine
  upstream drift), but can be stood up independently since it exercises a full build, a
  strict superset of what the cheaper layers check.

## Out of scope

- Publishing canary-built images anywhere (this plan explicitly builds without publish).
- A full replacement of the external `ol-infrastructure` Concourse pipeline — that remains
  the actual deployment path; this plan only adds pre-merge and drift-detection signal
  inside the `lehrer` repo itself.
- Extending the matrix to release lines or deployments that don't yet have
  `pip_package_lists` files (e.g. a hypothetical new operator) — scope is the existing
  `generic` and `mit-ol` deployments across `master`/`ulmo`/`verawood`.
