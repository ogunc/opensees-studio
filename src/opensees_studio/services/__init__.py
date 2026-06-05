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
    load_project,
    save_project,
)
from opensees_studio.services.results import (
    ModalResults,
    StaticResults,
    TransientResults,
)

__all__ = [
    "PROJECT_FILE_SUFFIX",
    "CyclicSegment",
    "LoadProtocol",
    "MaterialTestResult",
    "ModalResults",
    "OpenSeesRunner",
    "StaticResults",
    "TransientResults",
    "load_project",
    "save_project",
    "test_uniaxial_material",
]
