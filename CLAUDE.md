# CLAUDE.md — Project context for Claude Code

This file is loaded automatically by Claude Code (and other AI coding
assistants) when working in this repo. It captures the architectural
rules, conventions, and gotchas that aren't obvious from reading the
code. Keep it short — link out instead of duplicating.

## Project: OpenSees Studio

A SAP2000-style desktop GUI for OpenSeesPy. PySide6 + PyVista + pyqtgraph.

See [`README.md`](README.md) for the user-facing overview and
[`docs/architecture.md`](docs/architecture.md) for the long form
architecture document.

## Architecture

- **Pattern**: MVVM + service layer.
- **`core/`** — pure Python, no Qt, no openseespy. Pydantic v2 models for
  `Project`, `Node`, `Element`, `Material`, `Section`, `Load`, `Analysis`.
  Safe to import from a script, notebook, or future CLI.
- **`services/`** — `OpenSeesRunner`, persistence, deformation, spectrum,
  section_properties, animation_export. May import openseespy. No Qt.
- **`viewmodels/`** — Qt-aware adapters. `ProjectViewModel`,
  `AnalysisRunner`, `QUndoStack`.
- **`views/`** — Qt widgets, dialogs, 3D canvas. Never imports
  openseespy directly — go through a service.
- **`commands/`** — `QUndoCommand` subclasses for every model mutation.
- **Analysis execution** runs in a child process. `AnalysisRunner`
  (viewmodels) first writes the pre-run snapshot
  `<stem>.run-snapshot.osmodel` next to the project file (for a never-saved
  project `untitled.run-snapshot.osmodel` in the app data directory,
  override with `OPENSEES_STUDIO_DATA_DIR`), then starts
  `python -m opensees_studio.run --project <snapshot> --cases <id> --out <dir>`
  with `QProcess` (`sys.executable`). The CLI (`opensees_studio/run.py`) prints
  one JSON object per stdout line (`log`, `progress`, `case_started`,
  `case_finished`, `error`), flushed per line; fd 1 is redirected to stderr
  first, so OpenSees native output never touches the protocol. Exit codes:
  0 every case ran (an early stop is a result), 2 Python-side analysis
  error with an `error` line, 3 invalid project or reference; anything else
  means the child died. Results travel through `services/result_store.py`
  (float64 HDF5 plus `manifest.json`, lossless) and are rebuilt with
  `load_results`. The snapshot doubles as crash recovery: on open, a
  snapshot newer than the file prompts to restore or discard; a normal save
  or close removes it. `OPENSEES_STUDIO_IN_PROCESS=1` runs the previous
  threaded in-process worker (debugging, no cancel).
  `OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=N` is a test-only hook that makes the
  CLI hard-exit with 255 after N progress lines. The Material Tester still
  calls OpenSees in the GUI process.

The dependency direction is strict and one-way: `views → viewmodels →
services → core`. CI does not enforce this with import-linter yet, but
PRs that violate it will be rejected on review.

## Tech stack

- **Python 3.12** (`requires-python = ">=3.12"`), PySide6 (Qt 6), PyVista/VTK,
  pyqtgraph, OpenSeesPy 3.8.0.0, Pydantic v2, h5py, imageio[ffmpeg].
- Why 3.12: the `openseespywin` and `openseespylinux` 3.8.0.0 wheels both
  declare `Requires-Python >=3.12`. On Windows the wheel ships a single
  `opensees.pyd` linked against `python312.dll`, so use 3.12 exactly (3.13
  cannot load it, even though pip will install it).
- Windows DLL fix: pin `openseespy==3.8.0.0` *and* `openseespywin==3.8.0.0`.

### Venv layout (Windows dev machine, as of 2026-09-18)

- `.venv/`: the live environment. Python 3.12.10, OpenSeesPy 3.8.0.0,
  created with `py -3.12 -m venv .venv` then `pip install -e ".[gui,dev]"`.
- `.venv/` is the only interpreter inside the repo. The py311 rollback
  environment (`.venv-old-py311/`) and the stale Python 3.9.1 `venv/` were
  deleted on 2026-09-18 once the lock file below was recorded.

### Reproducing the known-good environment

`requirements-lock.txt` is a `pip freeze --exclude-editable` of the live
`.venv` (Python 3.12.10 + OpenSeesPy 3.8.0.0), recorded after unit 299,
integration 55 and GUI 181 passed on it. It is a record, not a constraint
file: `pyproject.toml` stays the source of truth for dependency ranges. To
rebuild that exact state: `py -3.12 -m venv .venv`, then
`pip install -r requirements-lock.txt`, then `pip install -e . --no-deps`.
Regenerate the file only after all three suites pass on a changed environment.

## Conventions and gotchas

These are non-obvious things that are easy to break if you don't know:

- `ForceComponent` is a plain `Enum`, **not** a `str`-Enum — a `str`
  mix-in breaks `.value` lookup inside PyVista renderers.
- `QObject.receivers()` in PySide6 takes a SIGNAL string, not a
  `SignalInstance` — avoid it.
- Qt mouse-event positions are LOGICAL pixels; VTK is DEVICE pixels.
  Scale by `widget.devicePixelRatioF()` when picking.
- `ModalResults.mode_shapes` is **1-indexed** (mode 1 → key `1`).
- `PathTimeSeries` field is `dt`, not `time_step`.
- `DiagramRenderer` must early-return when `abs_max == 0` — avoid
  divide-by-zero in the colour scale.
- The end-`j` sign is flipped in `extract_diagram_data` so axial /
  shear / moment diagrams are continuous across an element.
- `ProjectCommand` holds its view model by weak reference. Never store a
  strong reference to the view model (or anything owning its `QUndoStack`)
  on a command: the cycle through the stack corrupts the heap when the GC
  frees many of them (`0xC0000374`).
- `Entity.id` is `PositiveInt` (>0). The sentinel `999999` is reserved
  for in-flight / temporary objects that haven't been assigned a real id.
- ARPACK keeps its random start vector across `ops.eigen` calls, so only
  the first eigen call of a process is reproducible: a second call flips
  mode signs, rotates a repeated eigenvalue pair and moves the SRSS
  combination with it. The child-process runner is always that first
  call; in-process mode is not.

## Dependency split

`pyproject.toml` separates dependencies into two tiers:

- **Base** (`pip install -e .`): `pydantic`, `numpy`, `h5py`, `openseespy`.
  Safe to use headlessly — no Qt, no PyVista, no VTK. Scripts, notebooks,
  and web backends (e.g. opensees-studio-web) install only this tier.
- **GUI extra** (`pip install -e ".[gui]"`): adds PySide6, pyvista, pyvistaqt,
  vtk, pyqtgraph, imageio. Required to launch the desktop app.

Desktop dev: `pip install -e ".[gui,dev]"`.
Web / headless: `pip install -e .` (then verify with
`python -c "import sys, opensees_studio.core; assert 'PySide6' not in sys.modules"`).

See `docs/adr/ADR-0002-headless-gui-dep-split.md` for the rationale.

## Running

```bash
# Activate the venv
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # Linux/macOS

# Launch the app
python -m opensees_studio

# Run tests
pytest tests/unit -v           # pure-logic, no Qt, no openseespy
pytest tests/gui -v            # pytest-qt, real Qt event loop
pytest tests/integration -v    # real openseespy runs (slow)
```

## Test structure

- `tests/unit/` — pure logic, instant. No Qt, no openseespy.
  It runs without any `QT_QPA_PLATFORM` setting; a test that needs `qtbot`
  (and with it a QApplication) belongs in `tests/gui/`.
- `tests/gui/` — `qtbot` fixture, `@pytest.mark.gui`.
  Run it one process per test file (227 tests in 41 files as of
  2026-09-24, about 105 s):
  `Get-ChildItem tests\gui\test_*.py | ForEach-Object { python -m pytest $_.FullName }`.
  A single `pytest tests/gui` process segfaults around test 73 because VTK
  render windows accumulate (see `reports/STATUS_2026-09-12.md`). Check the
  exit code of every process, not only the pass count: every file exits 0
  since 2026-09-23, so any non-zero code (for example `0xC0000374` after all
  tests pass) is a new teardown bug. `tests/gui/conftest.py` closes plotters
  and top-level widgets at session end.
- `tests/integration/` — real `openseespy` runs that exercise full
  model → solve → results pipelines on the bundled examples, including the
  analysis CLI as a subprocess (`test_analysis_cli.py`) and the
  direct-versus-CLI result parity (`test_cli_result_parity.py`).

## Examples

The `examples/` directory contains both Python scripts and
pre-generated `.osmodel` files. Each script builds the project, saves
it, reloads, and round-trips for sanity. See [`examples/README.md`](examples/README.md)
for the full catalogue.

To regenerate every example after changing the data model:

```bash
for f in examples/*.py; do python "$f"; done
```

## Branch strategy

- `develop` — active development.
- `main` — released versions.
- Conventional commit style: `feat:`, `fix:`, `refactor:`, `docs:`,
  `test:`, `chore:`, `ci:`.
