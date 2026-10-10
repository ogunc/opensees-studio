"""Shared pytest fixtures.

`pytest-qt` automatically provides a `qtbot` fixture and a QApplication
instance. We add convenience fixtures here as the suite grows.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _app_data_dir_in_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep pre-run snapshots of never-saved projects out of the user's data directory."""
    import os

    os.environ["OPENSEES_STUDIO_DATA_DIR"] = str(tmp_path_factory.mktemp("app-data"))


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
