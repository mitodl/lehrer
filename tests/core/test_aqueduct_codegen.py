from __future__ import annotations

import ast
import inspect

import pytest

from lehrer.core import platform
from lehrer.core.platform import _aqueduct_codegen_cmd

_INVOCATION = "python -m django generate_aqueduct_settings"


@pytest.mark.parametrize("service", ["lms", "cms"])
def test_codegen_cmd_declares_the_services_plugin_entry_points(service: str) -> None:
    # Without --openedx-plugins the model carries no field for a setting a
    # plugin's plugin_settings() assigns, and pydantic-settings -- which
    # collects env values per *declared* field -- drops the pod's value instead
    # of parsing it (django-aqueduct >= 0.14.0).
    command = _aqueduct_codegen_cmd(service, f"{service}/envs/models/aqueduct.py")
    assert f"--modules openedx.envs.common,{service}.envs.common " in command
    assert f"--openedx-plugins {service}.djangoapp" in command
    assert f"--output {service}/envs/models/aqueduct.py --reset" in command


def test_every_codegen_call_site_goes_through_the_helper() -> None:
    """Regeneration and the drift check must render the model identically.

    The drift check in ``verify_settings`` only means anything if it renders
    the model the same way ``regenerate_aqueduct_settings`` does.  The two used
    to build the command inline, and a flag added to one and not the other
    turns every drift run red with a diff the documented remediation command
    cannot fix.  Guard the shared helper rather than the symptom.
    """
    tree = ast.parse(inspect.getsource(platform))
    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_aqueduct_codegen_cmd"
    )
    helper_strings = {
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    strays = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _INVOCATION in node.value
        and node not in helper_strings
    ]
    assert not strays, (
        f"{_INVOCATION!r} is built inline at platform.py line(s) "
        f"{strays} -- call _aqueduct_codegen_cmd instead"
    )
