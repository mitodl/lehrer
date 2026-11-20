"""Schema for a bootstrap spec: the objects a fresh Open edX install needs.

A bootstrap spec declares, as data, what has to exist in the database before
the install is usable: the migrated schema, users to log in as, OAuth2
applications for the services that authenticate against the LMS (notes,
Studio SSO, ...), waffle flags, and optionally the demo course.
:mod:`lehrer.bootstrap.__main__` applies one inside the platform image; every
step is idempotent, so applying the same spec twice changes nothing the second
time.

When a step runs is the caller's decision, not the spec's: a caller passes
``--steps`` (e.g. migrate on every deploy, the demo course only when a
developer asks for it), so one spec serves all of them.

The same file drives local dev (the edxapp-migrate, edxapp-provision and
edxapp-demo-course Jobs), a deployed environment's pre-deploy Job, and later
an operator reconciling the same fields from a CRD, so that none of them
carries bootstrap logic of its own.

Secrets never appear in a spec. A field ending in ``_env`` names the
environment variable the value is read from at apply time, so a spec can live
in a ConfigMap or in git while the values come from a Secret.

This module is imported both by lehrer's own CLI and tests and, copied into
the platform image as ``lehrer_bootstrap``, by the runner. It may therefore
import only pydantic, PyYAML and the standard library.
"""

from __future__ import annotations

import os
import string
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STEPS = (
    "migrate",
    "users",
    "oauth_applications",
    "third_party_auth_providers",
    "service_access_tokens",
    "waffle_flags",
    "demo_course",
)
"""Step names in the order they run. Everything after migrate needs the schema,
and OAuth applications are owned by a user, so users come before them."""

PLACEHOLDER_SETTINGS = frozenset(
    {"LMS_ROOT_URL", "CMS_ROOT_URL", "EDXNOTES_CLIENT_NAME"}
)
"""Django settings a spec may reference as ``{SETTING}``.

An allowlist rather than any identifier: the runner prints each resolved OAuth
application name in its report and stores resolved redirect URIs where any
Django admin can read them, so ``{SECRET_KEY}`` would publish the secret.
Widening this is a reviewed change to lehrer, not something a spec can do.
"""


def _check_placeholders(template: str) -> str:
    """Return ``template`` if every ``{...}`` in it is an allowlisted bare name.

    ``str.format_map`` would also honour attribute and index lookups
    (``{X.y}``, ``{X[0]}``), conversions and format specs, none of which a spec
    needs and each of which widens what a placeholder can reach.
    """
    try:
        fields = list(string.Formatter().parse(template))
    except ValueError as error:
        msg = f"{template!r} is not a valid template: {error}"
        raise ValueError(msg) from None
    for _, name, spec, conversion in fields:
        if name is None:
            continue
        if spec or conversion or name not in PLACEHOLDER_SETTINGS:
            msg = (
                f"{template!r} references {{{name}}}; a spec may only reference "
                f"one of {', '.join(sorted(PLACEHOLDER_SETTINGS))} as a bare "
                "{SETTING}"
            )
            raise ValueError(msg)
    return template


class Migration(BaseModel):
    """One ``manage.py <service> migrate`` run.

    Each runs in a subprocess with that service's settings, since the runner
    itself is set up for one settings module and the CMS migrates under its
    own.
    """

    model_config = ConfigDict(extra="forbid")

    service: Literal["lms", "cms"]
    app_label: str | None = Field(
        default=None, description="Migrate only this app. Omitted, migrates all."
    )
    database: str = Field(
        default="default",
        description=(
            "The DATABASES alias to migrate. migrate never touches another alias "
            "on its own, so an app routed to a separate database (e.g. "
            "coursewarehistoryextended on student_module_history) needs its own "
            "entry."
        ),
    )
    fake: str | None = Field(
        default=None,
        description=(
            "Full name of one app_label migration (e.g. "
            "0006_mariadb_uuid_conversion) to record as applied without running "
            "it, after applying the migrations it depends on. For a migration "
            "that cannot run as written; once it is recorded the entry does "
            "nothing."
        ),
    )

    @model_validator(mode="after")
    def _fake_names_its_app(self) -> Migration:
        if self.fake and not self.app_label:
            msg = f"fake: {self.fake} needs the app_label it belongs to"
            raise ValueError(msg)
        return self


class DemoCourse(BaseModel):
    """The Open edX demo course, imported into the CMS modulestore.

    Re-importing overwrites the course in place.
    """

    model_config = ConfigDict(extra="forbid")

    repo: str = "https://github.com/openedx/openedx-demo-course"
    branch: str | None = Field(
        default=None,
        description=(
            "Branch to import. Omitted, the first of release/<line>, "
            "open-release/<line>.master and <line> that exists, where <line> is "
            "the platform's own RELEASE_LINE (e.g. verawood, master)."
        ),
    )


class User(BaseModel):
    """A user the install needs, e.g. a local-dev superuser or a service user.

    Applied as declared, including on an existing account: one the spec does
    not mark ``superuser`` or ``staff`` loses those flags, and every declared
    user is made active.
    """

    model_config = ConfigDict(extra="forbid")

    username: str
    email: str
    password_env: str | None = Field(
        default=None,
        description=(
            "Environment variable holding the password. Omitted, the password "
            "is left alone (a new user gets an unusable one), which suits a "
            "service user that only ever authenticates with OAuth2."
        ),
    )
    superuser: bool = False
    staff: bool = Field(
        default=False,
        description="Django is_staff. A superuser is always made staff as well.",
    )


class OAuthApplication(BaseModel):
    """A django-oauth-toolkit Application and its oauth_dispatch access record.

    Matched on ``client_id``, so an application created by hand in a deployed
    environment is adopted (and brought in line with the spec) rather than
    duplicated.

    ``name`` and each redirect URI may reference Django settings as
    ``{SETTING}``, e.g. ``{CMS_ROOT_URL}/complete/edx-oauth2/``, so one spec
    serves every environment whose settings differ.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    user: str = Field(description="Username of the owning user; must exist.")
    grant_type: Literal[
        "authorization-code", "implicit", "password", "client-credentials"
    ]
    client_id_env: str
    client_secret_env: str
    redirect_uris: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(
        default_factory=list,
        description=(
            "Scopes beyond the defaults the application may request, e.g. "
            "user_id for Studio SSO. Empty leaves the access record alone."
        ),
    )
    skip_authorization: bool = False
    public: bool = Field(
        default=False, description="Public client type; confidential otherwise."
    )

    @field_validator("name")
    @classmethod
    def _name_placeholders(cls, value: str) -> str:
        return _check_placeholders(value)

    @field_validator("redirect_uris")
    @classmethod
    def _redirect_uri_placeholders(cls, value: list[str]) -> list[str]:
        return [_check_placeholders(uri) for uri in value]


class ThirdPartyAuthProvider(BaseModel):
    """An ``OAuth2ProviderConfig``: an external IdP the LMS federates login to.

    ``THIRD_PARTY_AUTH_BACKENDS`` makes a backend *importable*; this row is what
    makes it *usable*. Without one, ``/auth/login/<backend>/`` 404s even though
    the backend class is installed and in ``AUTHENTICATION_BACKENDS``.

    The provider's endpoint URLs cannot come from Django settings:
    ``OAuth2ProviderConfig.get_setting`` serves ``KEY`` and ``SECRET`` from this
    row and every other name out of its ``other_settings`` JSON, so that JSON is
    the only channel for ``AUTHORIZATION_URL`` / ``ACCESS_TOKEN_URL`` /
    ``API_ROOT`` / ``DISCOVERY_URL``.

    Which IdP to federate to is a property of the surrounding deployment, not of
    this stack, so the JSON arrives by environment variable like the credentials
    do. **An entry whose referenced variables are unset or empty is skipped**,
    which is how a standalone install -- one with no upstream IdP in front of it
    -- declines the whole step without needing a different spec file.
    """

    model_config = ConfigDict(extra="forbid")

    backend_name: str = Field(
        description=(
            "social-core backend name, e.g. ol-oauth2. Must appear in "
            "THIRD_PARTY_AUTH_BACKENDS or the provider is never registered."
        )
    )
    slug: str
    name: str = Field(description="Label shown on the LMS login page.")
    client_id_env: str
    client_secret_env: str
    other_settings_env: str = Field(
        description=(
            "Environment variable holding the other_settings JSON object. The "
            "endpoint URLs live here because Django settings cannot reach them."
        )
    )
    enabled: bool = True
    visible: bool = True
    skip_hinted_login_dialog: bool = True
    skip_registration_form: bool = Field(
        default=True,
        description=(
            "Provision the account straight from the IdP's user data instead of "
            "prompting. Required when the IdP, not the LMS, owns registration."
        ),
    )
    skip_email_verification: bool = True
    sync_learner_profile_data: bool = False
    optional: bool = Field(
        default=True,
        description=(
            "Skip the entry when its variables are unset or empty. False makes "
            "that an error, which is what a feature's entries need: a skipped "
            "provider is a feature that silently is not there."
        ),
    )


class ServiceAccessToken(BaseModel):
    """A long-lived OAuth2 bearer token for an upstream service integration.

    Some integrations do not perform an OAuth2 exchange at all: they are handed
    one opaque token and send it as ``Authorization: Bearer`` forever. MITx
    Online's ``OPENEDX_SERVICE_WORKER_API_TOKEN`` is the example -- it is read
    straight out of settings and used to enrol learners through the LMS API, so
    without a matching ``AccessToken`` row here every enrolment silently fails
    and the upstream records ``edx_enrolled=False``.

    Self-contained on purpose: the entry owns its service account and its
    application as well as the token, because all three exist only to serve one
    integration and should appear and disappear together. **Skipped entirely
    when ``token_env`` is unset or empty**, so an install with no such
    integration does not grow an unused staff account.

    The account gets an unusable password: it authenticates only by this token.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(description="Service account to create and own the token.")
    email: str
    token_env: str = Field(
        description=(
            "Environment variable holding the bearer token. The upstream must "
            "be configured with the identical value."
        )
    )
    application_name: str = Field(
        description="Name for the owning OAuth2 application.",
    )
    staff: bool = Field(
        default=True,
        description=(
            "Django is_staff. Enrolling a *different* user through the LMS "
            "enrollment API requires it, so a service worker that provisions "
            "enrolments needs it set."
        ),
    )
    scopes: list[str] = Field(
        default_factory=lambda: ["read", "write", "email", "profile", "user_id"]
    )
    expires_in_days: int = Field(
        default=3650,
        description=(
            "Lifetime from apply time. Long by default: this stands in for a "
            "credential a deployed environment would hold in a secret store."
        ),
    )
    optional: bool = Field(
        default=True,
        description=(
            "Skip the entry when token_env is unset or empty. False makes that "
            "an error."
        ),
    )


class WaffleFlag(BaseModel):
    """A waffle flag, applied through django-waffle's ``waffle_flag`` command.

    The command can only switch the per-group settings on, so ``superusers``,
    ``staff`` and ``authenticated`` being false means "leave as is", not
    "turn off". ``everyone`` is the one tri-state: true activates the flag for
    all users, false deactivates it, unset leaves it alone.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    everyone: bool | None = None
    superusers: bool = False
    staff: bool = False
    authenticated: bool = False
    percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Whole percent; waffle_flag's --percent only takes an int.",
    )
    rollout: bool = False
    testing: bool = False
    create: bool = True

    def argv(self) -> list[str]:
        """The ``waffle_flag`` command-line arguments for this flag."""
        args = [self.name]
        if self.everyone is True:
            args.append("--everyone")
        elif self.everyone is False:
            args.append("--deactivate")
        args += [
            f"--{option}"
            for option in ("superusers", "staff", "authenticated", "rollout", "testing")
            if getattr(self, option)
        ]
        if self.percent is not None:
            args += ["--percent", str(self.percent)]
        if self.create:
            args.append("--create")
        return args

    @classmethod
    def from_argv(cls, argv: list[str]) -> WaffleFlag:
        """Parse a ``[name, *options]`` list in the set_waffle_flags.py format.

        For converting existing ``waffles:`` lists. Raises ``ValueError`` on an
        option this model does not express, rather than dropping it.
        """
        name, *options = argv
        fields: dict[str, Any] = {"name": name, "create": False}
        remaining = iter(options)
        for option in remaining:
            match option:
                case "--everyone":
                    fields["everyone"] = True
                case "--deactivate":
                    fields["everyone"] = False
                case "--percent" | "-p":
                    fields["percent"] = int(next(remaining))
                case (
                    "--superusers"
                    | "--staff"
                    | "--authenticated"
                    | "--rollout"
                    | "--testing"
                    | "--create"
                ):
                    fields[option.removeprefix("--")] = True
                case _:
                    msg = f"waffle flag {name!r}: unsupported option {option!r}"
                    raise ValueError(msg)
        return cls(**fields)


class BootstrapSpec(BaseModel):
    """Everything a fresh install needs in its database, by step."""

    model_config = ConfigDict(extra="forbid")

    migrate: list[Migration] = Field(default_factory=list)
    users: list[User] = Field(default_factory=list)
    oauth_applications: list[OAuthApplication] = Field(default_factory=list)
    third_party_auth_providers: list[ThirdPartyAuthProvider] = Field(
        default_factory=list
    )
    service_access_tokens: list[ServiceAccessToken] = Field(default_factory=list)
    waffle_flags: list[WaffleFlag] = Field(default_factory=list)
    demo_course: DemoCourse | None = None

    @model_validator(mode="after")
    def _identities_are_unique(self) -> BootstrapSpec:
        """Collapse repeated entries and refuse ones that disagree.

        Each list is applied by upserting on one key, so two entries sharing
        it would have the second silently rewrite the first. Identical
        repeats are harmless and are collapsed, which is what lets the same
        flag arrive from two features (or a feature and a base spec) at all.
        Run on every spec, so a hand-written file and a :func:`merge` result
        fail the same way.
        """
        for field, key in IDENTITIES.items():
            setattr(self, field, _collapse(field, getattr(self, field), key))
        self.migrate = _collapse(
            "migrate", self.migrate, lambda m: tuple(m.model_dump().items())
        )

        _unique(
            "oauth_applications.client_id_env",
            [(a.client_id_env, a.name) for a in self.oauth_applications],
        )
        app_names = {a.name for a in self.oauth_applications}
        user_names = {u.username for u in self.users}
        _unique(
            "service_access_tokens.application_name",
            [(t.application_name, t.username) for t in self.service_access_tokens],
        )
        for token in self.service_access_tokens:
            # Each of these is upserted by name by another step, so the
            # second write would reassign what the first created.
            if token.application_name in app_names:
                msg = (
                    f"service_access_tokens {token.username!r} names application "
                    f"{token.application_name!r}, which oauth_applications also "
                    "declares"
                )
                raise ValueError(msg)
            if token.username in user_names:
                msg = (
                    f"service_access_tokens {token.username!r} is also declared "
                    "under users; the token step owns its account"
                )
                raise ValueError(msg)
        return self


IDENTITIES: dict[str, Callable[[Any], object]] = {
    "users": lambda e: e.username,
    "oauth_applications": lambda e: e.name,
    "third_party_auth_providers": lambda e: e.backend_name,
    "service_access_tokens": lambda e: e.username,
    "waffle_flags": lambda e: e.name,
}
"""The key each list is upserted on, and so compared on when specs combine.

``third_party_auth_providers`` is keyed on ``backend_name``, not ``slug``: the
runner looks up the newest row for ``(SITE_ID, backend_name)``.
"""


# A TypeVar rather than PEP 695 `def _collapse[T: ...]`: this package is
# compiled into every platform image, and ulmo's runs Python 3.11.
_Entry = TypeVar("_Entry", bound=BaseModel)


def _collapse(
    field: str, entries: list[_Entry], key: Callable[[_Entry], object]
) -> list[_Entry]:
    kept: dict[object, _Entry] = {}
    for entry in entries:
        identity = key(entry)
        if identity not in kept:
            kept[identity] = entry
        elif kept[identity].model_dump() != entry.model_dump():
            msg = (
                f"{field}: two entries for {identity!r} differ: "
                f"{kept[identity].model_dump(exclude_defaults=True)} vs "
                f"{entry.model_dump(exclude_defaults=True)}"
            )
            raise ValueError(msg)
    return list(kept.values())


def _unique(what: str, pairs: list[tuple[str, str]]) -> None:
    """Refuse two different owners sharing one value of ``what``."""
    owners: dict[str, str] = {}
    for value, owner in pairs:
        if owners.setdefault(value, owner) != owner:
            msg = f"{what} {value!r} is used by both {owners[value]!r} and {owner!r}"
            raise ValueError(msg)


def merge(*specs: BootstrapSpec) -> BootstrapSpec:
    """Combine specs in order into one, refusing any conflict.

    Lists concatenate and then go through the same identity checks as a
    single spec. ``demo_course`` is one value, so two specs that set it must
    agree. The runner and ``lehrer features compile`` both call this, so the
    two cannot disagree about what a set of specs means.
    """
    combined: dict[str, Any] = {}
    for spec in specs:
        for field in BootstrapSpec.model_fields:
            value = getattr(spec, field)
            if field == "demo_course":
                if value is None:
                    continue
                if combined.get(field, value) != value:
                    msg = (
                        f"demo_course differs between specs: "
                        f"{combined[field].model_dump()} vs {value.model_dump()}"
                    )
                    raise ValueError(msg)
                combined[field] = value
            else:
                combined.setdefault(field, []).extend(value)
    return BootstrapSpec.model_validate(
        {
            field: [e.model_dump() for e in value] if isinstance(value, list) else value
            for field, value in combined.items()
        }
    )


FRAGMENT_FIELDS = frozenset(
    {
        "users",
        "oauth_applications",
        "third_party_auth_providers",
        "service_access_tokens",
        "waffle_flags",
    }
)
"""What a feature's fragment may declare. Migrations and the demo course are
the operator's to schedule, not something one feature can add."""


def check_fragment(spec: BootstrapSpec) -> None:
    """Refuse what only an operator's base spec may declare.

    A superuser or a password is the operator's decision. Other privilege (a
    staff service account, a long-lived token) stays allowed and is listed by
    ``lehrer features explain``.
    """
    extra = [
        field
        for field in BootstrapSpec.model_fields
        if field not in FRAGMENT_FIELDS and getattr(spec, field)
    ]
    if extra:
        msg = f"a feature fragment may not declare {', '.join(extra)}"
        raise ValueError(msg)
    for user in spec.users:
        if user.superuser or user.password_env:
            msg = (
                f"users {user.username!r}: superuser and password_env belong to "
                "the operator's base spec, not a feature fragment"
            )
            raise ValueError(msg)


def load(path: str | Path) -> BootstrapSpec:
    """Read and validate a bootstrap spec from a YAML file."""
    return BootstrapSpec.model_validate(yaml.safe_load(Path(path).read_text()) or {})


def load_all(paths: list[str] | list[Path]) -> BootstrapSpec:
    """Read several specs and :func:`merge` them in the order given."""
    return merge(*(load(path) for path in paths))


def from_env(name: str) -> str:
    """Read a value a spec references by environment variable name."""
    try:
        return os.environ[name]
    except KeyError:
        msg = f"the bootstrap spec reads {name} from the environment, which is unset"
        raise ValueError(msg) from None


def from_env_optional(name: str) -> str | None:
    """Read an optional value, treating unset and empty as equally absent.

    Empty counts as absent because the local-dev Secret is built by resolving
    every declared key, so a key meant to be supplied only by a composing
    caller still arrives -- as "". Distinguishing the two here would make an
    entry that is meant to opt out fail instead.
    """
    value = os.environ.get(name)
    return value or None


class _SettingsLookup(Mapping[str, Any]):
    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self._settings, key)
        except AttributeError:
            msg = f"the bootstrap spec references setting {{{key}}}, which is not set"
            raise ValueError(msg) from None

    def __iter__(self):  # pragma: no cover - format_map never iterates
        raise NotImplementedError

    def __len__(self) -> int:  # pragma: no cover - format_map never sizes
        raise NotImplementedError


def resolve(template: str, settings: Any) -> str:
    """Substitute ``{SETTING}`` references with values from Django settings."""
    return template.format_map(_SettingsLookup(settings))


def json_schema() -> dict:
    """Return the JSON Schema for a bootstrap spec."""
    return BootstrapSpec.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(json_schema(), indent=2))  # noqa: T201
