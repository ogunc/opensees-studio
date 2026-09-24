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
- ✅ ISO-2 Seismic isolators, `flatSliderBearing` and `singleFPBearing` with
  friction models (2026-09-24, cloud-built on branch `cc/iso-2`, see the
  Windows verification box). Core `Project.friction_models` with
  `CoulombFriction`, `VelDependentFriction` and `VelNormalFrcDepFriction`
  (additive, schema stays 2), referenced by id from
  `FlatSliderBearingElement` (Kinit) and `SingleFPBearingElement` (Reff,
  Kinit), which share the bearing base of ISO-1 (P, Mz, T, My materials,
  orient, shearDist, doRayleigh, mass) plus `-iter`. Live OpenSeesPy 3.8.0
  signatures confirmed in separate processes; every hard exit found became a
  validator rule: OpenSees terminates the process (exit 255) on Coulomb
  mu <= 0, VelDependent muSlow or muFast <= 0 or transRate < 0,
  VelNormalFrcDep aSlow or aFast <= 0, a coincident-node bearing without
  -orient, and zero or parallel orient vectors; a bad friction model
  reference, a missing T or My in 3D and a three-value 2D orient raise a
  Python exception; Reff = 0 or Kinit = 0 make the analysis fail (NaN) and
  negative values give wrong-signed forces, so all three are positive
  fields; `-iter 0` fails the integrator. The runner emits `frictionModel`
  after the materials. Measured laws of the live build: VelDependent
  mu = muFast - (muFast - muSlow) exp(-transRate |v|); VelNormalFrcDep
  friction force a N^n with the rate alpha0 + alpha1 N + alpha2 N^2 and the
  cap maxMuFact muFast (OpenSees source). Verified against the Coulomb
  closed form at 10 and 25 slip displacements: flat slider rectangular loop
  at mu W (1e-6), pendulum loop with stiffness W / Reff (2 percent; the
  element takes the normal force on the curved surface, N = W + F u / Reff,
  reproduced to 1e-4) and intercept mu W, energy 4 mu W (u_max - u_y) per
  cycle within 0.5 percent; VelDependent reaches muSlow W and muFast W
  within 1 percent under imposed slow and fast velocities; a rigid mass on
  one pendulum free-vibrates at 2 pi sqrt(Reff / g) within 0.1 percent and
  stays bounded with periodic loops under a 1 Hz sine after a static gravity
  preload (peak 0.034 m literal, 5 percent). UI: Define > Friction Models
  (Material Library pattern, deleting a model in use is refused), the
  bearing dialog (Assign > Joint > Bearing) gains both sliding types with
  read-only slip displacement, restoring stiffness and isolated period in
  the project units, rendering, tooltip and property rows as ISO-1. Example
  `isolated_portal2d_fp` (the ISO-1 frame on two single FP bearings, mu 0.05,
  Reff 61 in, same record and scale): peak isolator displacement about
  1.42 in against 1.35 in with the elastomeric bearings, superstructure
  drift 0.22 in against 0.68 in fixed-base, residual offset 0.57 in.
- ✅ Process isolation: analyses run in a child process (2026-09-24,
  cloud-built on branch `cc/proc-iso`, see the Windows verification box).
  Found in ISO-2 Step 0: Analyze > Run went `MainWindow._on_run_analysis`
  to `RunAnalysisDialog` to `AnalysisRunner.run`, which moved an
  `AnalysisWorker` onto a `QThread` in the GUI process, so a hard exit
  inside OpenSees (measured with the ISO-1 coincident-node bearing and the
  -orient emission bypassed) terminated the application with exit code
  255 and no signal, traceback or atexit handler. Now: `AnalysisRunner`
  writes the pre-run snapshot `<stem>.run-snapshot.osmodel` atomically
  (temp file then rename) next to the project file, or
  `untitled.run-snapshot.osmodel` in the app data directory for a
  never-saved project, then starts `python -m opensees_studio.run` with
  `QProcess`. The CLI prints one JSON object per stdout line (log,
  progress, case_started, case_finished, error), sends fd 1 to stderr so
  OpenSees native output cannot corrupt the protocol, and exits 0 when
  every case ran (an early stop is a result), 2 on a Python-side analysis
  error, 3 on an invalid project or reference; anything else means the
  child died. Results travel through `services/result_store.py` (float64
  HDF5 plus manifest.json): thirteen example cases covering static, modal,
  pushover, transient and response-spectrum results match the direct
  OpenSeesRunner results with a tolerance of zero. The Run dialog shows
  step progress and has a Cancel button (terminate, kill after 1.5 s)
  that leaves the project unchanged; a non-zero exit or a dead child opens
  a non-blocking error dialog with the exit code, the last error line and
  the last 40 stderr lines while the window stays alive and the snapshot
  is kept. On open, a snapshot newer than the project file prompts
  "Restore unsaved changes from the last analysis run?" (restore loads it
  as unsaved changes, discard deletes it); a normal save or close removes
  it. `OPENSEES_STUDIO_IN_PROCESS=1` keeps the threaded in-process runner
  for debugging (no cancel). Overhead on the Linux container: about 0.37 s
  per run for process start, imports and result loading (cantilever static
  0.002 s in-process against 0.37 s in the child; ex1a_canti2d 1000-step
  transient 0.03 s against 0.39 s). Side finding: ARPACK keeps its start
  vector across eigen calls, so only the first eigen call of a process is
  reproducible; a second in-process call flipped mode signs, rotated the
  repeated eigenvalue pair of space_frame_3d and moved its SRSS result by
  0.27, which the child process avoids by construction. The unit suite
  now runs without any QT_QPA_PLATFORM setting (the five qtbot tests of
  test_grid_system.py moved to tests/gui).
- ✅ Modal determinism and CQC (2026-09-24, cloud-built on branch
  `cc/modal-det`, see the Windows verification box). Step 0 measured the
  eigen solvers in fresh processes (three calls each with wipeAnalysis
  between): ARPACK repeats differ by up to 2.0 in normalized mode shape on
  the examples (sign flips, the rotated repeated pair of space_frame_3d,
  the mirror tie of elastic_frame), fullGenLapack repeats are bit-identical
  everywhere, the two solvers agree on the eigenvalues to about 1e-13
  relative (shear frame 6.3e-7), and fullGenLapack costs 0.0013 s at 48
  free DOF, 4.8 s at 900, 57.6 s at 1764 and 657 s at 3402, against 0.42 s
  for ARPACK at 3402. symmBandLapack fails on every example (lumped mass
  leaves DOF massless). Ruling (c): `ModalCase.solver` defaults to `auto`,
  dense at or below `core.modal.DENSE_EIGEN_MAX_FREE_DOF` (500, override
  `OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF`), ARPACK above, where the analysis
  CLI runs every ARPACK case that follows an earlier eigen call in a fresh
  child process and relays its protocol; `genBandArpack` and
  `fullGenLapack` are honoured when chosen, `symmBandLapack` loads but is
  refused at run time, other names load with a notice and run with the
  routing; the solver used and the free DOF count travel in the results
  and the manifest and show in the results panel, the spectrum dock and
  the run log. Mode shapes are sign-normalized (largest absolute component
  positive, ties within 1e-9 to the lowest DOF index) and the modes of a
  repeated eigenvalue are made mass-orthogonal, because the dense solver
  returns a mass-oblique pair there (mass cosine 0.084 on space_frame_3d).
  Found on the way: `mass_participation` normalized with the excitation
  direction components only, so the two sway modes of space_frame_3d each
  carried 84 percent of the X mass (200 percent cumulative); it now uses
  the full modal mass (100 percent). `core.modal_combination` holds SRSS
  and CQC (Der Kiureghian, equal and unequal damping); CQC of a degenerate
  pair is invariant under rotation of the pair (below 1e-12 in the unit
  test, below 1e-10 relative on the real space_frame_3d output, 3e-10
  between the dense and the ARPACK basis) while SRSS moves by more than
  1 percent (12 percent between the two bases). New response spectrum
  cases default to CQC with the case's modal damping (0 or empty stored as
  none, meaning the spectrum's damping; a CQC run never uses zero damping),
  saved cases keep their rule, and SRSS with a mode pair at frequency
  ratio 0.9 or above (case field `closely_spaced_ratio`) warns with the
  modes and ratios in the results, the panel, the dock and the log. Multi
  case CLI runs of space_frame_3d, cantilever, elastic_frame and a 900 free
  DOF synthetic grid routed to ARPACK match fresh-process references with
  a tolerance of zero. The eight modal examples store `solver: auto`
  (changed in place; a full regeneration would also move 28 files from
  schema 1 to 2, see Maintenance).
- ⬜ TBDY modal combination rule: engineer to confirm. TBDY 2018 asks for
  CQC across modes (and SRSS or the 100/30 rule across directions, which
  is out of scope here); confirm the rule, the damping (5 percent) and
  whether the closely spaced warning threshold of 0.9 matches the intended
  practice before response spectrum cases are used for TBDY checks.
- ⬜ Material Tester still runs `test_uniaxial_material` in the GUI process
  (`viewmodels/material_tester_vm.py`, `run()` calls the service directly),
  so an unsupported input that makes OpenSees hard-exit takes the
  application down; move it to the CLI path (a `--material-test` mode or a
  second entry point with the same JSON protocol) or guard the inputs
  before emission.
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
- ⬜ Windows verification of GM-1, GM-2, GM-3, GM-2b, ISO-1, ISO-2,
  process isolation and modal determinism (cloud-built).
  All eight phases were built and tested in a Linux cloud container
  (offscreen Qt), so the Windows dev machine has to confirm them before
  `cc/modal-det` (which contains `cc/proc-iso`, `cc/iso-2`, `cc/iso-1`,
  `cc/gm-2b`, `cc/gm-3` and `cc/gm-2`) reaches `develop`:
  1. `git pull` on the Windows checkout, then `git checkout cc/modal-det`.
  2. Unit, integration and tools (all 45, gidopensees checkout present)
     on the Windows `.venv`. The integration run now asserts the corrected
     BM68elc peak displacements (8 examples, 5 percent tolerance) on the
     Windows OpenSeesPy wheel.
  3. GUI per-file sweep (41 files, `test_ground_motions_site_target.py`,
     `test_assign_bearing.py`, `test_friction_bearings.py`,
     `test_run_snapshot_recovery.py`, `test_child_process_runner.py` and
     `test_grid_system_gui.py` are new), recording the exit code of every
     process.
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
  10. Assign > Joint > Bearing (the ISO-1 label Elastomeric Bearing was
     renamed in ISO-2) on Windows: select two joints,
     create a Plasticity and a Bouc-Wen bearing, confirm the derived u_y
     and F_y, the hover tooltip over the bearing line, the property editor
     rows, undo, and that alpha1 = 1 is refused with the dialog kept open.
  11. Open `examples/isolated_portal2d.osmodel` on Windows, run Gravity
     then Earthquake, and confirm the base-node peak |ux| of about 1.35 in.
  12. Ground Motions dialog with a vertical target: the overlay must stop at
     TLD and a period range beyond TLD must be refused with the message.
  13. `tests/integration/test_friction_bearing.py` and
     `test_isolated_portal2d_fp.py` on the Windows OpenSeesPy wheel: the
     flat slider plateau (1e-6), the pendulum slope (2 percent), the loop
     energies (0.5 percent), the VelDependent slow and fast forces (1
     percent), the pendulum period (1 percent) and the FP isolator peak of
     about 1.42 in must hold on the Windows build of the friction bearings.
  14. Define > Friction Models on Windows: add a Coulomb and a VelDependent
     model, edit mu with Apply, undo from the main window, and confirm that
     deleting a model referenced by a bearing is refused with the message.
  15. Assign > Joint > Bearing on Windows with the sliding types: create a
     flatSliderBearing and a singleFPBearing referencing the friction model,
     confirm the slip displacement, W / Reff and the period in the project
     units, the tooltip and property rows, undo, and that Reff = 0 is refused
     with the dialog kept open.
  16. Open `examples/isolated_portal2d_fp.osmodel` on Windows, run Gravity
     then Earthquake, and confirm the base-node peak |ux| of about 1.42 in.
  17. Unit suite on Windows without any `QT_QPA_PLATFORM` setting
     (`pytest tests/unit`): 503 tests, no abort. The integration suite
     includes `test_analysis_cli.py` (subprocess exit codes 0, 2, 3 and the
     hard-exit hook 255) and `test_cli_result_parity.py` (thirteen cases,
     tolerance zero) on the Windows OpenSeesPy wheel.
  18. Normal run through the child process on Windows: open
     `examples/cantilever.osmodel`, Analyze > Run > Tip-Load; the console
     must show "Starting analysis process: ...python.exe -m
     opensees_studio.run", the progress bar must fill and the deformed
     shape must be available afterwards. Check that `sys.executable` is
     the `.venv` python.exe (with pythonw.exe the child is pythonw and the
     pipes still work, but confirm).
  19. Cancel a long transient on Windows: open `examples/ex1a_canti2d.osmodel`,
     raise the Earthquake steps to 2 000 000 in Analyze > Cases, run, press
     Cancel after the first progress update; the dialog must log
     "--- Cancelled ---" within about two seconds (terminate is WM_CLOSE on
     Windows and does nothing to a console process, so the kill after 1.5 s
     is the path that ends it), the window must stay responsive and the
     model unchanged.
  20. Hard-exit hook on Windows: in the shell set
     `OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=2` before `python -m
     opensees_studio`, run the ex1a_canti2d Earthquake case; the error
     dialog must show "exited with code 255", the stderr tail and the
     window must stay alive with the snapshot kept next to the project.
  21. Recovery prompt on Windows: with a long transient running, end the
     OpenSees Studio process from Task Manager, restart, File > Open the
     same project; the prompt "Restore unsaved changes from the last
     analysis run?" must appear, Yes must load the snapshot as unsaved
     changes (title marked dirty), No must delete the snapshot file.
  22. Overhead on Windows spawn: time Run to "--- Done" for the cantilever
     Tip-Load case in the child (default) and with
     `OPENSEES_STUDIO_IN_PROCESS=1`; Linux measured 0.37 s against 0.002 s,
     Windows process creation and the OpenSeesPy DLL load will be larger
     (expect one to three seconds); record the numbers here.
  23. Modal determinism suites on the Windows OpenSeesPy wheel: unit
     532 tests without `QT_QPA_PLATFORM` (`test_modal_core.py` and
     `test_modal_combination.py` are new), integration 128 passed and 1 xfailed
     (`test_response_spectrum_combination.py` is new, `test_runner_modal.py`
     gained the two-calls and elastic_frame tie tests,
     `test_cli_result_parity.py` the multi-case runs including the 900
     free DOF grid with `OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF=100`), GUI
     per-file sweep 230 tests in 42 files
     (`test_response_spectrum_warning.py` is new) with every exit code
     recorded. The dense solver on the Windows LAPACK: time the 900 free
     DOF grid (Linux 4.8 s per call) and record it here.
  24. Open `examples/space_frame_3d.osmodel` on Windows, run Modal-6: the
     results panel title must show "eigen solver fullGenLapack, 48 free
     DOF" and the console "Eigen solver: fullGenLapack (48 free DOF, dense
     at or below 500)."; the OpenSees banner "the 'fullGenLapack' eigen
     solver is VERY SLOW" may appear on stderr and must not reach the
     protocol. Eigenvalues 759.131 (twice), 909.129, 5363.81, 13863.9
     (twice).
  25. Run RS-X-SRSS on Windows: the results panel must show the warning
     "SRSS with closely spaced modes ... modes 1 and 2 (ratio 1.000)" and
     the console the same line; switch the case to CQC in Analyze > Cases
     (the damping field enables, 0 means the spectrum's damping), run
     again: no warning, roof node 12 U1 about 0.01404 m and U2 0.
  26. Analyze > Cases > New > ResponseSpectrum on Windows: the new case
     must show CQC with the damping field enabled; choosing SRSS must
     disable it. Modal case dialog: the solver list must read Auto
     (fullGenLapack at or below 500 free DOF), genBandArpack,
     fullGenLapack, and a case saved with symmBandLapack must show
     "(not offered, refused at run time)" and fail its run with the
     positive definite mass message.
  27. Fresh-process re-exec on Windows: in the shell set
     `OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF=10`, then
     `python -m opensees_studio.run --project examples\space_frame_3d.osmodel
     --cases 2 4 --out out` must log "uses ARPACK after an earlier eigen
     call: running it in a fresh process" before case 4, exit 0, and
     `out\manifest.json` must list both cases with solver genBandArpack.
  28. Merge `cc/modal-det` into `develop` after everything is green.
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
