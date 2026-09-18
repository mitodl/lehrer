# ruff: noqa: INP001, E402
"""Create the LMS objects a fresh local-dev install needs.

Mounted into the edxapp-provision Job from a ConfigMap that lehrer-core.star
builds out of this directory, and run inside the platform image against
``lms.envs.aqueduct``. It cannot be imported or type-checked here: every
edx-platform symbol it touches only exists inside that image.

Idempotent — every object is get-or-created and then updated in place, so
re-running against a provisioned database is a no-op apart from resetting the
superuser password to the configured value.
"""

import os

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import management

from common.djangoapps.student.models import UserProfile

USERNAME = os.environ.get("PROVISION_SUPERUSER_USERNAME", "edx")
EMAIL = os.environ.get("PROVISION_SUPERUSER_EMAIL", "edx@example.com")
PASSWORD = os.environ.get("PROVISION_SUPERUSER_PASSWORD", "edx")  # noqa: S105

User = get_user_model()

user, created = User.objects.get_or_create(username=USERNAME, defaults={"email": EMAIL})
user.email = EMAIL
# do_create_account() would leave the account inactive pending an activation
# email that local dev has no way to deliver, so the account is built directly
# and activated here.
user.is_active = True
user.is_staff = True
user.is_superuser = True
user.set_password(PASSWORD)
user.save()

# Most of the LMS assumes user.profile exists; a User row created without going
# through registration has none, and the account/dashboard views 500 on the
# missing reverse relation.
UserProfile.objects.get_or_create(user=user, defaults={"name": USERNAME})

print("==> {} superuser {}".format("Created" if created else "Updated", USERNAME))

# LMS signs the notes annotator token with this Application's client_secret and
# sets aud to its client_id (lms/djangoapps/edxnotes/helpers.py ->
# get_edxnotes_id_token), looking the Application up by *name*. edx-notes-api
# validates with its own CLIENT_SECRET/CLIENT_ID (notesapi/v1/permissions.py),
# which the notes Deployment feeds from the same two secret keys. All three
# values have to line up or every notes request 403s.
management.call_command(
    "create_dot_application",
    settings.EDXNOTES_CLIENT_NAME,
    USERNAME,
    grant_type="client-credentials",
    client_id=os.environ["NOTES_OAUTH_CLIENT_ID"],
    client_secret=os.environ["NOTES_OAUTH_CLIENT_SECRET"],
    skip_authorization=False,
    update=True,
)
print("==> Provisioned OAuth application " + settings.EDXNOTES_CLIENT_NAME)

# Studio has no login of its own: its /login/ starts auth_backends' EdXOAuth2
# flow against the LMS, which rejects the callback unless it is registered
# here. CMS_ROOT_URL is the Studio address the LMS config carries, so a caller
# that overrides CMS_BASE_URL registers its own host. The client id and secret
# are the SOCIAL_AUTH_EDX_OAUTH2_KEY/SECRET the CMS reads from the same Secret.
#
# Add further OAuth clients here as the stack grows to need them.
management.call_command(
    "create_dot_application",
    "cms-sso",
    USERNAME,
    grant_type="authorization-code",
    redirect_uris=settings.CMS_ROOT_URL + "/complete/edx-oauth2/",
    client_id=os.environ["SOCIAL_AUTH_EDX_OAUTH2_KEY"],
    client_secret=os.environ["SOCIAL_AUTH_EDX_OAUTH2_SECRET"],
    # auth_backends asks for user_id alongside profile and email, and the LMS
    # answers invalid_scope unless the application's access record allows it.
    scopes="user_id",
    skip_authorization=True,
    update=True,
)
print("==> Provisioned OAuth application cms-sso")
