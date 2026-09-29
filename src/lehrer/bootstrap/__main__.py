"""Apply a bootstrap spec to this Open edX install.

Runs inside the platform image, where lehrer bakes this package in as
``lehrer_bootstrap``::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct \\
        python -m lehrer_bootstrap /path/to/bootstrap.yaml [--steps users,waffle_flags]

Every step converges the database on the spec, so re-running it is safe. Each
object applied prints one JSON line on stdout (``{"step", "target",
"result"}``, result one of created/updated), which is what a Job's caller, and
later an operator, reads to tell what changed. A failure raises and exits
non-zero after the lines for everything already applied.

argparse rather than cyclopts: the image has no cyclopts, and this must not
depend on anything the platform does not already install.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .spec import STEPS, BootstrapSpec, from_env, load, resolve


def _report(step: str, target: str, *, created: bool) -> None:
    result = "created" if created else "updated"
    print(json.dumps({"step": step, "target": target, "result": result}), flush=True)  # noqa: T201


def apply_users(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    from django.contrib.auth import get_user_model  # type: ignore[import-not-found]  # noqa: PLC0415

    from common.djangoapps.student.models import UserProfile  # type: ignore[import-not-found]  # noqa: PLC0415

    user_model = get_user_model()
    for declared in spec.users:
        user, created = user_model.objects.get_or_create(
            username=declared.username, defaults={"email": declared.email}
        )
        user.email = declared.email
        # Registration would leave the account inactive pending an activation
        # email; a declared user is one the install needs usable now.
        user.is_active = True
        user.is_superuser = declared.superuser
        user.is_staff = declared.staff or declared.superuser
        if declared.password_env:
            password = from_env(declared.password_env)
            # set_password salts afresh, and Django checks every session
            # against a hash of the stored password, so re-setting an unchanged
            # one would log the user out everywhere on every run.
            if not user.check_password(password):
                user.set_password(password)
        elif created:
            user.set_unusable_password()
        user.save()
        # Most of the LMS assumes user.profile exists, and a User row made
        # outside registration has none: the account and dashboard views 500.
        UserProfile.objects.get_or_create(user=user, defaults={"name": user.username})
        _report("users", declared.username, created=created)


def apply_oauth_applications(spec: BootstrapSpec, settings: Any) -> None:
    # Written through the ORM rather than create_dot_application, which logs
    # every client_secret at INFO: harmless in local dev, a leak anywhere else.
    from django.contrib.auth import get_user_model  # type: ignore[import-not-found]  # noqa: PLC0415
    from oauth2_provider.models import get_application_model  # type: ignore[import-not-found]  # noqa: PLC0415

    from openedx.core.djangoapps.oauth_dispatch.models import (  # type: ignore[import-not-found]  # noqa: PLC0415
        ApplicationAccess,
    )

    application_model = get_application_model()
    user_model = get_user_model()
    for declared in spec.oauth_applications:
        client_id = from_env(declared.client_id_env)
        fields = {
            "name": resolve(declared.name, settings),
            "user": user_model.objects.get(username=declared.user),
            "client_secret": from_env(declared.client_secret_env),
            "authorization_grant_type": declared.grant_type,
            "redirect_uris": " ".join(
                resolve(uri, settings) for uri in declared.redirect_uris
            ),
            "client_type": (
                application_model.CLIENT_PUBLIC
                if declared.public
                else application_model.CLIENT_CONFIDENTIAL
            ),
            "skip_authorization": declared.skip_authorization,
        }
        # Consumers such as edxnotes fetch their application by name, so a
        # second row under the same name (e.g. after a client_id rotation)
        # would break them with MultipleObjectsReturned.
        clash = (
            application_model.objects.filter(name=fields["name"])
            .exclude(client_id=client_id)
            .exists()
        )
        if clash:
            msg = (
                f"OAuth application {fields['name']!r} already exists under a "
                f"different client_id than {declared.client_id_env} holds; delete "
                "or rename it before applying this spec"
            )
            raise ValueError(msg)
        application, created = application_model.objects.update_or_create(
            client_id=client_id, defaults=fields
        )
        if declared.scopes:
            ApplicationAccess.objects.update_or_create(
                application=application, defaults={"scopes": declared.scopes}
            )
        _report("oauth_applications", fields["name"], created=created)


def apply_waffle_flags(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    from django.core import management  # type: ignore[import-not-found]  # noqa: PLC0415
    from waffle.models import Flag  # type: ignore[import-not-found]  # noqa: PLC0415

    for declared in spec.waffle_flags:
        created = not Flag.objects.filter(name=declared.name).exists()
        # waffle_flag narrates every option it sets; stdout is reserved for
        # the one JSON line per object.
        management.call_command("waffle_flag", *declared.argv(), stdout=sys.stderr)
        _report("waffle_flags", declared.name, created=created)


APPLY = {
    "users": apply_users,
    "oauth_applications": apply_oauth_applications,
    "waffle_flags": apply_waffle_flags,
}


def _parse_steps(value: str) -> list[str]:
    steps = [step.strip() for step in value.split(",") if step.strip()]
    unknown = [step for step in steps if step not in STEPS]
    if unknown:
        msg = f"unknown step(s) {', '.join(unknown)}; choose from {', '.join(STEPS)}"
        raise argparse.ArgumentTypeError(msg)
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lehrer_bootstrap")
    parser.add_argument("spec", help="Path to a bootstrap spec (YAML).")
    parser.add_argument(
        "--steps",
        type=_parse_steps,
        default=list(STEPS),
        help=f"Comma-separated subset of {','.join(STEPS)}. Always run in that order.",
    )
    args = parser.parse_args(argv)
    spec = load(args.spec)

    import django  # type: ignore[import-not-found]  # noqa: PLC0415

    django.setup()
    from django.conf import settings  # type: ignore[import-not-found]  # noqa: PLC0415

    for step in STEPS:
        if step in args.steps:
            APPLY[step](spec, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
