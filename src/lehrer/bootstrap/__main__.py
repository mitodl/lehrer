"""Apply a bootstrap spec to this Open edX install.

Runs inside the platform image, where lehrer bakes this package in as
``lehrer_bootstrap``, from the edx-platform checkout (the steps that shell out
run ``manage.py`` from there)::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct \\
        python -m lehrer_bootstrap /path/to/bootstrap.yaml [--steps users,waffle_flags]

Every step converges the database on the spec, so re-running it is safe. Each
object applied prints one JSON line on stdout (``{"step", "target",
"result"}``), which is what a Job's caller, and later an operator, reads to
tell what changed. ``result`` is created/updated/unchanged for database
objects, applied/unchanged for migrations and imported for the demo course.
Everything else, including the output of the commands a step runs, goes to
stderr. A failure raises and exits non-zero after the lines for everything
already applied.

argparse rather than cyclopts: the image has no cyclopts, and this must not
depend on anything the platform does not already install.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from .spec import (
    STEPS,
    BootstrapSpec,
    Migration,
    from_env,
    from_env_optional,
    load,
    resolve,
)

Result = Literal["created", "updated", "unchanged", "applied", "imported"]


def _report(step: str, target: str, result: Result) -> None:
    print(json.dumps({"step": step, "target": target, "result": result}), flush=True)  # noqa: T201


def _written(*, created: bool) -> Result:
    return "created" if created else "updated"


def _manage(service: str, *args: str) -> list[str]:
    """A ``manage.py`` command line for ``service`` under this run's settings.

    manage.py prefers DJANGO_SETTINGS_MODULE over its service argument, so a
    CMS command run from an LMS-configured process would load the LMS settings.
    ``--settings`` wins over both, and takes the module name under
    ``<service>.envs``.
    """
    settings_name = os.environ["DJANGO_SETTINGS_MODULE"].rpartition(".")[2]
    return [
        sys.executable,
        "manage.py",
        service,
        *args,
        f"--settings={settings_name}",
    ]


def _run_migrate(command: list[str]) -> bool:
    """Run a migrate command, echoing its output to stderr.

    :returns: whether it applied anything. Counting "Applying ... OK" lines
        would undercount: the platform logs to the same stream while a
        migration runs, so the OK can land on a later line.
    """
    unchanged = False
    with subprocess.Popen(  # noqa: S603
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as process:
        assert process.stdout is not None  # noqa: S101
        for line in process.stdout:
            sys.stderr.write(line)
            unchanged = unchanged or line.strip() == "No migrations to apply."
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)
    return not unchanged


def _migrate(migration: Migration) -> None:
    target: str = migration.service
    if migration.app_label:
        target += f" {migration.app_label}"
    if migration.database != "default":
        target += f"@{migration.database}"
    app = [migration.app_label] if migration.app_label else []
    # migrate's system checks import ROOT_URLCONF and call get_user_model(),
    # which fails against a schema that does not exist yet. Migrations do not
    # need them.
    applied = _run_migrate(
        _manage(
            migration.service,
            "migrate",
            *app,
            "--noinput",
            f"--database={migration.database}",
            "--skip-checks",
        )
    )
    _report("migrate", target, "applied" if applied else "unchanged")


def apply_migrate(spec: BootstrapSpec, settings: Any) -> None:
    # Some data migrations (e.g. certificates/0003) write badge images through
    # FileSystemStorage, which fails if MEDIA_ROOT does not exist yet.
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    for migration in spec.migrate:
        _migrate(migration)


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
        _report("users", declared.username, _written(created=created))


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
        _report("oauth_applications", fields["name"], _written(created=created))


def apply_third_party_auth_providers(spec: BootstrapSpec, settings: Any) -> None:
    from django.contrib.sites.models import Site  # type: ignore[import-not-found]  # noqa: PLC0415

    from common.djangoapps.third_party_auth.models import (  # type: ignore[import-not-found]  # noqa: PLC0415
        OAuth2ProviderConfig,
    )

    for declared in spec.third_party_auth_providers:
        other_settings = from_env_optional(declared.other_settings_env)
        client_id = from_env_optional(declared.client_id_env)
        client_secret = from_env_optional(declared.client_secret_env)
        if not (other_settings and client_id and client_secret):
            # Not an error: an install with no upstream IdP in front of it
            # leaves these unset, and creating the row anyway would put a login
            # button on the page that cannot work. See ThirdPartyAuthProvider.
            print(  # noqa: T201
                f"third_party_auth_providers: skipping {declared.backend_name} "
                "(credentials or other_settings not supplied)",
                file=sys.stderr,
            )
            continue

        # Validated here rather than at the far end of a login redirect, where
        # a malformed value surfaces as a social-core KeyError on whichever
        # setting the backend happened to read first.
        try:
            parsed = json.loads(other_settings)
        except json.JSONDecodeError as error:
            msg = (
                f"{declared.other_settings_env} must be a JSON object of "
                f"provider settings: {error}"
            )
            raise ValueError(msg) from None
        if not isinstance(parsed, dict):
            msg = f"{declared.other_settings_env} must be a JSON object, not a {type(parsed).__name__}"  # noqa: E501
            raise ValueError(msg)

        site = Site.objects.get(pk=settings.SITE_ID)
        fields = {
            "slug": declared.slug,
            "name": declared.name,
            "enabled": declared.enabled,
            "visible": declared.visible,
            "skip_hinted_login_dialog": declared.skip_hinted_login_dialog,
            "skip_registration_form": declared.skip_registration_form,
            "skip_email_verification": declared.skip_email_verification,
            "sync_learner_profile_data": declared.sync_learner_profile_data,
            "key": client_id,
            "secret": client_secret,
            # Canonicalised, so a reordered or reindented env value does not
            # read as a change and append a new version on every apply.
            "other_settings": json.dumps(parsed, sort_keys=True),
        }
        # OAuth2ProviderConfig is a ConfigurationModel: rows are an append-only
        # history keyed on KEY_FIELDS (site_id, backend_name) and the newest
        # wins. There is nothing to update in place -- a change means a new row
        # -- so idempotency has to be a comparison against the newest one.
        #
        # Queried directly rather than through .current(): that override takes
        # only the non-site key fields and resolves site_id itself from the
        # *current request*, which a provisioning job does not have.
        current = (
            OAuth2ProviderConfig.objects.filter(
                site_id=site.id, backend_name=declared.backend_name
            )
            .order_by("-change_date", "-id")
            .first()
        )
        unchanged = current is not None and all(
            getattr(current, key) == value for key, value in fields.items()
        )
        if not unchanged:
            OAuth2ProviderConfig.objects.create(
                site=site, backend_name=declared.backend_name, **fields
            )
        # Unchanged is its own result here, not an update: a
        # ConfigurationModel row is never written in place, so "updated" would
        # claim a new history row that this run did not append.
        _report(
            "third_party_auth_providers",
            declared.backend_name,
            "unchanged" if unchanged else "created",
        )


def apply_service_access_tokens(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    from datetime import timedelta  # noqa: PLC0415

    from django.contrib.auth import get_user_model  # type: ignore[import-not-found]  # noqa: PLC0415
    from django.utils import timezone  # type: ignore[import-not-found]  # noqa: PLC0415
    from common.djangoapps.student.models import (  # type: ignore[import-not-found]  # noqa: PLC0415
        UserProfile,
    )
    from oauth2_provider.models import (  # type: ignore[import-not-found]  # noqa: PLC0415
        get_access_token_model,
        get_application_model,
    )

    user_model = get_user_model()
    application_model = get_application_model()
    token_model = get_access_token_model()

    for declared in spec.service_access_tokens:
        token = from_env_optional(declared.token_env)
        if not token:
            print(  # noqa: T201
                f"service_access_tokens: skipping {declared.username} "
                f"({declared.token_env} not supplied)",
                file=sys.stderr,
            )
            continue

        user, _ = user_model.objects.get_or_create(
            username=declared.username,
            defaults={"email": declared.email, "is_active": True},
        )
        # Reasserted rather than left to the defaults above, so an account that
        # already exists converges on the spec instead of keeping whatever it
        # was created with by hand.
        user.email = declared.email
        user.is_active = True
        user.is_staff = declared.staff
        if user.has_usable_password():
            user.set_unusable_password()
        user.save()
        # Same reason as apply_users: the LMS assumes user.profile exists.
        UserProfile.objects.get_or_create(user=user, defaults={"name": user.username})

        # Same reasoning as apply_oauth_applications, and the same remedy:
        # Application.name carries no uniqueness constraint, so an install that
        # already has two rows under this name makes update_or_create raise
        # MultipleObjectsReturned with nothing naming the duplicate.
        if application_model.objects.filter(name=declared.application_name).count() > 1:
            msg = (
                f"more than one OAuth application is named "
                f"{declared.application_name!r}; delete all but the one this "
                "spec should own before applying it"
            )
            raise ValueError(msg)
        application, _ = application_model.objects.update_or_create(
            name=declared.application_name,
            defaults={
                "user": user,
                "client_type": application_model.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": application_model.GRANT_CLIENT_CREDENTIALS,
            },
        )
        # A token string is a credential, not a key to overwrite: if this exact
        # value already belongs to somebody else, the spec and the database
        # disagree about who owns it, and update_or_create would silently
        # reassign it and break whatever integration was using it.
        existing = token_model.objects.filter(token=token).first()
        if existing is not None and existing.user_id != user.id:
            msg = (
                f"the token in {declared.token_env} already belongs to a "
                f"different user than {declared.username!r}; rotate it or "
                "delete the existing AccessToken before applying this spec"
            )
            raise ValueError(msg)
        _, created = token_model.objects.update_or_create(
            token=token,
            defaults={
                "user": user,
                "application": application,
                "expires": timezone.now() + timedelta(days=declared.expires_in_days),
                "scope": " ".join(declared.scopes),
            },
        )
        # Any older token for this account is now unreachable by the upstream,
        # which only ever sends the configured one; leaving them would be a
        # credential with no owner.
        token_model.objects.filter(user=user).exclude(token=token).delete()
        _report("service_access_tokens", declared.username, _written(created=created))


def apply_waffle_flags(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    from django.core import management  # type: ignore[import-not-found]  # noqa: PLC0415
    from waffle.models import Flag  # type: ignore[import-not-found]  # noqa: PLC0415

    for declared in spec.waffle_flags:
        created = not Flag.objects.filter(name=declared.name).exists()
        # waffle_flag narrates every option it sets; stdout is reserved for
        # the one JSON line per object.
        management.call_command("waffle_flag", *declared.argv(), stdout=sys.stderr)
        _report("waffle_flags", declared.name, _written(created=created))


def _demo_course_branch(repo: str, release_line: str) -> str:
    # openedx-demo-course has named its branches three ways: release/<name>
    # from Teak on, open-release/<name>.master before that, and master
    # tracking edx-platform master. Probing beats a mapping that goes stale.
    candidates = [
        f"release/{release_line}",
        f"open-release/{release_line}.master",
        release_line,
    ]
    for branch in candidates:
        found = subprocess.run(  # noqa: S603
            ["git", "ls-remote", "--exit-code", "--heads", repo, branch],  # noqa: S607
            stdout=subprocess.DEVNULL,
            check=False,
        )
        if found.returncode == 0:
            return branch
    msg = (
        f"{repo} has none of the branches {', '.join(candidates)}; set "
        "demo_course.branch in the spec"
    )
    raise ValueError(msg)


def _demo_course_dir(checkout: Path) -> Path:
    """The directory holding the demo course's ``course.xml``.

    Redwood onward keep it under ``demo-course/course``, beside a content
    library; Quince and earlier at the repository root.
    """
    for course in (checkout / "demo-course" / "course", checkout):
        if (course / "course.xml").is_file():
            return course
    msg = f"no course.xml in {checkout} or {checkout}/demo-course/course"
    raise ValueError(msg)


def apply_demo_course(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    declared = spec.demo_course
    if declared is None:
        return
    from openedx.core.release import RELEASE_LINE  # type: ignore[import-not-found]  # noqa: PLC0415

    branch = declared.branch or _demo_course_branch(declared.repo, RELEASE_LINE)
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "openedx-demo-course"
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                declared.repo,
                str(checkout),
            ],
            check=True,
            stdout=sys.stderr,
        )
        course = _demo_course_dir(checkout)
        # import takes a data directory and course directories relative to it.
        # Course assets land in the MongoDB contentstore, so the checkout can
        # go once it is done.
        subprocess.run(  # noqa: S603
            _manage("cms", "import", str(course.parent), course.name),
            check=True,
            stdout=sys.stderr,
        )
    _report("demo_course", f"{declared.repo}@{branch}", "imported")


IN_PROCESS = {
    "users",
    "oauth_applications",
    "third_party_auth_providers",
    "service_access_tokens",
    "waffle_flags",
}
"""Steps that call the ORM in this process, and so need ``django.setup()``."""

APPLY = {
    "migrate": apply_migrate,
    "users": apply_users,
    "oauth_applications": apply_oauth_applications,
    "third_party_auth_providers": apply_third_party_auth_providers,
    "service_access_tokens": apply_service_access_tokens,
    "waffle_flags": apply_waffle_flags,
    "demo_course": apply_demo_course,
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
    from django.conf import settings  # type: ignore[import-not-found]  # noqa: PLC0415

    # Only the steps that use the ORM need the app registry, so it is set up
    # just before the first of them. migrate and demo_course do their work in
    # manage.py children, which load their own; setting one up any earlier
    # would hold a second platform in memory while they run, and would do it
    # against a schema that migrate has not created yet. Lazy settings read
    # without it.
    set_up = False
    for step in STEPS:
        if step not in args.steps:
            continue
        if step in IN_PROCESS and not set_up:
            django.setup()
            set_up = True
        APPLY[step](spec, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
