# Roadmap

## Phase 0 — Scaffolding ✅ (in progress)
- [x] Repo, license, `.gitignore`, `pyproject.toml`
- [x] Pre-commit + ruff + mypy
- [x] GitHub Actions CI (Linux/Mac/Win × Py 3.10–3.12)
- [ ] `python -m opensees_studio` opens an empty `MainWindow` with a `pyvistaqt` viewport, a model-tree dock, a property-editor dock, and a Python console dock
- [ ] Application icon, About dialog, basic menu bar (File/Edit/View/Define/Assign/Analyze/Display/Help)

## Phase 1 — Core Data Model
- [ ] `core.geometry`: `Node`, `Element` (abstract), `FrameElement`, `TrussElement`, `ShellElement`
- [ ] `core.materials`: `ElasticIsotropic`, `Steel01`, `Steel02`, `Concrete01`, `Concrete02`, `ElasticPP`
- [ ] `core.sections`: `ElasticSection`, `FiberSection` (with `FiberPatch`)
- [ ] `core.loads`: `NodalLoad`, `DistributedLoad`, `GroundMotion`
- [ ] `core.analysis`: `StaticCase`, `ModalCase`, `TransientCase`
- [ ] `core.project.Project` aggregator with id-allocation, validation, signals
- [ ] `services.persistence`: load/save `.osmodel` (Pydantic JSON)
- [ ] Unit tests ≥ 90 % coverage on `core/`

## Phase 2 — OpenSees Service
- [ ] `services.opensees_runner.OpenSeesRunner.build(project)` — emits commands in canonical order
- [ ] Verified examples (matched analytically or against reference scripts):
  - cantilever beam (linear static)
  - portal frame (modal)
  - 2D truss (linear static)
  - SDOF time-history vs known response
- [ ] `AnalysisWorker(QObject)` runnable in a `QThread`

## Phase 3 — 3D Viewport
- [ ] `views.canvas3d.ModelCanvas` (subclass of `QtInteractor` from pyvistaqt)
- [ ] Grid plane, world axes triad, view-cube
- [ ] Node rendering as glyphs; element rendering as tubes (frames) / triangles (shells)
- [ ] Mouse picking → emits `nodePicked(node_id)` / `elementPicked(elem_id)`
- [ ] Selection highlighting

## Phase 4 — Modeling Tools
- [ ] Grid system dialog (X/Y/Z spacing, generate nodes)
- [ ] Draw Frame tool (click-click between nodes, with snapping)
- [ ] Assign Support tool (Free/Pin/Roller/Fix + custom 6-DOF dialog)
- [ ] Assign Load tool
- [ ] Replicate / Mirror / Move / Extrude (story copy)
- [ ] Undo/Redo via `QUndoStack`

## Phase 5 — Properties
- [ ] Material library dialog (CRUD)
- [ ] Section library dialog with fiber section visual editor
- [ ] Property editor dock — context-aware, multi-selection assignment

## Phase 6 — Analysis Pipeline
- [ ] Analysis case manager dialog
- [ ] Run dialog with progress + log + cancel
- [ ] Results stored to `<project>.osresults.h5`
- [ ] Convergence diagnostics view (residuals per step)

## Phase 7 — Post-processing
- [ ] Deformed shape with scale-factor slider
- [ ] Mode-shape animator
- [ ] Element force diagrams (axial, shear, moment)
- [ ] Time-history plotter (pyqtgraph)
- [ ] Hysteresis plotter
- [ ] Snapshot / video export

## Phase 8 — Earthquake Engineering
- [ ] Seismic isolators: `elastomericBearing*`, `frictionPendulumBearing`, `singleFPBearing`, `TripleFrictionPendulum`
- [ ] Plastic hinges: `BeamWithHinges`, lumped-plasticity zero-length
- [ ] Fiber section editor with confined/unconfined concrete
- [ ] Ground motion library + scaling tools
- [ ] Response spectrum generator
- [ ] IDA (Incremental Dynamic Analysis) batch runner

## Out-of-scope (for now)
- Code-checking (TBDY-2018, ASCE 41, Eurocode 8)
- Soil-structure interaction GUI
- Cloud / collaborative editing
