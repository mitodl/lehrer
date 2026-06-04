"""Lehrer — Open edX build and deploy toolchain.

This module is the Dagger entry point.  It exposes a thin ``Lehrer`` root type
that delegates to service-specific sub-objects in ``lehrer.core``.
"""

from dagger import function, object_type

from lehrer.core.codejail import OpenedxCodejail
from lehrer.core.mfe import OpenedxMfe
from lehrer.core.notes import OpenedxNotes
from lehrer.core.platform import OpenedxPlatform


@object_type
class Lehrer:
    """Lehrer — Open edX build and deploy toolchain.

    Use the sub-commands to access each service builder::

        dagger call platform build-platform   ...   # edx-platform LMS/CMS image
        dagger call mfe build-legacy          ...   # legacy MFE dist/
        dagger call mfe build-site            ...   # OEP-65 Site Project (Phase 2)
        dagger call codejail build            ...   # codejail service image
        dagger call notes build               ...   # edx-notes-api image
    """

    @function
    def platform(self) -> OpenedxPlatform:
        """Access edx-platform build functions."""
        return OpenedxPlatform()

    @function
    def mfe(self) -> OpenedxMfe:
        """Access MFE build functions (legacy and OEP-65)."""
        return OpenedxMfe()

    @function
    def codejail(self) -> OpenedxCodejail:
        """Access codejail service build functions."""
        return OpenedxCodejail()

    @function
    def notes(self) -> OpenedxNotes:
        """Access edx-notes-api build functions."""
        return OpenedxNotes()
