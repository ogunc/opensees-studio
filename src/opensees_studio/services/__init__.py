"""Service layer — I/O, solver invocation, persistence.

Services may import from ``core`` and may use external infrastructure
(file system, openseespy, h5py). Services may NOT import Qt.
"""

from opensees_studio.services.persistence import (
    PROJECT_FILE_SUFFIX,
    load_project,
    save_project,
)

__all__ = ["save_project", "load_project", "PROJECT_FILE_SUFFIX"]
