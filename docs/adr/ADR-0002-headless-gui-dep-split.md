# ADR-0002 — Split pyproject dependencies into headless base and `gui` optional extra

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-15 |
| **Author** | ogunc |

---

## 1. Context

`opensees_studio.core` is pure Pydantic v2 (no Qt, no OpenSeesPy imports — stated
explicitly in `core/__init__.py`). `opensees_studio.services` adds NumPy, h5py, and
OpenSeesPy for headless computation. Together, these two packages can be used from
scripts, Jupyter notebooks, and web backends **without any Qt or 3D-rendering stack**.

Before this ADR, every `pip install opensees-studio` pulled in PySide6, pyvista,
pyvistaqt, vtk, pyqtgraph, and imageio — roughly 800 MB of GUI/visualization
packages — even when only the headless computation layer was needed. Web backends and
CI machines without a display had to work around this with `--no-deps`, which is
fragile and skips genuine compute-layer deps (numpy, h5py) too.

## 2. Decision

Split `[project.dependencies]` into two tiers in `pyproject.toml`:

### Headless base (`pip install -e .`)

Packages imported by `core/` and the non-Qt parts of `services/`:

| Package | Where used |
|---------|-----------|
| `pydantic>=2.5` | All `core/` modules, `material_tester.py` |
| `numpy>=1.26` | `services/` computation modules (7 files) |
| `h5py>=3.10` | `opensees_runner._run_transient()`, `TransientResults` accessors |
| `openseespy==3.8.0.0` | Lazy import in `OpenSeesRunner.__init__` |
| `openseespywin==3.8.0.0 ; sys_platform=='win32'` | Windows DLL companion |

### GUI extra (`pip install -e ".[gui]"`)

Packages only needed by `views/`, `viewmodels/`, `commands/`, `qt_workers.py`,
and `animation_export.py` (which drives a live PyVista plotter):

`PySide6`, `pyvista`, `pyvistaqt`, `vtk`, `pyqtgraph`, `imageio[ffmpeg]`,
`scipy` (forward-compat, currently a phantom dep), `pandas` (same).

## 3. Consequences

- **Desktop developers** install with `pip install -e ".[gui,dev]"`. No change to
  what gets installed; only the install command changes from `.[dev]` → `.[gui,dev]`.
- **Web backends / scripts / notebooks** install with `pip install -e .` (or
  `pip install opensees-studio`) and get a lean ~50 MB environment.
- **opensees-studio-web** can drop the `--no-deps` workaround and install the
  package normally. The web backend's `requirements.txt` no longer needs to list
  pydantic/numpy/h5py separately — they come from the base install.
- **scipy and pandas** are listed under `[gui]` as phantom deps (currently never
  imported anywhere in the codebase). They are kept to avoid surprise breakage if a
  future feature adds them; audited and flagged on 2026-06-15.

## 4. Verification

After installing only the base set:

```python
import sys
from opensees_studio.core import Project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.material_tester import test_uniaxial_material

# Run a modal analysis on the bundled two-storey shear frame example
import json
from pathlib import Path
from opensees_studio.core import ModalCase

data = json.loads(Path("examples/eigen_two_storey_shear_frame.osmodel").read_text())
project = Project.model_validate(data)
modal_case = next(c for c in project.analyses if isinstance(c, ModalCase))
runner = OpenSeesRunner(project)
runner.build()
results = runner._run_modal(modal_case)

assert len(results.eigenvalues) == 2
assert all(ev > 0 for ev in results.eigenvalues)

gui_packages = {"PySide6", "pyvista", "pyvistaqt", "vtk", "pyqtgraph"}
assert not gui_packages.intersection(sys.modules), \
    f"GUI package imported: {gui_packages & sys.modules.keys()}"

print("PASS — headless modal analysis complete, no GUI packages imported")
```
