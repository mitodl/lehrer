import logging

import django

django.setup()
from django.core import management
from lms.djangoapps.instructor_task.management.commands import (
    process_scheduled_instructor_tasks,
)

from random import uniform
from time import sleep

log = logging.getLogger(__name__)

while True:
    sleep(uniform(300, 600))
    try:
        management.call_command(process_scheduled_instructor_tasks.Command(), [])
    except Exception:
        log.exception(
            "process_scheduled_instructor_tasks failed; will retry next cycle"
        )

exit(0)
