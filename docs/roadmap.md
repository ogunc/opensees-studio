# Roadmap

OpenSees Studio is built in eight phases. Phases 0–7 ship the core GUI
plus all the post-processing tooling we need for verification work.
Phase 8 layers in the earthquake-engineering primitives that turn the
GUI from "OpenSees frontend" into a usable research tool.

Status legend: ✅ done · 🟡 partial · ⬜ planned · ✂️ deferred / out-of-scope.

## Phase 0 — Scaffolding ✅
- ✅ Repo, license, `.gitignore`, `pyproject.toml`
- ✅ Pre-commit + ruff + mypy
- ✅ GitHub Actions CI (Linux/Mac/Win × Py 3.12)
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
- ✅ `Concrete04` (Popovics) end-to-end: model → runner → UI form → tests →
  fiber-section cantilever example
- ✅ **Material Tester service** (`services/material_tester.py`) — headless,
  Qt-free; runs any uniaxial material through a monotonic or cyclic strain
  protocol in an isolated single-element model and returns the full
  stress–strain history.  Verified: Elastic linearity, ElasticPP plateau,
  Steel01 hysteresis energy (EPP formula, <1%), Concrete04 Popovics C1
  continuity; state-cleanup and interleave proofs.
- ✅ Python 3.12 venv migration, OpenSeesPy 3.8.0.0 live (2026-09-18).
  First run against the pin: unit 299/299, integration 53/55.
- ✅ Integration triage (2026-09-18): the 2 failures were a test-model error in
  `tests/integration/test_concrete04_runner.py`, not a solver regression. The
  base restraint `(True, True, True, False, False, False)` left rz free in 2D,
  so the "cantilever" was a mechanism that OpenSees 3.5.1 factorized by
  round-off luck and 3.8.0 rejects as singular. Fixed to the 2D fixed-base form
  `(True, True, False, False, False, True)` in the test and in
  `examples/concrete04_cantilever.py` (model regenerated). Integration 55/55.
  CI, ruff and mypy now target 3.12 only.
- ✅ Dependency lock file (2026-09-18): `requirements-lock.txt` recorded from
  `pip freeze --exclude-editable` on Python 3.12.10 + OpenSeesPy 3.8.0.0 after
  unit 299, integration 55 and GUI 181/181 (three per-file sweeps). Ruling: the
  interpreter-exit crash `0xC0000374` (2 of 117 GUI test processes, after all
  their tests had passed) is deterministic on the old py311 venv, so it predates
  the migration and does not block the lock. It is tracked under Maintenance
  below. The rollback venv `.venv-old-py311` and the stale `venv/` were deleted.
- ⬜ **Material Tester dialog** — Qt front-end for the service above; live
  stress–strain plot with strain-amplitude and step controls
- ⬜ Seismic isolators: `elastomericBearing*`, `frictionPendulumBearing`,
  `singleFPBearing`, `TripleFrictionPendulum`
- ⬜ Ground-motion library (PEER-style record set + scaling tools)
- ⬜ IDA (Incremental Dynamic Analysis) batch runner
- 🟡 Fiber-section editor — exists for rectangular / circular sections;
  confined / unconfined visual presets pending

## Backlog (post Phase 8)
- ⬜ Pre-analysis model validation: detect under-restrained or mechanism 2D/3D
  models before `ops.analyze`

## Maintenance / debt
- ⬜ GUI interpreter-exit teardown crash (`0xC0000374`, Qt/VTK finalize order);
  deterministic on old py311 venv `test_commands.py`, 2/117 flaky on 3.12;
  candidate fix: session-end `pyvista.close_all()` and explicit `QApplication`
  shutdown in conftest
- 🟡 ruff tree-wide debt: mechanical sweep done 2026-09-18 in one commit
  (`e089aa7`, ruff 0.16.8, safe fixes plus format, no hand edits). CI scope
  (`src tests`): `ruff check` 590 to 195, `ruff format --check` 241 files to 0.
  Whole repo (adds `examples`, `tools`): 696 to 224 and 266 to 2 (the 2 are
  python blocks inside `docs/adr/*.md`, left alone). Suites unchanged after the
  sweep: unit 299, integration 55, GUI 181/181 with all 31 exit codes 0. The CI
  lint job runs `ruff check src tests` then `ruff format --check src tests`; the
  format step now passes, the check step still fails on the 195 below. No safe
  fix is left; what remains needs a manual pass (unsafe = ruff offers a fix only
  under `--unsafe-fixes`, to be reviewed by hand, never bulk applied).

  | Rule | Repo | CI scope | Kind | Note |
  |---|---|---|---|---|
  | N806 | 45 | 43 | manual | engineering symbols as locals (`H`, `L`, `Iz`, `dU`); candidate per-file ignore |
  | RUF003 | 38 | 29 | manual | unicode in comments; 77 of the 95 RUF001/2/3 hits are `×`, the rest Greek letters and minus signs; candidate `allowed-confusables` |
  | RUF002 | 37 | 25 | manual | same, in docstrings |
  | RUF001 | 20 | 18 | manual | same, in strings (some are UI text) |
  | N815 | 19 | 19 | manual | OpenSees parameter names as model fields (`cR1`, `epsU`; serialized, do not rename) and Qt signal names; candidate noqa |
  | SIM105 | 16 | 16 | 15 unsafe, 1 manual | `try/except/pass` to `contextlib.suppress` |
  | B023 | 9 | 9 | manual | all 9 are two helper closures inside one loop in `model_renderer.py`, called within the same iteration; looks benign, confirm then bind or noqa |
  | E741 | 6 | 5 | manual | ambiguous name `I` (moment of inertia) |
  | N802 | 6 | 6 | manual | Qt event overrides (`mousePressEvent`) and test names that embed a signal name; candidate noqa |
  | RUF046 | 5 | 3 | unsafe | `int()` around a value that is already an integer |
  | F401 | 4 | 4 | manual | `typing.Union` left unused by UP007 in four `core/*/__init__.py` |
  | RUF059 | 4 | 4 | unsafe | unused unpacked variable |
  | RUF012 | 3 | 3 | manual | mutable class default, needs `ClassVar` |
  | B905 | 3 | 3 | unsafe | `zip()` without `strict=` |
  | F841 | 3 | 2 | unsafe | unused local |
  | B017 | 1 | 1 | manual | `pytest.raises(Exception)` |
  | N817 | 1 | 1 | manual | camelcase imported as acronym |
  | SIM101 | 1 | 1 | unsafe | duplicate `isinstance` |
  | SIM102 | 1 | 1 | manual | collapsible `if` |
  | SIM113 | 1 | 1 | manual | use `enumerate` |
  | RUF022 | 1 | 1 | unsafe | `core/__init__.py` `__all__` has grouping comments |
  | Total | 224 | 195 | 32 unsafe, 192 manual | |

  Follow-ups from the sweep: `core/catalog/generated/*` was reformatted (101
  files, quote style), so `tools/gidopensees_import/codegen.py` should run
  `ruff format` on its output or the next regeneration will undo it; ruff is
  unpinned in CI and pinned to v0.4.4 in `.pre-commit-config.yaml`, while the
  sweep used 0.16.8 (`requirements-lock.txt`), so the three should be aligned.
- ⬜ mypy debt: 148 errors, 124 union-attr in `opensees_runner.py`; mypy runs
  neither in CI nor in an installed pre-commit today

## Out-of-scope (for now)
- ✂️ Code-checking (TBDY-2018, ASCE 41, Eurocode 8)
- ✂️ Soil-structure interaction GUI
- ✂️ Cloud / collaborative editing
- ✂️ Native shell-element rendering / pre-processing (quads exist as a
  primitive, but a proper shell workflow is its own phase)
