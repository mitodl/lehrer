"""Apply a bootstrap spec to this Open edX install.

Runs inside the platform image, where lehrer bakes this package in as
``lehrer_bootstrap``, from the edx-platform checkout (the steps that shell out
run ``manage.py`` from there)::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct \\
        python -m lehrer_bootstrap /path/to/bootstrap.yaml [--steps users,waffle_flags]

Every step converges the database on the spec, so re-running it is safe. Each
object applied prints one JSON line on stdout (``{"step", "target",
"result"}``), which is what a Job's caller, and later an operator, reads to
tell what changed. ``result`` is created/updated for database objects,
applied/unchanged for migrations and imported for the demo course.
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
from typing import Any

from .spec import STEPS, BootstrapSpec, Migration, from_env, load, resolve


def _report(step: str, target: str, result: str) -> None:
    print(json.dumps({"step": step, "target": target, "result": result}), flush=True)  # noqa: T201


def _created(created: bool) -> str:  # noqa: FBT001
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
        _report("users", declared.username, _created(created))


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
        _report("oauth_applications", fields["name"], _created(created))


def apply_waffle_flags(spec: BootstrapSpec, settings: Any) -> None:  # noqa: ARG001
    from django.core import management  # type: ignore[import-not-found]  # noqa: PLC0415
    from waffle.models import Flag  # type: ignore[import-not-found]  # noqa: PLC0415

    for declared in spec.waffle_flags:
        created = not Flag.objects.filter(name=declared.name).exists()
        # waffle_flag narrates every option it sets; stdout is reserved for
        # the one JSON line per object.
        management.call_command("waffle_flag", *declared.argv(), stdout=sys.stderr)
        _report("waffle_flags", declared.name, _created(created))


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


APPLY = {
    "migrate": apply_migrate,
    "users": apply_users,
    "oauth_applications": apply_oauth_applications,
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

    django.setup()
    from django.conf import settings  # type: ignore[import-not-found]  # noqa: PLC0415

    for step in STEPS:
        if step in args.steps:
            APPLY[step](spec, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
