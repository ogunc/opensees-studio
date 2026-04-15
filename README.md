# OpenSees Studio

A modern, SAP2000-style desktop GUI for [OpenSeesPy](https://openseespydoc.readthedocs.io/),
built for structural and earthquake engineers who want a visual modeling environment
without leaving the OpenSees ecosystem.

> **Status:** Pre-alpha. Active development. APIs will change.

## Goals

- Graphical pre-processing: nodes, frame/shell elements, supports, loads, masses
- Property assignment for nonlinear materials, fiber sections, seismic isolators, plastic hinges
- Full analysis pipeline: static, modal, nonlinear pushover, nonlinear time-history
- Interactive post-processing: deformed shape, mode shapes, force diagrams, hysteresis, time-history plots
- Reproducible: every visual model is round-trip serializable to a versionable JSON project file
- Scriptable: same core model usable from a Python REPL or Jupyter

## Tech stack

| Layer | Library |
|---|---|
| GUI | PySide6 (Qt 6) |
| 3D viewport | PyVista + pyvistaqt (VTK) |
| 2D plots | pyqtgraph |
| Solver | OpenSeesPy |
| Numerics | NumPy, SciPy, pandas |
| Results storage | HDF5 (h5py) |
| Tests | pytest, pytest-qt |
| Lint/format/type | ruff, mypy |

## Architecture

Strict MVVM with a service layer. The `core` package is pure Python — no Qt, no
OpenSeesPy imports — and is fully unit-testable in isolation. See
[`docs/architecture.md`](docs/architecture.md).

```
views (Qt)  →  viewmodels  →  services (OpenSeesRunner, Persistence)  →  core (model)
```

## Install (development)

```bash
git clone https://github.com/ogunc/opensees-studio.git
cd opensees-studio
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```bash
python -m opensees_studio
```

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md).

## License

MIT — see [`LICENSE`](LICENSE).
