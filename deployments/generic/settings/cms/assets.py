# -*- mode: python -*-
"""
Bare minimum settings for collecting CMS (Studio) production assets — generic Open edX deployment.
"""

from ..common import *
from openedx.core.lib.derived import derive_settings

ENABLE_COMPREHENSIVE_THEMING = True
COMPREHENSIVE_THEME_DIRS.append("/openedx/themes")

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
