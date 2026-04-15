"""Console entry point: ``python -m opensees_studio``."""

from __future__ import annotations

import sys

from opensees_studio.app import run


def main() -> int:
    """Launch the application. Returns the Qt exit code."""
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
