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
- ✅ **Material Tester dialog**: Qt front-end for the service above; live
  stress–strain plot with strain-amplitude and step controls. Define menu,
  Ctrl+Shift+T; three strain protocols, derived values and CSV export
  (2026-09-22).
- ⬜ Material Tester: tension-first and tension-only monotonic protocols; the
  service requires a negative `max_compressive`, so every protocol starts in
  compression today
- ⬜ Material Tester: `HystereticSM` support in the service (`_emit_uniaxial`
  branch and `SUPPORTED_MATERIALS` entry); the dialog leaves it off the list
  until then
- ⬜ Material Tester: user-defined strain histories (file import or asymmetric
  peak tables) and an option for equal strain increments on quarter and half
  branches
- ⬜ Material Tester: `0xC000041D` seen once in 26 runs of
  `tests/gui/test_material_tester_dialog.py` (2026-09-22, output tail only);
  not seen since in 10 standalone runs and 3 full per-file sweeps with
  faulthandler on (2026-09-23). Capture the full faulthandler output if it
  returns
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
- ✅ GUI interpreter-exit teardown crash (`0xC0000374`): closed 2026-09-23.
  Root cause: `ProjectCommand` held a strong reference to its view model, which
  owns the `QUndoStack` that owns the command, so every dropped view model was
  a PySide6 cycle, and freeing many of them in pytest's final `gc.collect()`
  corrupted the heap. Fixed with a weak reference (`23ba1d9`) plus a
  session-end Qt/VTK teardown fixture in `tests/gui/conftest.py` (`3d02d77`);
  32 of 32 GUI files exit 0 in three consecutive per-file sweeps
- ✅ ruff tree-wide debt: closed 2026-09-18. CI scope (`src tests`), ruff
  0.16.8: `ruff check` 590 to 0, `ruff format --check` 241 files to 0, so both
  steps of the CI lint job pass. Path: mechanical sweep `e089aa7` (590 to 195),
  config rulings `843e40e` (to 55), E741 `59779d8` (to 50), B023 `069ea05`
  (to 41), reviewed unsafe fixes `d2480a3` (to 11), manual remainder `4ac6333`
  (to 0). Suites after the last step: unit 300 (one test added for the
  renderer closures), integration 55, tools 42, GUI 181/181 with all 31 exit
  codes 0.

  Config rulings in `pyproject.toml`: N802, N806, N815 ignored (engineering
  notation such as `E`, `I`, `A`, `Kinit`, `cR1` is the domain language);
  `allowed-confusables` = multiplication sign and Greek alpha, gamma, nu, rho.
  Real strays were fixed in the text instead: three U+2212 minus signs in
  `main_window.py` docstrings, one en dash in the Steel02 `R0` description.

  Suppressed by design, each with its reason on the line:

  | Rule | Count | Where | Reason |
  |---|---|---|---|
  | E741 | 6 | five integration tests, one example | `I` is the second moment of area, next to `A` and `E` |
  | RUF022 | 1 | `core/__init__.py` | `__all__` is grouped by domain under section comments; sorting scatters them |
  | UP042 | 1 | `core/units.py` | `UnitSystem` is serialized into `.osmodel` files |

  The SIM113 suppression on the transient step counter in
  `services/opensees_runner.py` was dropped on 2026-09-18: the counter is now
  read after the loop (see the `n_steps` box below), so the rule no longer
  fires.

  RUF012 needed no suppression: the three class-level lists are read-only
  constants and are now annotated `ClassVar[list[str]]`. B023: both helper
  closures in `ModelRenderer._build_grid` were only ever called inside their
  own iteration, and are now early bound through keyword defaults anyway.
  B905: all three `zip()` calls got `strict=True` (lengths proven equal).

  Outside CI scope, left as is: `ruff check .` reports 3 in `examples`
  (RUF046 twice, F841 once, all unsafe-fix class) and `ruff format --check .`
  reports 2 (python blocks inside `docs/adr/*.md`).

  Tooling: `codegen.py` runs `ruff format` on its output (`232a07b`); ruff is
  pinned to 0.16.8 in the CI lint job and in `.pre-commit-config.yaml`,
  matching `requirements-lock.txt`.
- ✅ catalog codegen is reproducible byte for byte (2026-09-18). The header
  stamp is derived from the source, never from the wall clock:
  `# Generated from schemas.json sha256:42032585df71, codegen v2`, that is the
  first 12 hex of the sha256 of `schemas.json` (CRLF normalised to LF, so
  Windows and Linux agree) plus `CODEGEN_VERSION` in `codegen.py`. Rule: bump
  the constant whenever a template changes. The switch rewrote exactly one
  header line in each of the 100 generated files; a second regeneration leaves
  `git status` clean. Guarded by `tests/tools/test_codegen_idempotent.py`.
- ✅ `TransientResults.n_steps` is the number of steps actually completed
  (2026-09-18); the requested count lives in `n_steps_requested`, and
  `early_stop` / `steps_summary()` make a short run visible in the results
  panel, the plot labels, the analysis log and the animation export. A run
  where no step converges raises instead of returning empty arrays. The class
  is not persisted, so there is no `.osmodel` or HDF5 schema change. The fix
  exposed the stall recorded in the next box, which the old count had hidden.
- ⬜ `rc_frame_earthquake` stalls at t = 1.93 s: the run completes 192 of 400
  steps (it was 98 before the case went from tol 1e-12 / 10 iterations to
  1e-8 / 50). The step-count assertion in
  `tests/integration/test_rc_frame_earthquake.py` is `xfail(strict=True)` until
  this is fixed.
  - Cycle data at step 193 (`NormDispIncr`): plain Newton reaches an increment
    of 6.64e-6 at iteration 3 and stays frozen there for all 50 iterations,
    while the residual norm alternates 0.664 / 0.657 and never decays. Every
    fallback cycles as well, 1000 iterations each: `Newton -initial` ends at
    5.72e-6, `Broyden 8` repeats three values (2.35e-7, 9.58e-7, 6.84e-6),
    `NewtonLineSearch 0.8` ends at 1.24e-7 with the residual still at 0.11.
    Step 99 (t = 0.99 s) is passed only through the fallback chain.
  - First diagnostic question: model units and displacement magnitude. Node 3
    Ux reaches +/-1.5 in model units. If the model were in metres that would be
    a collapsed frame and the cycle would be physical. The example script
    reports its mass in kip*s^2/in, which points to kip and inch (about 1 %
    drift on a 144 in column), but confirm it and check the ground-motion
    scale factor (g applied twice or not at all), the mass and the unit system
    before touching algorithms.
  - Then candidate numerical routes: sub-stepping on failure, `KrylovNewton`,
    an `EnergyIncr` or `NormUnbalance` test, comparison against OpenSees Ex3.3.
  - The drift assertion (`|Ux| < 14.4`) tolerates that displacement and should
    be tightened once the example is sound.
- ⬜ review analysis-case tol 1e-12 in `beam_quad_2d`, `ex1a_canti2d_eq`,
  `rc_frame_gravity`, `rc_frame_pushover` (scripts and their `.osmodel` files).
  The element-level `ForceBeamColumn` 1e-12 / 10 is the OpenSees default for
  the element's internal iteration; leave it.
- ⬜ mypy debt: 148 errors, 124 union-attr in `opensees_runner.py`; mypy runs
  neither in CI nor in an installed pre-commit today

## Out-of-scope (for now)
- ✂️ Code-checking (TBDY-2018, ASCE 41, Eurocode 8)
- ✂️ Soil-structure interaction GUI
- ✂️ Cloud / collaborative editing
- ✂️ Native shell-element rendering / pre-processing (quads exist as a
  primitive, but a proper shell workflow is its own phase)
