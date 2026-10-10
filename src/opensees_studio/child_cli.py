"""How this installation re-enters the analysis CLI in a child process.

The GUI runs every analysis in a child process so that a hard exit inside
OpenSees cannot take the application down. From a source checkout that
child is ``python -u -m opensees_studio.run ...``. A frozen (PyInstaller)
bundle has no module search path and no ``python`` of its own: the only
interpreter is the bundle's own executable, so the child re-enters it
through :data:`CLI_FLAG` and ``__main__`` dispatches the flag back to
:func:`opensees_studio.run.main`.

Deliberately imports nothing but ``sys``: the frozen child must reach the
CLI without pulling Qt or OpenSeesPy into the module import.
"""

from __future__ import annotations

import sys

CLI_FLAG = "--run-analysis-cli"
"""First argument that turns the application executable into the analysis CLI."""


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a source tree."""
    return bool(getattr(sys, "frozen", False))


def analysis_cli_command() -> list[str]:
    """argv prefix, program included, that runs the analysis CLI here.

    Callers append the CLI arguments (``--project``, ``--cases``, ``--out``,
    optional ``--case-override``).
    """
    if is_frozen():
        return [sys.executable, CLI_FLAG]
    return [sys.executable, "-u", "-m", "opensees_studio.run"]
