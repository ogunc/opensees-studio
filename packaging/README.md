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
| `dist/OpenSeesStudio-x86_64.AppImage` | Linux only, with `--appimage-tool`: the same folder as one runnable file. |

On a tag build `desktop.yml` sets `OPENSEES_STUDIO_RELEASE_VERSION` to the tag,
and every file name carries the version without its `v`:
`OpenSeesStudio-0.0.65-linux.zip`, `OpenSeesStudio-0.0.65-windows.zip`,
`OpenSeesStudio-0.0.65-macos.zip`, `OpenSeesStudio-0.0.65-x86_64.AppImage`.
Pull request and manual runs keep the unversioned names above.

## The Linux AppImage

The AppImage is the Linux bundle unchanged, wrapped in an AppDir
(`build/OpenSeesStudio.AppDir`): the PyInstaller folder under
`usr/lib/OpenSeesStudio`, plus `AppRun`, `opensees-studio.desktop` and the
icon from `packaging/linux/`. It is built from an existing `dist/OpenSeesStudio`
and then smoke-tested as a file, the way a user runs it:

```bash
python packaging/build.py --appimage-tool ./appimagetool --appimage-runtime ./runtime-x86_64
xvfb-run -a python packaging/build.py --gui-smoke --smoke-exe dist/OpenSeesStudio-x86_64.AppImage
```

- **Pinned tools.** `desktop.yml` downloads `appimagetool` 1.9.1 and the
  type 2 runtime `20251108` and checks both SHA256 digests. The runtime is
  passed with `--runtime-file`; otherwise appimagetool fetches the newest
  continuous build. `appimagetool` runs with `APPIMAGE_EXTRACT_AND_RUN=1`, so
  the build host needs no FUSE.
- **The static runtime needs `fusermount`, not `libfuse2`.** Ubuntu 22.04
  dropped `libfuse2` from the default install, which broke AppImages built
  with the old runtime; the type 2 runtime links FUSE statically and only
  calls `fusermount`/`fusermount3` (package `fuse3`). The smoke test mounts
  the AppImage for real, which is why the CI job installs `fuse3`.
- **The mounted image is read-only.** Nothing may be written next to the
  executable: OpenSeesPy from Options → Solver goes to
  `<app data>/engines` (`~/.local/share/opensees-studio/engines`), and
  `solver.json` to the same per-user folder. The CLI smoke test on the
  mounted AppImage is what proves it.
- **The child CLI runs the inner executable.** `sys.executable` inside the
  AppImage is `/tmp/.mount_*/usr/lib/OpenSeesStudio/OpenSeesStudio`, so an
  analysis child re-enters the bundle directly rather than through `AppRun`;
  it works because the mount lives as long as the GUI does.

## Why the build script, and not a one-line PyInstaller call

`build.py` does two things: it runs the spec, and then it **proves the bundle
can solve**. The second part is not ceremony. A frozen bundle can start, show
a window, and still fail at the only thing it exists for, because the GUI
never solves in its own process: it re-runs the executable as the analysis
CLI (`src/opensees_studio/child_cli.py`), and a bundle has no `python -m`. The
smoke test drives exactly that entry point on a bundled example and requires
a result file and a manifest entry back.

**The bundle does not carry OpenSeesPy** (`docs/adr/ADR-0003-solver-engines.md`):
it has its own license, and the user installs it from Options → Solver, which
downloads the pinned PyPI wheels into the application data folder. So the smoke
test checks both halves: without a solver the frozen CLI must exit 2 with the
message that points to Options → Solver, and after installing OpenSeesPy with
the application's own installer (`services/engine_install.py`) into a temporary
folder it must solve. That download needs network; `--engine-dir PATH` reuses
a folder that already holds OpenSeesPy.

`--gui-smoke` adds a second check: it starts the GUI and requires that it is
still running after 20 seconds, which catches a missing Qt plugin or VTK
library. It needs a display; on a headless Linux box wrap it in
`xvfb-run -a`.

## Things that are easy to get wrong

- **Build Linux on the oldest supported base.** The bundle carries its own
  Python, Qt and VTK but not glibc: it uses the system's, and it needs one at
  least as new as the newest `GLIBC_x.y` its binaries ask for, which is the
  glibc of the machine that built it. Built on Ubuntu 24.04 (glibc 2.39), it
  refused to start on Linux Mint 21 (glibc 2.35). `desktop.yml` builds on
  `ubuntu-22.04`, and `tools/glibc_floor.py dist/OpenSeesStudio --max 2.35`
  fails the build when any file asks for more. Supported: Ubuntu 22.04 and
  later, Linux Mint 21 and later, Debian 12, LMDE 6.
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
- **OpenSeesPy is excluded, not just uncollected.** PyInstaller follows the lazy
  `import openseespy` inside the runner, and a developer's environment has it,
  so the spec lists `openseespy*` in `excludes`. The frozen interpreter loads
  it at run time from the folder appended to `sys.path`
  (`OPENSEES_STUDIO_ENGINE_PATH`), which is what the smoke test proves.

## Size

Measured on Linux, x86-64, *with* OpenSeesPy (before it left the bundle):
**1.3 GB unpacked, 569 MB as a zip**. Without it the bundle is about 250 MB
lighter unpacked; the user downloads OpenSeesPy separately (86 MB on Linux,
7 MB on Windows, 10 MB on macOS arm64). What was in it:

| Component | Size |
| --- | --- |
| VTK (`vtkmodules`, all 154 modules) | 557 MB |
| OpenSees (`opensees.so` + BLAS/LAPACK) — no longer bundled | 254 MB |
| Qt (PySide6) | 131 MB |
| ffmpeg (video export) | 77 MB |
| OpenBLAS (numpy) | 37 MB |
| PyVista's mypyc module | 36 MB |
| scipy, for the bundled PyNite engine (added in 0.0.22) | ~140 MB |
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

The archives and the AppImage are published with a `SHA256SUMS.txt` so a
download can be checked:

```bash
sha256sum -c SHA256SUMS.txt          # Linux
shasum -a 256 -c SHA256SUMS.txt      # macOS
certutil -hashfile OpenSeesStudio-0.0.65-windows.zip SHA256   # Windows
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

The `publish` job needs the Linux archive, the Linux AppImage and the Windows
archive, and publishes without
the macOS one when its job failed or found no hosted runner (it says so in the
release notes). "Re-run failed jobs" on that run later builds macOS and re-runs
`publish`, which adds the archive to the same release and rewrites
`SHA256SUMS.txt`.
