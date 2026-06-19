from ..common import *
from openedx.core.lib.derived import derive_settings

STATIC_ROOT_BASE = "/openedx/staticfiles"

SECRET_KEY = "secret"  # pragma: allowlist secret
XQUEUE_INTERFACE = {
    "django_auth": None,
    "url": None,
}
DATABASES = {
    "default": {},
}

# Required: cms/envs/common.py derives URL settings from LMS_ROOT_URL, which
# defaults to None in Studio. Without this, derive_settings() raises
# "unsupported operand type(s) for +: 'NoneType' and 'str'".
LMS_ROOT_URL = "lms.example.com"

derive_settings(__name__)

LOCALE_PATHS.append("/openedx/locale/contrib/locale")
LOCALE_PATHS.append("/openedx/locale/user/locale")
