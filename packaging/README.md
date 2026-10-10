# Packaging the desktop app for end users

This folder turns a source checkout into something a structural engineer can
run without installing Python: a self-contained folder with an
`OpenSeesStudio` executable inside.

```bash
pip install -e ".[gui,packaging]"
python packaging/build.py --gui-smoke --zip
```

| Output | What it is |
| --- | --- |
| `dist/OpenSeesStudio/` | The bundle. Ship the whole folder, not the executable alone. |
| `dist/OpenSeesStudio/OpenSeesStudio` (`.exe` on Windows) | What the user runs. |
| `dist/OpenSeesStudio-linux.zip` (and `-windows` / `-macos`) | The folder zipped for download. |

## Why the build script, and not a one-line PyInstaller call

`build.py` does two things: it runs the spec, and then it **proves the bundle
can solve**. The second part is not ceremony. A frozen bundle can start, show
a window, and still fail at the only thing it exists for, because the GUI
never solves in its own process: it re-runs the executable as the analysis
CLI (`src/opensees_studio/child_cli.py`), and a bundle has no `python -m`. The
smoke test drives exactly that entry point on a bundled example and requires
a result file and a manifest entry back.

`--gui-smoke` adds a second check: it starts the GUI and requires that it is
still running after 20 seconds, which catches a missing Qt plugin or VTK
library. It needs a display; on a headless Linux box wrap it in
`xvfb-run -a`.

## Things that are easy to get wrong

- **Python 3.12.** On Windows the OpenSeesPy wheel ships one `opensees.pyd`
  linked against `python312.dll`. The interpreter inside the bundle must be
  the one that can load it, so build with 3.12 even if your dev venv is
  newer.
- **The `vtk` shim is excluded on purpose.** `vtk.py` re-exports the whole
  VTK namespace. PyVista imports it only inside an `if TYPE_CHECKING:` block,
  which PyInstaller still walks, and no runtime path loads it (verified:
  `import pyvista, opensees_studio.views.main_window` leaves `vtk` out of
  `sys.modules`). PyVista resolves everything through `vtkmodules.*`.
- **`vtkmodules.util` and `vtkmodules.numpy_interface` must stay.** PyVista
  imports both; excluding them fails at startup inside `pyvista/_vtk.py`.
  The GUI smoke test is what caught that.
- **PyVista is built with mypyc, and its plugin is a runtime import.**
  `pyvista/core/dataobject.py` imports `promote_type` from
  `pyvista.typing.mypy_plugin`, which needs a top-level native module whose
  name is a content hash (`6ec57f84c680d3a3778b__mypyc`). Nothing names it and
  the hash changes every PyVista release, so the spec globs `*__mypyc*` from
  site-packages. Without it the app dies at startup with
  `ModuleNotFoundError: No module named '...__mypyc'`.
- **`mypy` is excluded.** The same plugin imports it inside
  `if importlib.util.find_spec('mypy')`, so PyInstaller pulls the whole type
  checker into the bundle. Outside a type check that branch is meant to stay
  off.
- **`console=False`.** The Windows/macOS bundle is a normal windowed app; the
  analysis child is created with `CREATE_NO_WINDOW` so it does not flash a
  console (`viewmodels/analysis_runner.py`).
- **OpenSees has no PyInstaller hook.** `openseespylinux` / `openseespywin`
  ship one ~250 MB extension with BLAS/LAPACK beside it, loaded by name from
  the package `__init__`. The spec collects them explicitly.

## Size

Measured on Linux, x86-64: **1.3 GB unpacked, 569 MB as a zip**. What is in
it:

| Component | Size |
| --- | --- |
| VTK (`vtkmodules`, all 154 modules) | 557 MB |
| OpenSees (`opensees.so` + BLAS/LAPACK) | 254 MB |
| Qt (PySide6) | 131 MB |
| ffmpeg (video export) | 77 MB |
| OpenBLAS (numpy) | 37 MB |
| PyVista's mypyc module | 36 MB |
| everything else | the rest |

### Why VTK is not trimmed

Cutting VTK to the modules the application actually reaches would save
roughly 400 MB, and it was attempted: a list built from PyVista's own
class-lookup tables took the bundle from 154 VTK modules to 70, and the
frozen app then failed at startup on `vtkmodules.vtkFiltersSources`, and
after adding that, on `vtkmodules.vtkRenderingContextOpenGL2` — pulled in by
`f'{_vtk._VTK_ROOT}.vtkRenderingContextOpenGL2'` inside
`pyvista/plotting/_rendering_imports.py`, a name no static analysis can see.

Doing it properly means a runtime check per removed family: open every
dialog, plot every result kind, export a video. That harness does not exist
yet, so the bundle ships the whole namespace and stays correct. Anyone
picking this up should start by writing that check, not by editing
`excludes`.


## Signing and checksums

The archives are published with a `SHA256SUMS.txt` so a download can be
checked:

```bash
sha256sum -c SHA256SUMS.txt          # Linux
shasum -a 256 -c SHA256SUMS.txt      # macOS
certutil -hashfile OpenSeesStudio-windows.zip SHA256   # Windows
```

The binaries themselves are **not signed** unless the repository has signing
secrets configured, which is why the READMEs tell users about the Gatekeeper
and SmartScreen prompts. `desktop.yml` has the signing steps already wired;
they are skipped when the secrets are absent, so a fork still builds working
archives. To turn them on, add:

| Secret | What it is |
| --- | --- |
| `MACOS_CERT_P12` | base64 of the Developer ID Application certificate (`.p12`) |
| `MACOS_CERT_PASSWORD` | its password |
| `MACOS_SIGN_IDENTITY` | e.g. `Developer ID Application: Name (TEAMID)` |
| `MACOS_NOTARY_APPLE_ID` | Apple ID used with `notarytool` |
| `MACOS_NOTARY_TEAM_ID` | team id |
| `MACOS_NOTARY_PASSWORD` | app-specific password for that Apple ID |
| `WINDOWS_CERT_PFX` | base64 of the code-signing certificate (`.pfx`) |
| `WINDOWS_CERT_PASSWORD` | its password |

Two details that are easy to get wrong, and are why `build.py` has
`--zip-only`: signing has to happen on the **unpacked** bundle, so the build
and the archive are separate steps, and on macOS the notary ticket is stapled
afterwards, which means the archive has to be written twice — the second time
so what users download carries the ticket.

**This path has not been exercised against a real certificate**: it is written
from the documented tool invocations and gated so that it cannot break an
unsigned build. Treat the first signed release as the test.

## Cross-platform builds

`.github/workflows/desktop.yml` builds all three platforms on demand, on
tags, and on pull requests that touch this folder; tag builds attach the
archives to the GitHub release. A Windows bundle must be built on Windows
and a macOS one on macOS: PyInstaller cannot cross-compile.
