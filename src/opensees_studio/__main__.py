"""Entry point of the application, and of the frozen bundle's child CLI.

``python -m opensees_studio`` (or the ``opensees-studio`` script) launches
the GUI. The same executable, started with
:data:`~opensees_studio.child_cli.CLI_FLAG`, runs the analysis CLI instead:
a frozen bundle has no ``python -m`` to re-enter, so re-running the bundle
is how the GUI gets its child analysis process there (see
:mod:`opensees_studio.child_cli`).

Both branches import lazily, so the child never loads Qt.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Launch the GUI, or the analysis CLI when the child flag is present."""
    from opensees_studio.child_cli import CLI_FLAG

    argv = sys.argv
    if len(argv) > 1 and argv[1] == CLI_FLAG:
        from opensees_studio.run import main as cli_main

        return cli_main(argv[2:])

    from opensees_studio.app import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
