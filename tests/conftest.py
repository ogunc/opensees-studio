"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_opensees() -> None:
    """Reset OpenSees domain between tests if openseespy is usable.

    Catches both ImportError (package missing) and any runtime error
    (DLL load failure on Windows, missing system libs on Linux, etc.)
    so that pure-core tests run regardless of the solver's availability.
    """
    try:
        import openseespy.opensees as ops
        ops.wipe()
    except Exception:
        return
