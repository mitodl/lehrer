# Follow-up: the generated aqueduct settings model is incomplete

**Status:** open — blocks running any lehrer-built deployment as a live service.
**Found:** 2026-06-15, while bringing the `generic` deployment up end-to-end in
the local k3d dev environment (`lehrer dev start`).

## TL;DR

The `generic` deployment now **builds, boots, and connects to MySQL**, but the
LMS/CMS are **not functional**: the generated aqueduct settings model
(`deployments/generic/settings/models/`) is missing `INSTALLED_APPS` entirely,
so at runtime `lms.envs.aqueduct` resolves `INSTALLED_APPS` to Django's empty
default. With no apps installed, nothing works:

- `manage.py … migrate` reports `Apply all migrations: (none)` and never creates
  the schema;
- importing the URLconf raises `AUTH_USER_MODEL refers to model 'auth.User' that
  has not been installed`;
- `/heartbeat` returns HTTP 500, so the readiness/liveness probes fail and the
  pods CrashLoop.

This is a **code-generation gap** in `OpenedxPlatform.regenerate_aqueduct_settings`
(`src/lehrer/core/platform.py`), not a config problem.

## Evidence

From inside a running LMS pod (`DJANGO_SETTINGS_MODULE=lms.envs.aqueduct`):

```text
INSTALLED_APPS type: list count: 0
has django.contrib.auth: False
loaded app configs: 0

# DB connectivity is fine (the _derive_databases fix works):
DB OK host= mysql.openedx.svc.cluster.local
current db: ('edxapp',)
table count: 0           # empty schema — migrate found no apps to migrate
```

`INSTALLED_APPS` is absent from `deployments/generic/settings/models/base.py`
(the field list jumps from `ID_VERIFICATION_SUPPORT_LINK` straight to
`INTEGRATED_CHANNELS_API_CHUNK_TRANSMISSION_LIMIT`) and the LMS/CMS models add
nothing.

## Root cause

`regenerate_aqueduct_settings` snapshots `lms/cms.envs.common` into a Pydantic
model. The aqueduct adapter (`django_aqueduct.configure_django_settings`)
**replaces** the Django settings with the model's values — confirmed by the
existing `_derive_xblock_mixins` validator, whose docstring says it restores
`XBLOCK_MIXINS` from `common.py` "when no override is present." So **any setting
the generator skips or can't serialise is lost** unless a validator restores it.

The generator handles "opaque" (non-JSON-serialisable) values inconsistently:

| Setting | Generator output | Result |
|---|---|---|
| `XBLOCK_MIXINS` | field + `_derive_xblock_mixins` restore validator | works |
| `YOUTUBE`, `*_PATTERN`, … (8 fields) | `<type> \| None`, `default=None` | validate OK (None passes) |
| `JWT_AUTH` | `dict[str, Any]` (non-optional!), `default=None` | **boot crash** — worked around in commit `fcc5aec` |
| `INSTALLED_APPS`, and likely `MIDDLEWARE`, `TEMPLATES`, `AUTHENTICATION_BACKENDS`, `DATABASE_ROUTERS`, `STATICFILES_FINDERS`, … | **omitted entirely** | **non-functional** — no restore, no field |

So there are (at least) three generator defects:

1. **Opaque dict fields aren't consistently made `Optional`** — `JWT_AUTH` got
   `dict[str, Any]` instead of `dict[str, Any] | None` (the other 8 opaque
   fields were correct).
2. **Complex settings that hold class/callable references are dropped** rather
   than restored. `INSTALLED_APPS` is the fatal one; audit `MIDDLEWARE`,
   `TEMPLATES`, `AUTHENTICATION_BACKENDS`, `DATABASE_ROUTERS`, `WSGI_APPLICATION`,
   `STATICFILES_*`, `DEFAULT_*`, etc.
3. **No boot validation** — the generated model was never asserted to import and
   `django.setup()` cleanly, which would have caught (1) and (2) immediately.

## Scope note: django-aqueduct is ours

`django-aqueduct` is a first-party MIT OL project, **fully under our control and
in-scope for modification**. The fix is not limited to this repo's generator or
the generated models — we can (and probably should) change `django-aqueduct`
itself: the adapter's apply/replace semantics, how it treats settings it doesn't
model, opaque-value handling, and the overall ergonomics of the snapshot →
model → runtime flow. Prefer fixing the framework once over papering over its
gaps in every generated deployment model.

## Recommended fix (pick one direction)

**A. Fix `django-aqueduct` itself (preferred — addresses the root + ergonomics).**
The core defect is that the adapter *replaces* Django settings and silently
drops anything not modelled, so a generation miss (e.g. `INSTALLED_APPS`) is
fatal and invisible. Better framework behaviour to consider:

- **Don't drop unmodelled settings** — overlay the model onto the existing
  `from …common import *` values instead of replacing them, so a missing field
  degrades to "uses common.py's value" rather than "empty".
- **Make opaque/non-serialisable settings first-class** — a consistent
  represent-and-restore mechanism (the `_derive_xblock_mixins` idea generalised),
  rather than per-field special-casing that produced the `JWT_AUTH`/`INSTALLED_APPS`
  inconsistencies.
- **Generate a boot self-test** — emit/assert that a generated model imports and
  `django.setup()`s cleanly, so gaps fail at generation time, not at pod boot.

Then fix `regenerate_aqueduct_settings` in this repo to match, and regenerate.

**B. Fix only this repo's generator.** If a framework change is deferred, make
`regenerate_aqueduct_settings` emit restore validators (the `_derive_xblock_mixins`
pattern) for every setting it can't round-trip, plus the boot self-test above.

**C. Runtime restore validators (stopgap).** Hand-add `@model_validator`s to
`deployments/generic/settings/models/base.py` restoring `INSTALLED_APPS`,
`MIDDLEWARE`, `TEMPLATES`, `AUTHENTICATION_BACKENDS`, … from `common.py`. Slow to
discover the full list (one ~19-min image rebuild per missing setting) and must
be re-applied after every regeneration, so only a bridge to (A)/(B).

Either way, finish by re-running the local-dev bring-up to a Ready LMS pod.

## What is already in place (so the next person can pick up here)

All committed on `feat/local-dev-environment`:

- `_derive_databases` validator + `MYSQL_*`/`DB_PASSWORD` fields — DB wiring is
  **verified working** (`18c7b03`).
- `JWT_AUTH` made `| None` (`fcc5aec`) — unblocks settings *validation*; the
  generator should be fixed so this isn't reintroduced on regen.
- `ALLOWED_HOSTS` JSON-encoded in the platform ConfigMaps (`c955ec9`).
- `edxapp-migrate` Job (`manage.py {lms,cms} migrate --skip-checks`) wired so the
  platform services wait on it (`18c7b03`). It will work once `INSTALLED_APPS` is
  restored.
- Earlier build fixes (lxml reinstall, `setuptools<82`, `settings_namespace`
  default `generic`, CMS `LMS_ROOT_URL`) — see git log.

The local k3d cluster is left running with the partially-working deployment; run
`lehrer dev teardown` to reset.

## Repro / verification

```bash
lehrer dev setup && lehrer dev start            # build + deploy generic
# once the platform image is built and an lms pod is Running:
pod=$(kubectl -n openedx get pod -l app=lms -o jsonpath='{.items[-1:].metadata.name}')
kubectl -n openedx exec "$pod" -c lms -- python -c \
  'import os;os.environ["DJANGO_SETTINGS_MODULE"]="lms.envs.aqueduct";import django;django.setup();from django.conf import settings;print(len(settings.INSTALLED_APPS))'
# expect a few hundred once fixed; currently prints 0
```
