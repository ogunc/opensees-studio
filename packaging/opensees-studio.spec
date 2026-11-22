# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the end-user desktop bundle.

Build with::

    python packaging/build.py

Produces ``dist/OpenSeesStudio/`` — a folder you can zip and hand to someone
who has no Python: ``OpenSeesStudio`` (the GUI) is the file they run.

Three things here are not obvious and are the reason this file exists at all
instead of a one-line ``pyinstaller`` call:

* **OpenSeesPy is not in the bundle.** It is a separate program with its own
  license (ADR-0003): the user installs it from Options → Solver, which
  downloads it from PyPI into a folder the analysis child appends to
  ``sys.path``. It is listed in ``excludes`` because PyInstaller also follows
  the lazy imports inside the runner, and a developer's environment has it.
* **The bundle re-runs itself for analyses.** ``opensees_studio.child_cli``
  makes the frozen executable double as the analysis CLI (a bundle has no
  ``python -m``), and ``__main__`` dispatches it. Nothing extra is needed in
  the spec for that, but the smoke test in ``packaging/build.py`` and in CI
  exists to prove it still works.
* **pandas is excluded deliberately.** No module imports it (it left the
  ``gui`` extra on 2026-11-15); the exclusion keeps a package that pulls it in
  transitively out of the bundle. scipy used to be excluded too; the bundled
  PyNite engine needs it now (about 140 MB).

``console=False`` is what makes the Windows/macOS bundle a normal windowed
application. The analysis child is then started with ``CREATE_NO_WINDOW``
(see ``viewmodels/analysis_runner.py``) so it does not flash a console.
"""

from pathlib import Path
import glob
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"

APP_NAME = "OpenSeesStudio"

datas = []
binaries = []
hiddenimports = []

# ifcopenshell (File → Export / Import → IFC) is imported lazily and ships a native
# library plus its schema files, so it is collected whole; so is the PyNite
# engine, imported only when it runs.
for package in ("ifcopenshell", "Pynite"):
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
    for name in ("aisc_v16.csv", "README.md", "LICENSE-steelpy.txt", "logo.svg")
]
# The interface translations (Options → Language).
datas += [(str(SRC / "opensees_studio" / "data" / "i18n" / "es.json"), "opensees_studio/data/i18n")]
# One SVG per command (the ribbon, the menus and the toolbars).
datas += [(str(SRC / "opensees_studio" / "data" / "icons" / "*.svg"), "opensees_studio/data/icons")]

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
    # The solver: installed by the user (Options → Solver), never shipped.
    "openseespy",
    "openseespylinux",
    "openseespywin",
    "openseespymac",
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

# Never ship the build host's C++ runtime on Linux. PyInstaller collects
# /usr/lib/x86_64-linux-gnu/libstdc++.so.6 into _internal; the bundle then
# prepends _internal to the loader path and that (older) copy shadows the
# host's. A bundle built on Ubuntu 22.04 carries GLIBCXX_3.4.30, while Mesa's
# libLLVM on Ubuntu 24.04 / Mint 22 needs GLIBCXX_3.4.32: GLX finds no
# FBConfig and the app aborts with "Could not initialize GLX". The host's
# libstdc++ is always at least as new as the one the wheels were built with,
# so the bundle should use it. See packaging/README.md.
if sys.platform.startswith("linux"):
    a.binaries = [
        entry for entry in a.binaries if not Path(entry[0]).name.startswith("libstdc++.so")
    ]

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
    # The roadmap still owes a native .ico; macOS gets its .icns from the
    # BUNDLE below.
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

# On macOS the folder is wrapped in OpenSeesStudio.app, so a double click in
# Finder starts the GUI as an application instead of opening Terminal to run a
# bare executable. COLLECT still writes dist/OpenSeesStudio; the .app is what
# is zipped and shipped. build.py renders the Linux SVG icon into
# build/macos/OpenSeesStudio.icns first (Qt + iconutil); without it the .app
# gets the generic icon.
if sys.platform == "darwin":
    import os

    _icns = ROOT / "build" / "macos" / f"{APP_NAME}.icns"
    _version = os.environ.get("OPENSEES_STUDIO_RELEASE_VERSION", "").strip().removeprefix("v")
    if not _version:
        sys.path.insert(0, str(SRC))
        from opensees_studio import __version__ as _version
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=str(_icns) if _icns.is_file() else None,
        bundle_identifier="io.github.marcel1983.opensees-studio",
        version=_version,
        info_plist={
            "CFBundleDisplayName": "OpenSees Studio",
            "CFBundleName": "OpenSees Studio",
            "CFBundleShortVersionString": _version,
            "CFBundleVersion": _version,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # The openseespymac wheel the user installs from Options > Solver
            # is built for macOS 13 on arm64.
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.developer-tools",
        },
    )
