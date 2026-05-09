# OpenSees Studio

> A modern, SAP2000-style desktop GUI for [OpenSeesPy](https://openseespydoc.readthedocs.io/) —
> built for structural and earthquake engineers who want a visual modeling environment
> without leaving the OpenSees ecosystem.

**Status:** Pre-alpha. Active development. APIs and file formats will change.

## Why

OpenSees is the gold-standard nonlinear FEM solver for earthquake engineering,
but its native interface is Tcl/Python scripts. OpenSees Studio adds a visual
front-end so you can:

- Click to draw nodes, frames, supports, and loads.
- Assign materials, sections, and load patterns through dialogs.
- Run static, modal, pushover, and time-history analyses with progress + cancel.
- Inspect results visually — deformed shape, mode shapes, force diagrams,
  pushover curves, time-history plots.
- Save the model as a single `.osmodel` JSON file that round-trips cleanly
  (diff-able in Git, scriptable from Python).

Behind the GUI, the same `core` Pydantic model is fully usable from a script
or notebook — the GUI is one frontend, not the only one.

## What works today

- **Modeling** — grids, nodes, frames (elastic + force-based), trusses, quads,
  zero-length sections, restraints, equalDOF constraints, distributed loads,
  ground motions (PathTimeSeries / UniformExcitation).
- **Materials and sections** — `Steel01`, `Steel02`, `Concrete01`, `Concrete02`,
  `ElasticPP`, `Hysteretic`, fiber sections (rectangular / circular patches +
  rebar layers), `SectionAggregator`, `BeamWithHinges`.
- **Analyses** — static (load- or displacement-controlled), modal,
  displacement-controlled pushover, transient time-history with mode-1
  Rayleigh damping. Chained workflows: gravity preload →
  `loadConst -time 0.0` → pushover or transient.
- **Post-processing** — deformed shape (with scale slider), animated mode
  shapes, axial / shear / moment diagrams, pushover curves (in display
  units), time-history plots, hysteresis loops, response-spectrum SRSS/CQC,
  snapshot + video export.
- **Persistence** — projects save as a single JSON `.osmodel` file (Pydantic-validated).
- **Examples** — 20+ verified examples bundled, including the OpenSees wiki
  Examples-1 through Example-4 family and a fiber-section RC frame pushover.
  See [`examples/README.md`](examples/README.md).

## Tech stack

| Layer        | Library                          |
| ------------ | -------------------------------- |
| GUI          | PySide6 (Qt 6)                   |
| 3D viewport  | PyVista + pyvistaqt (VTK)        |
| 2D plots     | pyqtgraph                        |
| Solver       | OpenSeesPy 3.5.1.12              |
| Numerics     | NumPy, SciPy, pandas             |
| Storage      | Pydantic v2 (model), HDF5 (results) |
| Tests        | pytest, pytest-qt                |
| Lint / type  | ruff, mypy                       |

## Architecture

Strict MVVM + service layer. The `core` package is pure Python — no Qt, no
OpenSeesPy imports — and is fully unit-testable in isolation.

```
views (Qt)  →  viewmodels  →  services (OpenSeesRunner, Persistence)  →  core (model)
```

See [`docs/architecture.md`](docs/architecture.md) for the long form,
including the canonical OpenSeesPy command sequence the runner emits.

## Install (development)

```bash
git clone https://github.com/ogunc/opensees-studio.git
cd opensees-studio

python -m venv .venv
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # Linux / macOS

pip install -e ".[dev]"
```

Python 3.10+ is required; 3.11 is recommended. On Windows, pin both
`openseespy==3.5.1.12` and `openseespywin==3.5.1.12` (already pinned in
`pyproject.toml`).

## Quick start — the 60-second tour

```bash
python -m opensees_studio
```

Then:

1. **File → Open** → pick `examples/cantilever.osmodel`.
2. **Analyze → Cases** → run `Tip-Load`.
3. **Display → Show Force Diagram** → component **M3** → linear moment
   peaking at 50 kN·m at the fixed end. Component **V2** → constant -10 kN.
4. **Display → Show Deformed Shape** → the classic cantilever curve.

For a nonlinear walkthrough, open `examples/portal_pushover.osmodel`,
run the `Push-X` case, then **Display → Show Pushover Curve** — you'll
see the elastic ramp followed by a yield plateau as the fiber-section
hinges form at the column bases.

## Run the test suite

```bash
pytest tests/unit          # pure-logic tests, milliseconds
pytest tests/gui           # Qt event-loop tests (pytest-qt)
pytest tests/integration   # real OpenSeesPy runs on bundled examples
```

CI runs lint + the non-`slow` subset on Linux / macOS / Windows × Python
3.10 / 3.11 / 3.12.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md). Short version: more
earthquake-engineering primitives (isolators, ground-motion library,
IDA), a fiber-section visual editor, and a results-comparison view
across runs.

## Contributing

PRs welcome — but please read [`CONTRIBUTING.md`](CONTRIBUTING.md) first.
The architectural rules in there (e.g. *"`core/` may not import Qt or
openseespy"*) are enforced in review.

## License

[MIT](LICENSE) © Ozan
