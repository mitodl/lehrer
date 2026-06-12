import logging

import django

django.setup()
from django.core import management

from random import uniform
from time import sleep

log = logging.getLogger(__name__)

while True:
    # Execute randomly once every 24-48 hours
    sleep(uniform(86400, 172800))
    try:
        management.call_command("saml", ["--pull"])
    except Exception:
        log.exception("saml --pull failed; will retry next cycle")

exit(0)
