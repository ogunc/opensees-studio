# Roadmap

OpenSees Studio is built in eight phases. Phases 0–7 ship the core GUI
plus all the post-processing tooling we need for verification work.
Phase 8 layers in the earthquake-engineering primitives that turn the
GUI from "OpenSees frontend" into a usable research tool.

Status legend: ✅ done · 🟡 partial · ⬜ planned · ✂️ deferred / out-of-scope.

## Phase 0 — Scaffolding ✅
- ✅ Repo, license, `.gitignore`, `pyproject.toml`
- ✅ Pre-commit + ruff + mypy
- ✅ GitHub Actions CI (Linux/Mac/Win × Py 3.10–3.12)
- ✅ `python -m opensees_studio` opens a `MainWindow` with PyVista 3D
  viewport, model-tree dock, property dock, console dock, working-plane
  toolbar, and a full menu bar (File / Edit / Define / Assign /
  Analyze / Display / View / Options / Help)
- 🟡 Application icon and About dialog — wordmark logo done; native
  OS icon (`.ico` / `.icns`) still pending

## Phase 1 — Core Data Model ✅
- ✅ `core.geometry`: `Node`, `Element`, `TrussElement`, `CorotTrussElement`,
  `ElasticBeamColumn`, `ForceBeamColumn`, `DispBeamColumn`,
  `ZeroLengthElement`, `ZeroLengthSectionElement`, `BeamWithHingesElement`,
  `QuadElement`, plus `GridSystem` / `CoordinateSystem`
- ✅ `core.materials`: `ElasticIsotropic`, `ElasticUniaxial`, `ElasticPP`,
  `Steel01`, `Steel02`, `Concrete01`, `Concrete02`, `HystereticMaterial`
- ✅ `core.sections`: `ElasticSection`, `FiberSection` with rectangular
  / circular patches and straight rebar layers, `SectionAggregator`
- ✅ `core.loads`: `NodalLoad`, `UniformElementLoad`, `LinearTimeSeries`,
  `ConstantTimeSeries`, `PathTimeSeries`, `PlainLoadPattern`,
  `UniformExcitationPattern`, `ResponseSpectrum`
- ✅ `core.analysis`: `StaticCase`, `ModalCase`, `TransientCase`,
  `PushoverCase`, `ResponseSpectrumCase` — including chained preload
  via `preload_case_ids` and pattern removal for free-vibration runs
- ✅ `core.constraints`: `EqualDOFConstraint` (multi-point constraints)
- ✅ `core.project.Project` aggregator with id allocation, validation,
  `validate_references()`
- ✅ `services.persistence`: `.osmodel` (Pydantic JSON) load/save with
  round-trip-clean assertion in every example script

## Phase 2 — OpenSees Service ✅
- ✅ `services.opensees_runner.OpenSeesRunner` emits commands in the
  canonical order documented in [`architecture.md`](architecture.md)
- ✅ Verified examples (matched analytically or against the OpenSees
  Wiki Tcl reference): cantilever (point + UDL), portal frame, basic
  truss, SDOF pushover, RC frame gravity / pushover / earthquake,
  Examples 1–4 family, two-storey shear / one-bay frames, simply
  supported beam with quad elements
- ✅ `AnalysisWorker(QObject)` runnable inside a `QThread` with
  `progress(int)` / `log(str)` / `finished(ResultsHandle)` signals

## Phase 3 — 3D Viewport ✅
- ✅ `views.canvas3d.ModelCanvas` (subclass of `QtInteractor` from pyvistaqt)
- ✅ Grid plane, world axes triad, view-cube-style preset buttons
  (Isometric / Top XY / Front XZ / Right YZ), parallel projection toggle
- ✅ Node rendering as glyphs; element rendering as tubes (frames /
  trusses) and shells (quads); supports rendered as gizmos
- ✅ Mouse picking → `nodePicked` / `elementPicked` signals; pixel-space
  grid snap (rejects clicks more than 15 px from an intersection)
- ✅ Selection highlighting with in-place colour updates

## Phase 4 — Modeling Tools ✅
- ✅ Grid system dialog (X / Y / Z spacing, generates nodes); SAP2000-style
  table editor; off-grid clicks rejected
- ✅ Working-plane filter — grid + snap restricted to the active level
- ✅ Draw Node / Draw Frame / Draw Truss tools with hover snap highlight
- ✅ Inline element editing from the Properties dock (truss area,
  any scalar field)
- ✅ Assign Support tool (Free / Pin / Roller / Fix + custom 6-DOF dialog)
- ✅ Assign Load: nodal loads, distributed beam loads, ground motions
- ✅ Assign EqualDOF (multi-point constraints) from the UI
- ✅ Show Extruded Sections toolbar shortcut
- ✅ Undo / Redo via `QUndoStack` for every model mutation
- 🟡 Replicate / Mirror / Move / Extrude — basic copy works; story-extrude
  and mirror still pending

## Phase 5 — Properties ✅
- ✅ Material library dialog (CRUD)
- ✅ Section library dialog (incl. `FiberSection` rows that previously
  crashed are now handled)
- ✅ Property editor dock — context-aware, multi-selection assignment,
  inline mass editor
- 🟡 Fiber-section visual editor — exists; some UI polish still needed

## Phase 6 — Analysis Pipeline ✅
- ✅ Analysis case manager dialog with case-type factories
- ✅ Run dialog with progress + log + cancel
- ✅ Per-run Rayleigh damping override (no project mutation)
- ✅ Results stored to `<project>.osresults.h5`
- 🟡 Convergence diagnostics view (residuals per step) — partial info
  in run log; dedicated diagnostics dock pending

## Phase 7 — Post-processing ✅
- ✅ Deformed shape with scale-factor slider
- ✅ Mode-shape animator (1-indexed; play / scrub / scale)
- ✅ Element force diagrams (axial, shear, moment) with auto-pick of
  the largest-magnitude component on dock open, numerical labels at
  global min/max ends
- ✅ Time-history plotter (pyqtgraph) with displacement / velocity /
  acceleration switching
- ✅ Hysteresis plotter — node DOF orbits and element local-force loops
- ✅ Pushover curve view in display units
- ✅ Response-spectrum view (Sa-T curve with modal-period markers and a
  mass-participation table)
- ✅ Snapshot / video export (mode shapes + time histories) via
  `imageio[ffmpeg]`
- ⬜ **Render performance pass** — collapse per-entity actors into glyphed
  PolyData (single draw call), in-place colour updates for selection,
  AA, lower-tessellation spheres. Target: 10k nodes / 20k frames @ 30 fps

## Phase 8 — Earthquake Engineering 🟡
- ✅ `HystereticMaterial`, `BeamWithHinges`, `FiberSection` → all
  flowing into the runner, end-to-end pushover example
- ✅ Response spectrum generator + SRSS / CQC modal combination
- ✅ Ground-motion import via `PathTimeSeries` + `UniformExcitationPattern`,
  with an example wired up against the OpenSees A10000 record
- ✅ `ZeroLengthSectionElement` for moment-curvature workflows; closed-form
  verification example shipped
- ⬜ Seismic isolators: `elastomericBearing*`, `frictionPendulumBearing`,
  `singleFPBearing`, `TripleFrictionPendulum`
- ⬜ Ground-motion library (PEER-style record set + scaling tools)
- ⬜ IDA (Incremental Dynamic Analysis) batch runner
- 🟡 Fiber-section editor — exists for rectangular / circular sections;
  confined / unconfined visual presets pending

## Out-of-scope (for now)
- ✂️ Code-checking (TBDY-2018, ASCE 41, Eurocode 8)
- ✂️ Soil-structure interaction GUI
- ✂️ Cloud / collaborative editing
- ✂️ Native shell-element rendering / pre-processing (quads exist as a
  primitive, but a proper shell workflow is its own phase)
