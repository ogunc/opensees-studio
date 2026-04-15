"""Shared pytest fixtures.

`pytest-qt` automatically provides a `qtbot` fixture and a QApplication
instance. We add convenience fixtures here as the suite grows.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_opensees() -> None:
    """Reset OpenSees domain between tests if openseespy is importable.

    Imported lazily so that pure-core tests don't pull in the C++ runtime.
    """
    try:
        import openseespy.opensees as ops
    except ImportError:
        return
    ops.wipe()
