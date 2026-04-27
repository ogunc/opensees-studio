# CLAUDE.md — Project context for Claude Code

## Project: OpenSees Studio

A SAP2000-style desktop GUI for OpenSeesPy. PySide6 + PyVista + pyqtgraph.

## Architecture

- **Pattern**: MVVM + service layer
- **Views** (Qt): `src/opensees_studio/views/` — NO direct OpenSeesPy calls
- **ViewModels**: `src/opensees_studio/viewmodels/` — ProjectViewModel, AnalysisRunner
- **Services**: `src/opensees_studio/services/` — OpenSeesRunner, persistence, deformation, spectrum, section_properties, animation_export
- **Core** (pure Python, NO Qt, NO openseespy): `src/opensees_studio/core/` — Pydantic models for Project, Node, Element, Material, Section, Load, Analysis
- **Commands**: `src/opensees_studio/commands/` — QUndoCommand subclasses for every model mutation

## Tech Stack

- Python 3.11+, PySide6 (Qt 6), PyVista/VTK, pyqtgraph, OpenSeesPy 3.5.1.12, Pydantic v2, h5py, imageio[ffmpeg]
- Windows DLL fix: `openseespy==3.5.1.12`, `openseespywin==3.5.1.12`

## Key Conventions

- `ForceComponent` is plain `Enum`, NOT `str`-Enum (breaks `.value` in PyVista)
- `QObject.receivers()` in PySide6 takes SIGNAL string, not SignalInstance — avoid it
- Qt event positions are LOGICAL pixels; VTK is DEVICE pixels → scale by `devicePixelRatioF()`
- `ModalResults.mode_shapes` is **1-indexed** dict
- `PathTimeSeries` field is `dt` (not `time_step`)
- `DiagramRenderer` must bail when `abs_max == 0`
- End-j sign flipped in `extract_diagram_data` for continuous diagram display
- Entity.id is PositiveInt (>0) — use sentinel 999999 for temporary objects

## Running

```bash
# Activate venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Run the app
python -m opensees_studio

# Run tests
pytest tests/unit -v
pytest tests/gui -v

# Regenerate example models
python examples/cantilever.py
python examples/portal_frame.py
python examples/space_frame_3d.py
python examples/sdof_pushover.py
python examples/portal_pushover.py
python examples/ex1a_canti2d.py
python examples/ex1b_portal2d.py
python examples/ex2a_canti2d_elastic_element.py
python examples/ex2b_canti2d_inelastic_section.py
python examples/ex2c_canti2d_inelastic_fiber_section.py
python examples/ex3_canti2d_elastic_element.py
python examples/ex3_canti2d_inelastic_section.py
python examples/ex3_canti2d_inelastic_fiber_section.py
python examples/ex1a_canti2d_eq.py
python examples/eigen_two_storey_shear_frame.py
python examples/eigen_two_storey_one_bay_frame.py
```

## Test Structure

- `tests/unit/` — no Qt, no OpenSeesPy (pure logic)
- `tests/gui/` — qtbot fixture, `@pytest.mark.gui`
- `tests/integration/` — real OpenSeesPy runs

## Current Status

- General transient workflow now supports preload chaining, removable patterns, and mode-1 Rayleigh damping from the GUI.
- Define workflow now includes explicit dialogs for `LinearTimeSeries` and `PlainLoadPattern`.
- Display workflow now includes `Display Options`, node labels, element labels, and manual `equalDOF` assignment from the UI.
- Example coverage was expanded substantially. Added or updated examples include:
  - `ex1a_canti2d_eq`
  - `ex1a_canti2d`
  - `ex1b_portal2d`
  - `ex2a_canti2d_elastic_element`
  - `ex2b_canti2d_inelastic_section`
  - `ex2c_canti2d_inelastic_fiber_section`
  - `ex3_canti2d_elastic_element`
  - `ex3_canti2d_inelastic_section`
  - `ex3_canti2d_inelastic_fiber_section`
  - `eigen_two_storey_shear_frame`
  - `eigen_two_storey_one_bay_frame`
- New reference Tcl/data files for those examples live under `examples/data/`.
- Integration coverage was expanded around those examples plus the generalized runner behavior.

## Immediate Next Step

- Next planned work is manual GUI walkthrough validation of the new OpenSees tutorial examples.
- Treat Example 3 as three separate build variants sharing the same analysis concepts:
  - elastic element
  - aggregated uniaxial inelastic section
  - fiber section
- For `Ex2c`, the source Tcl files were inconsistent (`numBarsCol` differed between push and EQ files). The repo currently uses one consistent section definition based on the pushover-side geometry so the project model stays coherent.

## Known Issues to Fix

- Fiber Section Editor: some UI polish needed
- VTK framebuffer warnings on Windows are cosmetic (ignore them)
- Linux test env segfault during gui test cleanup is cosmetic

## Branch Strategy

- `develop` — active development
- `main` — stable releases
- Conventional commits format
