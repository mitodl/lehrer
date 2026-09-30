"""Schema for a bootstrap spec: the objects a fresh Open edX install needs.

A bootstrap spec declares, as data, what has to exist in the LMS database
before the install is usable: users to log in as, OAuth2 applications for the
services that authenticate against the LMS (notes, Studio SSO, ...), and
waffle flags. :mod:`lehrer.bootstrap.__main__` applies one inside the platform
image; every step is idempotent, so applying the same spec twice changes
nothing the second time.

The same file drives local dev (the edxapp-provision Job), a deployed
environment's pre-deploy Job, and later an operator reconciling the same
fields from a CRD, so that none of them carries bootstrap logic of its own.

Secrets never appear in a spec. A field ending in ``_env`` names the
environment variable the value is read from at apply time, so a spec can live
in a ConfigMap or in git while the values come from a Secret.

This module is imported both by lehrer's own CLI and tests and, copied into
the platform image as ``lehrer_bootstrap``, by the runner. It may therefore
import only pydantic, PyYAML and the standard library.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

STEPS = ("users", "oauth_applications", "waffle_flags")
"""Step names in the order they run. OAuth applications are owned by a user,
so users come first."""


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

    users: list[User] = Field(default_factory=list)
    oauth_applications: list[OAuthApplication] = Field(default_factory=list)
    waffle_flags: list[WaffleFlag] = Field(default_factory=list)


def load(path: str | Path) -> BootstrapSpec:
    """Read and validate a bootstrap spec from a YAML file."""
    return BootstrapSpec.model_validate(yaml.safe_load(Path(path).read_text()) or {})


def from_env(name: str) -> str:
    """Read a value a spec references by environment variable name."""
    try:
        return os.environ[name]
    except KeyError:
        msg = f"the bootstrap spec reads {name} from the environment, which is unset"
        raise ValueError(msg) from None


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
