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

The dependency direction is strict and one-way: `views → viewmodels →
services → core`. CI does not enforce this with import-linter yet, but
PRs that violate it will be rejected on review.

## Tech stack

- Python 3.10+ (Windows: **3.12+** — the `openseespywin==3.8.0.0` wheel has no
  3.11 build), PySide6 (Qt 6), PyVista/VTK, pyqtgraph, OpenSeesPy 3.8.0.0,
  Pydantic v2, h5py, imageio[ffmpeg].
- Windows DLL fix: pin `openseespy==3.8.0.0` *and* `openseespywin==3.8.0.0`.

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
- `Entity.id` is `PositiveInt` (>0). The sentinel `999999` is reserved
  for in-flight / temporary objects that haven't been assigned a real id.

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
- `tests/gui/` — `qtbot` fixture, `@pytest.mark.gui`.
- `tests/integration/` — real `openseespy` runs that exercise full
  model → solve → results pipelines on the bundled examples.

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
