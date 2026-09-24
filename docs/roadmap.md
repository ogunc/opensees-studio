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
  `ConstantTimeSeries`, `PathTimeSeries`, `TrigTimeSeries`, `PlainLoadPattern`,
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
- ✅ ISO-1 Seismic isolators, elastomeric bearings (2026-09-24, cloud-built
  on branch `cc/iso-1`, see the Windows verification box). Core elements
  `ElastomericBearingPlasticityElement` and `ElastomericBearingBoucWenElement`
  (2D and 3D): Kinit, Qd, alpha1, alpha2, mu, plus eta, beta, gamma for
  Bouc-Wen; P and Mz materials, T and My for 3D; optional orient, shearDist,
  doRayleigh, mass; validation of stiffness, strength, 0 <= alpha < 1,
  orient vectors and material references (additive, schema stays 2). The
  runner emits the live OpenSeesPy 3.8.0 signature and always writes the
  six -orient values (OpenSees 3.8 terminates the process on a zero-length
  bearing without them; there is no catalog stub for either element).
  Verified against the bilinear closed form: yield force Qd/(1 - alpha1),
  post-yield slope alpha1 Kinit, energy per cycle 4 Qd (u_max - u_y) within
  0.5 percent, Bouc-Wen with eta = 50 within 0.5 percent and closed, secant
  stiffness decreasing with amplitude; an isolated SDOF under a GM-3 sine
  stays bounded with periodic loops. Dialog Assign > Joint > Elastomeric
  Bearing with derived u_y, F_y and K_eff, line rendering, hover tooltip,
  property editor rows. Example `isolated_portal2d` (Example 1b frame on
  two isolators under BM68elc, peak isolator displacement about 1.35 in,
  superstructure drift 0.23 in against 0.68 in fixed-base).
  Ruling applied in the same phase: the TBDY vertical spectrum is defined
  only up to TLD (NaN beyond, plot stops, scaling refuses ranges past TLD).
- ⬜ ISO-2 Seismic isolators, `flatSliderBearing` and `singleFPBearing`
  with friction models (Coulomb, velocity-dependent)
- ⬜ ISO-3 Seismic isolators, `TripleFrictionPendulum`
- ✅ GM-1 Ground motions: import, metadata, catalog (2026-09-24). Core
  readers for PEER AT2 (NGA and old SMD headers), two-column
  time/acceleration with dt uniformity validation, and bare value lists
  with a user-given dt; format auto-detection with explicit override.
  Metadata: PGA with its time, PGV and PGD (trapezoidal integration,
  linear detrend of velocity as the stated baseline correction), Arias
  intensity, D5-95, total duration. Project catalog stores relative path
  plus sha256 content hash (CRLF-normalised), never sample values
  (schema_version 2); legacy embedded series migrate on load only when
  the source file is identified with certainty, otherwise the values go
  to a `<stem>.records/` sidecar at the next save (never overwriting
  different content). Missing or changed files flag the entry and the
  runner refuses that case with a clear message. Define > Ground Motions
  dialog: import, table with PGA and D5-95, pyqtgraph trace, remove,
  relink with the hash re-checked. No record data is bundled in the
  repo: PEER NGA terms do not allow redistribution, so tests generate
  synthetic records on the fly.
  Single-process GUI note: on a Linux container with the offscreen Qt
  platform, the whole GUI suite in ONE pytest process passed (192 tests,
  exit 0, faulthandler on, under 3 s), so the per-file recipe is a
  Windows/VTK-render-window constraint, not a universal one. The
  per-file recipe stays for the Windows dev machine.
- ✅ GM-2 Ground motions: response spectra, TBDY 2018 target, scaling
  (2026-09-24, cloud-built on branch `cc/gm-2`, see the Windows
  verification box). Core: elastic Sd, pseudo-Sv and pseudo-Sa by the
  Nigam-Jennings piecewise-exact recurrence (exact for the linearly
  interpolated record, no solver step, verified against Newmark average
  acceleration, PGA and PGD limits and the closed-form resonance
  magnification); TBDY 2018 horizontal design spectrum from SDS and SD1
  (TA = 0.2 SD1/SDS, TB = SD1/SDS, TL = 6 s) plus user period/Sa tables
  with log-log interpolation, stored as `target_spectra` on the project
  (additive, schema stays 2); scaling methods PGA, Sa(T1) and period
  range [a T1, b T1] with a uniform or individual factor and SRSS pairs,
  all comparisons in g via the record's `accel_units` and the project
  unit system (unknown units are refused with a message). Factors are
  written to `PathTimeSeries.factor` only, the one place a scale lives;
  records are never modified. Dialog: spectrum plot with target overlay,
  target editor, Scale panel with preview and one undoable Apply, units
  combo per record; absolute record paths from never-saved projects are
  re-anchored to relative on the first save. The preset "TBDY 2018
  (engineer to confirm)" (a = 0.2, b = 1.5, alpha = 1.3 for SRSS pairs)
  still needs an engineer's confirmation against the text of the
  standard before it is relied on; single-component alpha is the
  user's choice. `services/peer_record.py` now delegates AT2 parsing
  to the core readers (one AT2 parser). The 8 BM68elc examples were left
  at `accel_units="unknown"` and factor 1.0 here; the BM68elc box below
  records the later fix (record in g, factor from the project unit system).
- ⬜ Spectral matching (future): adjust a record in the time or
  frequency domain so its spectrum follows the target over a period
  range, writing a new record file into the catalog (records stay
  immutable, the matched record is a new entry with its own hash).
- ✅ GM-3 Ground motions: sine and sine-beat generator (2026-09-24,
  cloud-built on branch `cc/gm-3`, see the Windows verification box).
  Core `generators`: continuous sine with optional linear ramp-in and
  ramp-out (in cycles) and a sine-beat train (cycles per beat, number of
  beats, pause; each beat a sine under a half-sine envelope scaled to the
  requested peak), both returning `(dt, accel)` plus a descriptor that
  `from_descriptor` rebuilds. Core `TrigTimeSeries` (`timeSeries Trig`)
  with runner emission, verified against the same sine sampled as a Path
  series on an SDOF. Generated inputs are never catalog records: a plain
  sine is stored as a Trig series, a ramped sine or a sine-beat as an
  embedded Path series with `file_path="generated:<kind>"` and the
  descriptor in the new additive `generator` field (schema stays 2).
  Dialog: Generate… with live trace and spectrum preview over the current
  target, one undoable add; Edit… reopens the generator from the stored
  descriptor and swaps the series in place (undoable). The preset
  "IEEE 693 style (engineer to confirm)" (5 beats, 10 cycles per beat,
  2 s pause) still needs an engineer's confirmation against the text of
  the standard; all its values stay editable.
- ✅ GM-2b Ground motions: TBDY 2018 site coefficients, vertical spectrum,
  record-count warning (2026-09-24, cloud-built on branch `cc/gm-2b`, see
  the Windows verification box). Core `tbdy_site`: Tablo 2.1 (Fs) and
  Tablo 2.2 (F1) with clamped linear interpolation, site classes ZA to ZE
  (ZF refused with a message), DD-1 to DD-4 as labels only, and
  SDS = Ss Fs, SD1 = S1 F1; ported from the owner's cfs-egitim-app
  `core/seismic/tbdy_spectrum.py` (behaviour, not its 4 or 6 decimal
  rounding: corner periods stay exact). `TargetSpectrum` kind `tbdy2018`
  now takes either SDS and SD1 or Ss, S1, site class and DD label, storing
  inputs and derived Fs, F1, SDS, SD1 (additive fields, schema stays 2);
  new kind `tbdy2018_vertical` is the owner's SaeD (TAD = TA/3,
  TBD = TB/3, TLD = TL/2, 0.8 SDS plateau; since ISO-1 the spectrum is NaN
  beyond TLD, the plot stops there and scaling refuses ranges past TLD),
  validated on the owner's SAP2000 TSC-2018 DD-2 points. Period-range
  scaling carries a warning below 11 records (11 pairs in SRSS mode),
  shown in the Scale panel; the scaling still runs. Dialog: Ss, S1, site
  class and level form beside the SDS, SD1 form, vertical option, derived
  SDS, SD1, TA, TB read-only. The 8 BM68elc examples were fixed in the
  same phase (box below). Out of scope by ruling: AFAD grid lookup,
  reduced spectrum Ra and SaR, equivalent lateral force, load
  combinations, Chapter 10 checks.
- ⬜ AFAD grid lookup (optional extra, future): Ss, S1, PGA and PGV at a
  latitude and longitude by interpolation of the AFAD TDTH grid, as in the
  owner's cfs-egitim-app `core/seismic/afad_grid.py`. Needs the 2.2 MB
  grid JSON and scipy, neither in the base tier, so it would be an optional
  extra or a downloaded data file, feeding the Ss, S1 form of the target
  editor.
- ⬜ Reduced spectrum Ra and SaR (future, only if response spectrum
  analysis is added): TBDY 2018 Denk. 4.1 Ra(T) = D + (R/I - D) T/TB below
  TB and R/I above, SaR = Sae/Ra, with R, D and I typed by the user (the
  owner's structural-system table covers only the two CFS systems).
- ✅ BM68elc scale factor in the 8 Ex1a/Ex1b/Ex2/Ex3 earthquake examples
  (investigated 2026-09-24, fixed 2026-09-24 on `cc/gm-2b`). Ruling: physical
  consistency wins over fidelity to the original OpenSees scripts. The
  bundled originals apply the record with `-factor 1`
  (`examples/data/Ex1a.Canti2D.EQ.tcl.txt:68`,
  `examples/data/Ex1b.Portal2D.EQ.tcl.txt:77`) or with `-factor $GMfatt`
  where `GMfatt` is 1.0 and the comment says "data in input file is in g"
  (`Ex2a.Canti2D.ElasticElement.EQ.tcl.txt:190-191`,
  `Ex2b.Canti2D.InelasticSection.EQ.tcl.txt:214-215`,
  `Ex3.Canti2D.analyze.Dynamic.EQ.Uniform.tcl.txt:105-106`); `GMfact` (1.0,
  1.0 and 1.5) is set but never used and stays unused (1.0). The file peak
  is 0.0567 (`examples/data/BM68elc.acc`), so the record is in g. All 8
  projects use the in-kip unit system, so each script now sets the series
  factor to `gravity(UnitSystem.US_IN_KIP)` = 386.0886 in/s^2 (the g of the
  project unit system, not the hard-coded 386.4 the scripts use for mass)
  and marks the catalog entry `accel_units="g"`. The 8 `.osmodel` files were
  regenerated (diff: factor and unit, plus the additive `generator: null`
  and `target_spectra: []` fields the files had not carried since GM-2/GM-3).
  Measured peak |ux| (in) at the top node over the 10 s transient, every run
  converged (1000 of 1000 steps); the corrected values are asserted in the
  integration tests at 5 percent relative tolerance:
  | example | factor 1.0 (before) | factor 386.0886 (after) |
  |---|---|---|
  | ex1a_canti2d | 0.00339 | 1.310440 |
  | ex1b_portal2d (node 3) | 0.00176 | 0.680483 |
  | ex2a_canti2d_elastic_element | 0.00123 | 0.476742 |
  | ex2b_canti2d_inelastic_section | 0.00182 | 0.701343 |
  | ex2c_canti2d_inelastic_fiber_section | 0.00155 | 0.594721 |
  | ex3_canti2d_elastic_element | 0.00123 | 0.476742 |
  | ex3_canti2d_inelastic_section | 0.00182 | 0.701343 |
  | ex3_canti2d_inelastic_fiber_section | 0.00105 | 0.402587 |
  No example needed an xfail.
- ⬜ Windows verification of GM-1, GM-2, GM-3, GM-2b and ISO-1 (cloud-built).
  All five phases were built and tested in a Linux cloud container
  (offscreen Qt), so the Windows dev machine has to confirm them before
  `cc/iso-1` (which contains `cc/gm-2b`, `cc/gm-3` and `cc/gm-2`) reaches
  `develop`:
  1. `git pull` on the Windows checkout, then `git checkout cc/iso-1`.
  2. Unit, integration and tools (all 45, gidopensees checkout present)
     on the Windows `.venv`. The integration run now asserts the corrected
     BM68elc peak displacements (8 examples, 5 percent tolerance) on the
     Windows OpenSeesPy wheel.
  3. GUI per-file sweep (37 files, `test_ground_motions_site_target.py`
     and `test_assign_bearing.py` are new), recording the exit code of
     every process.
  4. Single-process GUI run (Check B) repeated on Windows with a
     10-minute timeout and `-X faulthandler`; note whether the VTK
     render-window crash near test 73 still occurs.
  5. `tests/integration/test_runner_trig_series.py` on the Windows
     OpenSeesPy wheel (Trig series emission against the sampled sine).
  6. Define > Ground Motions > Generate… on Windows: the live preview must
     repaint while parameters are spun (pyqtgraph inside a modal dialog)
     and Edit… must reopen a stored sine-beat with its parameters.
  7. Define > Ground Motions target editor on Windows: the Ss, S1, site
     class form must show SDS 0.5850, SD1 0.1755 for Ss 0.45, S1 0.117, ZC
     and refuse ZF with a message; the vertical option must overlay SaeD;
     the Scale panel must show the record-count warning with 3 records.
  8. Open one regenerated BM68elc example (`examples/ex1a_canti2d.osmodel`)
     on Windows, run its transient case and confirm the top-node peak
     |ux| of about 1.31 in.
  9. `tests/integration/test_elastomeric_bearing.py` and
     `test_isolated_portal2d.py` on the Windows OpenSeesPy wheel: the
     bilinear loop checks (0.5 percent) and the isolator peak of about
     1.35 in must hold on the Windows build of the bearing elements.
  10. Assign > Joint > Elastomeric Bearing on Windows: select two joints,
     create a Plasticity and a Bouc-Wen bearing, confirm the derived u_y
     and F_y, the hover tooltip over the bearing line, the property editor
     rows, undo, and that alpha1 = 1 is refused with the dialog kept open.
  11. Open `examples/isolated_portal2d.osmodel` on Windows, run Gravity
     then Earthquake, and confirm the base-node peak |ux| of about 1.35 in.
  12. Ground Motions dialog with a vertical target: the overlay must stop at
     TLD and a period range beyond TLD must be refused with the message.
  13. Merge `cc/iso-1` into `develop` after everything is green.
- ⬜ IDA (Incremental Dynamic Analysis) batch runner
- 🟡 Fiber-section editor — exists for rectangular / circular sections;
  confined / unconfined visual presets pending

## Backlog (post Phase 8)
- ⬜ Pre-analysis model validation: detect under-restrained or mechanism 2D/3D
  models before `ops.analyze`

## Maintenance / debt
- ⬜ Canonical float serialization in `.osmodel` (platform last-digit noise
  seen on 18 non-GM examples, 2026-09-24): regenerating every example on
  the Linux container changed only the last digit of some floats in 18
  non-GM `.osmodel` files (and moved them from schema 1 to 2), so the
  regenerated files were discarded and those 18 stay at schema 1 until a
  Windows regeneration. The cause was not investigated (candidates: libm
  differences in the derived values the example scripts compute). Options:
  round derived values in the scripts, or a tolerance-aware example
  round-trip check, so regeneration is diff-clean on both platforms.
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
