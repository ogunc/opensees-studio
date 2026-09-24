"""Service layer — I/O, solver invocation, persistence.

Services may import from ``core`` and may use external infrastructure
(file system, openseespy, h5py). Most services are Qt-free. The Qt
worker lives in ``qt_workers`` and is the only module here that
imports PySide6.
"""

from opensees_studio.services.material_tester import (
    CyclicSegment,
    LoadProtocol,
    MaterialTestResult,
    test_uniaxial_material,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import (
    PROJECT_FILE_SUFFIX,
    RUN_SNAPSHOT_SUFFIX,
    discard_run_snapshot,
    load_project,
    newer_run_snapshot,
    run_snapshot_path,
    save_project,
    write_run_snapshot,
)
from opensees_studio.services.results import (
    ModalResults,
    StaticResults,
    TransientResults,
)

__all__ = [
    "PROJECT_FILE_SUFFIX",
    "RUN_SNAPSHOT_SUFFIX",
    "CyclicSegment",
    "LoadProtocol",
    "MaterialTestResult",
    "ModalResults",
    "OpenSeesRunner",
    "StaticResults",
    "TransientResults",
    "discard_run_snapshot",
    "load_project",
    "newer_run_snapshot",
    "run_snapshot_path",
    "save_project",
    "test_uniaxial_material",
    "write_run_snapshot",
]
