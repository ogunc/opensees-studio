# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the end-user desktop bundle.

Build with::

    python packaging/build.py

Produces ``dist/OpenSeesStudio/`` — a folder you can zip and hand to someone
who has no Python: ``OpenSeesStudio`` (the GUI) is the file they run.

Three things here are not obvious and are the reason this file exists at all
instead of a one-line ``pyinstaller`` call:

* **OpenSeesPy has no PyInstaller hook.** ``openseespylinux`` / ``openseespywin``
  ship one large extension module (about 250 MB) with BLAS/LAPACK next to it,
  loaded by name from the package ``__init__``. Nothing in the import graph
  points at the shared libraries, so they are collected explicitly.
* **The bundle re-runs itself for analyses.** ``opensees_studio.child_cli``
  makes the frozen executable double as the analysis CLI (a bundle has no
  ``python -m``), and ``__main__`` dispatches it. Nothing extra is needed in
  the spec for that, but the smoke test in ``packaging/build.py`` and in CI
  exists to prove it still works.
* **scipy and pandas are excluded deliberately.** ``pyproject.toml`` carries
  them as forward-compatibility extras that no module imports; freezing them
  would add about 180 MB of dead weight.

``console=False`` is what makes the Windows/macOS bundle a normal windowed
application. The analysis child is then started with ``CREATE_NO_WINDOW``
(see ``viewmodels/analysis_runner.py``) so it does not flash a console.
"""

from pathlib import Path
import glob
import sysconfig

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"

APP_NAME = "OpenSeesStudio"

# ── OpenSees: collected by hand, there is no hook for it ────────────────
datas = []
binaries = []
hiddenimports = []

for package in ("openseespylinux", "openseespy"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:  # platform-specific wheel of the other OS
        print(f"[spec] {package} not installed here ({exc}); skipping")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Package data that is not a Python module, so nothing discovers it: the AISC
# shape table the section picker reads at runtime. Without this the frozen app
# opens the picker and fails on a missing CSV.
datas += [
    (str(SRC / "opensees_studio" / "data" / name), "opensees_studio/data")
    for name in ("aisc_v16.csv", "README.md", "LICENSE-steelpy.txt")
]

# PyVista is built with mypyc: `pyvista.typing.mypy_plugin` — imported at
# runtime by `pyvista/core/dataobject.py`, not only by the type checker —
# imports a top-level native module whose name is a content hash, e.g.
# `6ec57f84c680d3a3778b__mypyc`. Nothing in the import graph names it, and
# the name changes with every PyVista release, so it is globbed here.
for _mypyc in glob.glob(str(Path(sysconfig.get_paths()["purelib"]) / "*__mypyc*")):
    binaries.append((_mypyc, "."))

# ── Modules that are imported by name, or only on a code path ───────────
hiddenimports += [
    "pyvistaqt",
    "pyqtgraph",
    "h5py",
    "imageio_ffmpeg",
    "opensees_studio.run",
]

# ── VTK: the whole namespace, on purpose ───────────────────────────────
# PyVista imports VTK modules *dynamically*: classes are looked up by name in
# `pyvista/_vtk.py` and the rendering backends are pulled in through
# `importlib.import_module` in `pyvista/plotting/_rendering_imports.py`. A
# static analysis therefore sees almost none of what the application can
# reach, and a curated list fails at startup on the first module it missed —
# observed in turn with vtkmodules.vtkFiltersSources and
# vtkmodules.vtkRenderingContextOpenGL2.
#
# Shipping all of them costs roughly 500 MB. Trimming it is a real option but
# needs a runtime check per removed family (open every dialog, plot every
# result), which does not exist yet, so correctness wins for now and the
# bundle carries the full namespace. The flat `vtk` shim below is the one
# part that is provably unused.
hiddenimports += collect_submodules("vtkmodules")

# ── Nothing here imports these ─────────────────────────────────────────
excludes = [
    "scipy",
    "pandas",
    "matplotlib.tests",
    "pytest",
    "IPython",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "sphinx",
    "docutils",
    # A development-only dependency that PyVista's mypy plugin imports inside
    # `if importlib.util.find_spec('mypy')`. Leaving it out of the bundle
    # keeps that branch switched off at runtime (which is what the plugin
    # expects outside a type check) and saves the whole mypy distribution.
    "mypy",
    # The flat ``vtk`` shim re-exports the whole VTK namespace (~500 MB of
    # libraries, including chemistry, geovis and Exodus readers this
    # application never touches). PyVista imports it only inside an
    # ``if TYPE_CHECKING:`` block, which static analysis still walks, so it
    # lands in the graph even though no runtime path loads it: verified with
    # ``import pyvista, opensees_studio.views.main_window`` leaving ``vtk``
    # out of ``sys.modules``. PyVista resolves everything through
    # ``vtkmodules.*``, which is what stays bundled.
    "vtk",
    # VTK namespace pieces reachable only from that shim.
    "vtkmodules.tk",
    "vtkmodules.wx",
    "vtkmodules.web",
    "vtkmodules.test",
    "vtkmodules.qt",
]

a = Analysis(  # noqa: F821 - provided by PyInstaller
    [str(SRC / "opensees_studio" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # The roadmap still owes a native .ico/.icns; add it here when it lands.
    icon=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
