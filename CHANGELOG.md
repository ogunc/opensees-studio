# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), with the caveat
that this is pre-alpha: minor and patch releases may change the `.osmodel`
schema (it carries a `schema_version`, and a file from a newer build is now
refused instead of silently downgraded).

## [Unreleased]

## [0.0.30] - 2026-10-31

The integration release: the fork absorbs `upstream/main` (PRs #16-#18) and
ships the pre-run model check.

### Added

- **Analyze → Check Model (F6): review the model before it runs.** OpenSees does
  not explain a model it cannot solve — a node nobody connects, a member that
  points at a deleted node or a frame missing one support all end as a singular
  stiffness matrix and displacements that are really the load vector. The check
  reports, without running anything: free nodes that no element or constraint
  reaches (an error; a fully restrained one is a warning), elements that refer to
  a missing node, repeat a node or have zero length, zero-length elements whose
  nodes are apart, parts of the model with no support, several supported parts
  (with the pair of nodes sitting at the same point when there is one, since that
  is nearly always a node that was never merged), and **static instability** —
  groups of nodes that can move without deforming any element, reported with the
  nodes and the DOF (Ux, Rz …) that are free and the number of independent
  motions. Every finding can be selected in the canvas.
  Stability is decided on an idealised model, one unit-stiffness spring per
  deformation mode of each element (a bar has one, a 3D frame six, a shell
  eighteen), so the answer does not depend on units or on how stiff one member is
  next to another, and needs no OpenSees. It is a linear, small-displacement test:
  it does not see gaps, cables or sliders, and a part above 3000 free DOF is
  skipped with a note (`OPENSEES_STUDIO_STABILITY_MAX_DOF` raises the limit).
  **Run now does the same check on its way in**: errors stop at the list with
  *Run anyway* (Cancel is the default button), and warnings are written to the
  console without interrupting. Mechanism counts were checked against the rank of
  an independently built compatibility matrix on truss grids of up to 3280 free
  DOF, and all 31 shipped examples pass without a finding.
- **Constant time series** (Define → Time Series → Constant…). A single-value
  series for loads and support motions that do not change with time.
- **Initial-tangent algorithms.** Static, transient and pushover cases offer
  Newton and ModifiedNewton with `-initial`.
- **Preload cases for pushover and transient.** The case forms choose the
  static cases solved before the main analysis and their execution order.

### Changed

- **Upstream integration (PRs #16–#18).** `upstream/main` is merged into the
  fork: point loads inside frame elements, the correction solve that lets a
  force-based frame see its element loads in a Linear first step, the Newton
  increment-test fix, the 2D truss scratch-matrix fix and modal damping now
  share history with upstream. The fork already shipped these behaviours; the
  merge keeps its implementations, so saved models are unchanged.

## [0.0.29] - 2026-10-25

### Added

- **Isolate Selected** in the View menu and the model's right-click menu. It
  shows only the selected elements and their joints, or the selected joints
  when no element is selected. **Show All Objects** restores the viewport and
  is also offered in the selection menu while a filter is active.

### Fixed

- **A selection box no longer picks hidden objects.** Hidden nodes and elements
  are excluded from box selection, so a drag selects only what is actually
  drawn in that viewport.

## [0.0.28] - 2026-10-25

### Fixed

- **Stability check no longer rejects a valid PythonSparse CSR matrix.** Some
  OpenSees builds report the allocated `nnz` while the CSR `index_ptr` ends at
  the stored entries. The check now treats the pointer as authoritative, uses
  the corresponding prefix and reports the difference as a note instead of
  stopping with `invalid CSR index pointer`. OpenSees integer buffers are read
  as either 32-bit or 64-bit.
- **Ungrounded components are diagnosed quickly.** For a connected component
  with no restraint or grounded spring, the check verifies a rigid-body
  translation against `K`. If the residual is zero it reports the component as a
  mechanism and marks the report partial, because the remaining stiffness was
  not searched; it no longer spends minutes in a sparse eigensolver that cannot
  converge on the singular matrix.

## [0.0.27] - 2026-10-25

### Added

- **Stability check phases, cancellation and reproducible benchmarks.**
  `Analyze → Check Model Stability` streams `precheck`, `build`, `capture`,
  `diagnose` and `reconstruct` phases to the console, and **Analyze → Cancel
  Stability Check** stops the child. The GUI applies a soft 300 s limit and a
  hard parent deadline; the service also accepts a timeout and cancellation
  callback between phases and returns a `completion="cancelled"` report instead
  of calling the model unstable. Mechanism vectors are expanded from the
  independent DOFs back to constrained nodes for equalDOF, rigid links and
  diaphragms, so the selected joints include slave nodes. `tools/stability_bench.py`
  builds reproducible frame and truss grids (stable and mechanism variants) and
  reports equations, `nnz`, timings, method and memory.

## [0.0.26] - 2026-10-25

### Added

- **Scalable stability check.** `Analyze → Check Model Stability` now captures
  the initial stiffness as a sparse CSR matrix through OpenSees'
  `PythonSparse`, instead of assembling a dense matrix and reading it with
  `printA`. Models up to 1 200 equations still use a dense symmetric reference;
  larger models use a diagonally scaled, shifted sparse eigenvalue search. The
  report distinguishes complete, partial, unsupported and error runs, separates
  mechanisms from negative stiffness and ill-conditioning, reports `nnz`,
  scaling, tolerances, residuals, timings, memory estimates and the model
  fingerprint, and keeps old reports readable. The connectivity precheck only
  warns about components without a restraint or grounded spring; it never calls
  them unstable by itself. `scipy` is now part of the `opensees` extra (the
  desktop extra already used it for PyNite).

- **Opt-in performance diagnostics for large models.** Start with `--profile`,
  `OPENSEES_STUDIO_PERF=1` or **Help → Performance monitor**. The monitor times
  the SAP2000 importer (`s2k.*`), project I/O (`persistence.*`), analysis build
  and case (`analysis.*`), scene construction (`render.*`), undoable commands
  and UI imports, and reports count/last/total/p95/max per stage together with
  model gauges, process memory and Qt event-loop stalls. **Profile next action**
  runs the next operation under `cProfile`; **Save JSON** / **Copy JSON** export
  the report for an issue. `--perf-json PATH` writes it on exit. The monitor is
  off by default, so normal work pays only a boolean check per boundary.
- **`tools/perf_bench.py`** measures synthetic grid models from 32 to 4 000
  nodes end to end: project build, renderer build, save/load and an optional
  static solve, with `--profile`, `--cprofile` and `--json`. It complements the
  renderer-only budget in `tools/render_bench.py`.
- **`docs/performance-profiling.md`** explains the stage names, the JSON report,
  the benchmark and how to interpret a profile. The Help menu has a matching
  page.

- **Screen-relative model markers.** Node markers, supports, load arrows,
  reactions and joint masses are sized as a percentage of the viewport height,
  with the camera conversion applied so they keep the same on-screen size while
  zooming. The main viewport stores the percentages (`node_size_percent`,
  `support_size_percent`, `load_size_percent`, `reaction_size_percent`,
  `mass_size_percent`) and a separate `label_size_px` in `ViewSettings`; **Display
  → Display Options** edits them, and they travel with the project. Nodes are now
  one point per joint drawn as screen-space spheres (no per-node glyph
  geometry), so selection recolours the point cloud without rebuilding an actor.
  A camera-settled timer rebuilds only the support/load/reaction/mass overlays,
  not the whole scene. Joint masses are a new, off-by-default purple-diamond
  marker.
- **Faster load rendering on large models.** Building load arrows no longer
  scans the whole element and node lists for every member load (id maps are
  built once per render), and the batched arrow template uses a lower-resolution
  8-sided tip/shaft. On the benchmark's 1 568-node / 4 284-frame grid,
  `render.loads` drops from ~2.0 s to ~0.6 s and the whole `--size large` run
  from ~7.2 s to ~3.0 s. Camera refreshes also skip rebuilds below a 2 %
  screen-size change, so a wheel zoom does not rebuild every glyph burst.
- **Independent frame-release markers.** End releases are drawn as screen-space
  colored dots on the bar ends: violet for torsion, orange for M2, red for M3,
  and yellow for partial fixity. Multiple releases at one end are staggered
  along the member so each color is visible. **View → Visibility → Releases**
  toggles them without hiding the rigid offset bars, which stay under **Frame
  Assignments**. The dots are cheap points, not sphere glyphs.

## [0.0.25] - 2026-10-24

### Added

- **SAP2000 text import and export: rigid diaphragms.**
  `CONSTRAINT DEFINITIONS - DIAPHRAGM` and `JOINT CONSTRAINT ASSIGNMENTS`
  become `RigidDiaphragm`s, and the export writes both tables back. SAP2000's
  floating centre-of-mass joint (the one that usually carries the floor's added
  mass and has no element) is used as the retained node, so the runner fixes
  its out-of-plane DOFs automatically; choosing a real floor joint would leave
  that mass-only joint singular. Supports are left out of the floor (OpenSees
  would silently ignore them), and 2D, multi-level and out-of-plane cases are
  counted in the report. This unblocks SAP2000's 1-024/1-025: their modal
  periods now match to 3e-6 and 9e-7 relative, 1-024's CQC/SRSS peak
  translations to 5e-7 absolute (2.4e-5 relative) and its reactions to 3.5e-6
  absolute; both previously failed with a singular stiffness matrix.

- **SAP2000 text import and export: frame property modifiers.**
  `FRAME PROPERTY MODIFIERS` (`AMod`, `AS2Mod`, `AS3Mod`, `JMod`, `I22Mod`,
  `I33Mod`, `MassMod`, `WeightMod`) now reaches each frame's `FrameModifiers`,
  mapped to this program's local axes, and the export writes the table back.
  A shear-area multiplier of 0 is accepted and turns shear deformation off
  (Euler-Bernoulli instead of `ElasticTimoshenkoBeam`); zero A, J, I22 or I33
  is reported rather than turned into a mechanism. On a nonprismatic frame the
  segment sections' own shear areas govern, matching SAP2000's stored results
  for 1-006a/b (whose table asks for zero shear but whose results keep it).
  The 68-file example set still imports in full; the comparison no longer marks
  those two models incomplete for this table.

- **Nonprismatic (tapered) sections, in the Section Library and the SAP2000
  import.** A `NonprismaticSection` is a template of segments between prismatic
  elastic sections, each with an absolute or relative length and a linear,
  parabolic or cubic variation, plus a user-editable subdivision count (minimum
  and default 12). Assigning it subdivides each selected member into that many
  ordinary elastic beam-columns, interpolating the section at every piece
  (rectangle/I/pipe/tube dimensions are interpolated, so a depth taper follows
  its true cubic inertia), copying the member's end releases, offsets, insertion
  and modifiers, scaling its mass per length and splitting its uniform,
  trapezoidal, point and temperature loads. The Section Library edits the
  template and refreshes the pieces already built from it; a changed subdivision
  count keeps their existing piece count, so choose it before assigning. The
  SAP2000 import reads `FRAME SECTION PROPERTIES
  05 - NONPRISMATIC` in the file's segment order, asks for the piece count, and
  materialises the members. Validated locally against SAP2000's 1-006a/b: the
  tip displacements under the example loads agree to 0.05-2.8% with 12 pieces,
  where the previous "start section" approximation was 10-12% off.

- **SAP2000 text import: temperature loads, support settlements, frame added
  mass and preloaded static cases.**
  `FRAME LOADS - TEMPERATURE` becomes a `TemperatureLoad` with the material's
  `A1`: the uniform change, a joint-pattern variation along the member (its mean
  is used) and a gradient per unit length. `JOINT LOADS - GROUND DISPLACEMENT`
  becomes an `ImposedDisplacement` on a restrained DOF; on a free or
  spring-supported DOF it is counted in the report, because this program's
  support spring has a fixed ground end. `FRAME ADDED MASS ASSIGNMENTS` is added
  to the element's mass per length. A static case whose `InitialCond` names
  another imported static case gets it as `preload_case_ids` (a new additive
  field, omitted at its default, so existing files save unchanged) and the export
  writes the name back. Found in SAP2000's example set: the six 1-002 temperature
  cases match to 1e-16, the two restrained settlements (1-005a/c) to 5e-7 and
  1-021's modal periods exactly.

- **SAP2000 text import and export: response-spectrum cases.** A `LinRespSpec`
  case with a CQC or SRSS `ModalCombo` becomes a `ResponseSpectrumCase` on the
  file's first modal case, with its `U1..R3` direction, its `ConstDamp` and the
  tabulated `FUNCTION - RESPONSE SPECTRUM - USER` as a project spectrum.
  `TransAccSF` takes the ordinates to the project units and a `T = 0` point is
  read as `1e-6 s`; `ABS` and "10 Percent" combinations, more than one direction,
  a non-zero angle, accidental eccentricity and a second scale factor are counted
  in the report. The export writes the three tables back. The four example files
  with ten spectrum cases import (two of the ten are the ABS/10 Percent ones,
  reported instead of guessed); the 68-file set still imports in full.

- **SAP2000 text import and export: eigen modal cases.** A `LinModal` case whose
  `CASE - MODAL 1 - GENERAL` row is `ModeType=Eigen` becomes a modal case asking
  for its `MaxNumModes`, with the solver left on this program's automatic
  routing (dense at or below 500 free DOF, ARPACK above), and the export writes
  both tables back. Other modal types, and a modal case with no general row, are
  counted in the report. Sixteen files of SAP2000's 68-file example set carry an
  eigen modal case and now import it; the five that still have no runnable case
  hold spectral, buckling, history, staged or nonlinear ones.

- **SAP2000 text import and export: added joint masses and support springs.**
  `JOINT ADDED MASS ASSIGNMENTS` (`Mass1..3`, `MMI1..3`) and `JOINT SPRING
  ASSIGNMENTS 1 - UNCOUPLED` (`U1..3`, `R1..3`, springs to ground) now reach
  `Node.mass` and `Node.spring`, scaled by their dimension to the project units,
  and the export writes both tables back, so a mass-and-spring model round-trips.
  The file's `MASS SOURCE` decides whether added masses count, and is reported
  when it excludes element mass or asks for load mass; a 2D model keeps the
  in-plane components and reports the rest; a file with rotated joint local axes
  reports those rows instead of turning them silently. The export now also
  reports a project mass source, which it cannot write.

### Documentation

- **The SAP2000 text import remains a work in progress.** Its status, the
  tables it reads, the known approximations and the unsupported objects are
  documented in `docs/sap2000-import-status.md`, linked from both READMEs and
  from the in-application help. The import report on each file remains the
  authoritative list of what was left out.

### Fixed

- **SAP2000 text import: real-world section definitions no longer stop a file.**
  A 2D frame with `I22 = 0` and `J = 0` (the out-of-plane zeros SAP2000 writes)
  imports, with the in-plane inertia checked per member instead of demanding
  both; a 3D section whose torsional constant is 0 gets a small one, counted in
  the report, because OpenSees needs torsional stiffness; and a `Nonprismatic`
  section no longer stops the file (it is subdivided into elastic pieces, as
  described above). Found importing SAP2000's own `Example 1-006`, `1-021`,
  `1-022` and `1-024` models: 5 of 68 example files used to be refused, all 68
  now import.

- **SAP2000 text import: a damaged file is refused with a message that names the
  table and the line, not with a crash or a hang.** A joint or frame name that
  CPython cannot read as an integer (4 300+ digits, or a character such as `²`
  that `isdigit` accepts) is numbered instead of raising `ValueError`; an area
  whose `NumJoints` is not 4 no longer drives a billion-iteration loop; a file
  with no joints is refused instead of opened as an empty project; and a line
  inside a table that is not a `Key=Value` record is counted in the import
  report instead of disappearing. A truncated or corrupted file now always
  reaches the caller as `Sap2000TextError`, and exporting a project twice writes
  the same bytes; both are pinned by tests.

## [0.0.24] — 2026-10-23

Batch analysis and SAP2000 interoperability: File → Run Batch… solves many
projects unattended and keeps their results to open later, and SAP2000 text
files (.s2k / .$2k) can be imported and exported.

### Added

- **File → Run Batch…: solve many projects unattended and view the results
  later.** Add files or a folder, pick all cases or cases by name, choose how
  many files solve at the same time, and follow a progress row per file (with
  Cancel). Each project keeps its results beside it
  (`<project>_batch_results/` and `<project>_results.sqlite`), and File → Open
  offers to load them without running again while the model is unchanged. A
  summary with the status, time and error of each file is written as
  `batch_summary.json` and `batch_summary.csv`. The same from a terminal:
  `python -m opensees_studio.batch models/ --cases all --jobs 4` (`--batch` in a
  packaged build). The engine chosen in Options → Solver solves every file.
- **File → Import → SAP2000 Text (.s2k / .$2k) and File → Export → SAP2000
  Text.** Reads a model saved as SAP2000 text tables as a new project: joints and
  restraints, global grid lines, frames with their sections (rectangular, I,
  pipe, box/tube and general, with property modifiers), materials, local-axis
  angles, end releases and partial fixity, load patterns with their self weight,
  joint forces, distributed (uniform, trapezoidal, partial, projected) and point
  frame loads, linear static cases (a pattern used with a factor becomes a scaled
  copy), combinations, and four-node shells. Values are scaled from the file's
  `CurrUnits` to the nearest unit system, a frame in the X-Z plane with only UX,
  UZ and RY active becomes a 2D model, and SAP2000's local 2 and 3 are mapped
  onto OpenSees' axes per member. Tables it does not read are listed by name in
  the log. The export writes the same tables, so an exported file imports back
  to the same model, and reports what it leaves out. Written from the text
  format alone, without CSI software; SAP2000 is a trademark of Computers and
  Structures, Inc.

## [0.0.23] — 2026-10-23

Display and editing tools: the view rotates a step at a time or spins, members
and shells can be coloured by section, material or group, loads can be deleted
by type, and Show Extruded Sections draws each member's real cross section. New
modelling: reinforced concrete walls as MVLEM macro-elements and the ConcreteCM
(Chang-Mander) concrete law.

### Added

- **Edit → Delete Loads.** Removes loads by type — joint forces, imposed
  displacements, uniform, trapezoidal and point frame loads, temperature loads,
  shell pressures, floor loads, and the self weight — from the chosen load
  patterns, on the selection (through its joints and elements) or the whole
  model. Each type shows how many it would remove before you accept; one undo
  step brings them all back.
- **View → Color By: paint frames and shells by section, by material or by
  group.** Each category gets its own colour (groups keep the colour they were
  given in Define → Groups) and a legend in the viewport's corner names them.
  Material follows the section's fibres, so a reinforced-concrete member reads
  "concrete + steel"; members with no section, material or group keep the
  ordinary colour. The selection still shows on top. Saved with the project's
  view settings; a project that keeps a single colour saves byte-identical.
- **View → Rotate, and rotate buttons in the View toolbar.** Rotate Left / Right
  (Alt+Left / Alt+Right) turn the point of view 15° about the vertical axis, Tilt
  Up / Down (Alt+Up / Alt+Down) 15° about the horizontal screen axis, and Spin
  keeps it turning to present the model until switched off. Only the camera
  moves; turning it leaves a plan or elevation view, as Isometric does.
- **Assign → Frame → RC Wall (MVLEM).** The selected vertical members of a 2D
  model become OpenSees `MVLEM` reinforced concrete wall segments: vertical
  fibres of concrete and steel across the wall length (with optional boundary
  elements of their own steel ratio) and a shear spring, created per segment
  height with the stiffness `G L t / h` or taken from an existing material. A
  stack of segments converges to the elastic cantilever's flexure plus shear
  (40 segments: 1 %), and a reinforced wall softens once its boundary steel
  yields. `.osmodel`: a new element type `MVLEM`. gidopensees' `FiberInt`
  shear-flexure section, which this replaces in the gap analysis, does not
  exist in OpenSeesPy 3.8.
- **`ConcreteCM` (Chang-Mander) concrete.** In the Material Library, and as the
  Concrete Section Wizard's new **Concrete law** option: cover and core become
  `ConcreteCM`, the core with Mander's `f'cc`, `εcc` and the `r` that makes
  Tsai's envelope Mander's curve (pinned against the closed form to 0.2 %).

### Changed

- **View → Show Extruded Sections draws the real cross section** instead of a
  box: AISC shapes as their profile (I, channel, tee, rectangular and round
  tube, angle), fibre sections as their patches, a truss as the bar of its
  area, anything else as the rectangle with the same area and second moments.
  The section stands in the member's OpenSees local axes (an AISC beam in a 3D
  model used to lie on its side) and sits on its insertion point. An AISC section now stores its
  profile in project units (I, channel, tee and rectangular tube are new; an
  HSS was stored as a solid rectangle), so the member size used by insertion
  points, end offsets from connectivity and the IFC export is the real one.
- **`ElasticPPGap` refuses `Fy` and `gap` of opposite signs.** OpenSees accepts
  them with a warning and then follows neither the tension nor the compression
  gap law; a tension gap takes both positive, a compression gap both negative.
  The laws of `ElasticPPGap`, `Viscous` and `ViscousDamper` are now pinned by
  tests (a strain path for the gap, a damped oscillator for the dashpots), and
  the Material Library help says that a dashpot acts only in a transient case
  and how stiff a `ViscousDamper` spring can be before its integrator fails.

## [0.0.22] — 2026-10-22

A second engine ships with the application: PyNite (MIT) runs linear static
and P-Delta cases of elastic frames and trusses with no download, giving the
same results as OpenSeesPy on those models, and Options → Solver chooses which
engine runs the cases. Also fixed: a stale pre-run snapshot after New / Open,
and truss forces that leaked from one OpenSees model into the next one solved
in the same process.

### Added

- **PyNite, a second engine that ships with OpenSees Studio** (MIT, no
  download). Options → Solver → Engine → PyNite runs linear static cases of
  elastic frames and trusses — nodal, uniform, trapezoidal, floor and point
  loads, self weight, releases, support springs — and P-Delta when a member
  uses the PDelta transformation. Its results come back in the same layout as
  OpenSeesPy's and match them to rounding on those models (checked by the test
  suite); anything it does not model is refused with a message naming it. The
  bundle grows by about 140 MB (scipy).
- **Choose the engine that runs the analyses** (Options → Solver → Engine). The
  analysis process now runs the cases with the engine chosen there instead of
  always with OpenSeesPy, so an engine installed as a Python package (the
  `opensees_studio.engines` entry point) solves without changes to OpenSees
  Studio. A case of a type the engine does not run is refused before anything is
  solved, with a message naming what it does run. The stability check and the
  Material Tester keep using OpenSeesPy whatever the engine.

### Fixed

- **Opening another project no longer leaves a stale pre-run snapshot
  behind.** File → Open and File → New now remove the snapshot of the project
  they replace, as save and close already did, so reopening a project that was
  run and left with nothing unsaved no longer offers to restore it. Cancelling
  the unsaved-changes prompt or the file dialog, or a file that fails to load,
  keeps the snapshot.
- **A 2D frame model (three DOFs per node) with `truss` members no longer
  inherits forces from a 3D truss model solved earlier in the same process.**
  OpenSees' `truss` shares its force vector and stiffness matrix between 3D
  models with three DOFs and 2D models with three, and in 2D leaves their
  rotation rows untouched, so the earlier model's last bar force came back as
  moment reactions at truss joints and, where a frame joint is free to rotate,
  as a spurious moment and stiffness that changed the displacements. The
  runner now clears them before building such a model. A normal analysis runs
  one project per process, so it showed up mainly in scripts, tests, the
  in-process mode (`OPENSEES_STUDIO_IN_PROCESS=1`) and Check Stability.

## [0.0.21] — 2026-10-22

Models come in from PORTICO and go out designed: File → Import → PORTICO Model
reads `.s3d` files scaled to the project's units; the new Design menu checks
steel members against AISC 360-16 (I-shapes, channels, tees, angles, HSS and
pipes), paints them by their ratio and checks storey drifts; influence lines,
moving loads and temperature loads join the analyses; the Concrete Section
Wizard and the Section Designer build any section; and a generated Verification
Manual compares every result family with closed-form and published solutions.

### Added

- **Define → Section Designer.** Draw any cross-section with a command line —
  `rect`, `circle`, `poly`, `ishape`, `channel`, `tee`, `angle`, `tube`, `pipe`,
  `hole …`, `move`, `delete`, `center`, with Undo — or import the closed
  outlines of a DXF (polylines with arcs, circles, ellipses, splines; an outline
  inside another is a hole; scaled by `$INSUNITS` and centred). It shows the
  area, centroid, Iz, Iy, Iyz, principal moments and angle, elastic and plastic
  moduli and the Saint-Venant torsional constant, solved by finite differences
  on Prandtl's stress function with boundary-fitted coefficients (hollow shapes
  included), and warns when regions overlap. OK adds an elastic section (E, ν,
  editable J) or a fiber section of one uniaxial material.

- **Define → Concrete Section Wizard.** A rectangular, circular, T or L
  reinforced concrete section from its dimensions, clear cover, metric or US bar
  sizes and counts, ties and strengths, drawn as you type. It adds the cover and
  core concrete (`Concrete02`; the core confined after Mander, Priestley and Park
  when asked), the bars (`Steel02`), a fiber section and, optionally, an elastic
  section with the ACI 318-19 cracked inertia (0.70 Ig for columns, 0.35 Ig for
  beams), all in one undo step.

- **Steel frame check: channels, tees, angles, HSS and pipes.** Design → Steel
  Frame Check now covers C and MC channels (E4 flexural-torsional buckling, F2,
  F6, G2, G6), WT, MT and ST tees (F9, stem as an unstiffened element), equal-leg
  angles (E3 about z, E4, F10, G3), rectangular HSS (E7 walls, F7 with the
  effective section modulus and lateral-torsional buckling, G4) and round HSS and
  pipes (E7-6, F8, G5). Section names are matched whatever their case and
  whether they write `.` and `/` or the table's `_`. Unequal-leg angles stay not
  designed.

- **Design → Display Steel Ratios on Model.** Paints every frame member by its
  governing AISC 360-16 ratio (blue, teal, green, orange up to the limit, red
  above it, grey when not designed) with the ratio at mid-length, and a panel
  with the legend, the summary and Select failing members. The Steel Frame Check
  dialog gains **Show ratios on the model**. The calculation report (File →
  Export → Report) prints the steel check and the storey drifts when the project
  has design settings.

- **Temperature loads on frames** (Assign → Frame → Temperature Load). A uniform
  temperature change and a gradient across local y and z, with the coefficient of
  expansion α, on elastic members without releases or end offsets, in static
  cases. The members' fixed-end forces are applied to the joints with the
  opposite sign and added back to their end forces, so a free member grows α ΔT L
  or bends to α g with no force, and a held one carries EA α ΔT and EI α g
  (Verification Manual V-17). Mesh, Replicate and Merge Joints carry the loads;
  other case types refuse a pattern that has them. PORTICO member temperature
  loads are imported with their material's α. `.osmodel`: an optional
  `temperature_loads` list on plain patterns, absent when empty.

- **Influence lines and moving loads.** A new analysis case type,
  *InfluenceLine* (Analyze → Cases…), walks a load (a unit load downward by
  default) along a chain of frame members, stopping at equal intervals of each,
  and solves the model once per stop: the result keeps every displacement,
  reaction and member end force at every stop, through the analysis CLI and the
  result store like any case. **Display → Influence Line** plots any of them per
  unit load against the distance along the path and moves a vehicle — axle loads
  and their offsets, stored on the case — across it in both directions, reporting
  the largest and smallest effect and where the front axle stood. Verified
  against Müller-Breslau on a two-span continuous beam (Verification Manual
  V-16). New example `bridge_influence_line` (three-span girder, HL-93 truck).

- **Tutorials, in English and Spanish** (`docs/tutorials/`): designing a steel
  moment frame with the AISC check and the drift check, a building with rigid
  floors (modes, CQC spectrum, NCh433 drift), and importing a PORTICO model. Their
  dialog screenshots are generated from the current code by
  `tools/tutorial_screenshots.py`.
- **`README.es.md`**, a Spanish overview of the README, linked from it.
- **Example `steel_frame_design`**: a two-bay, two-storey frame of AISC W shapes
  with three combinations and design settings, for the steel check.
- **Design → Steel Frame Check (AISC 360-16).** LRFD or ASD ratios of every frame
  member whose section is an AISC W, M, S or HP shape (by its name, or named per
  member): tension yielding (D2), flexural and torsional buckling with the
  effective area of slender elements (E3, E4, E7), major-axis flexure with
  lateral-torsional buckling and flange local buckling (F2, F3), minor-axis
  flexure (F6), shear (G2.1, G6) and the H1-1 interaction. Demands come from the
  results already run in the session, at 25 stations per member with span loads;
  Linear Add and Envelope combinations are expanded into their cases and a
  response spectrum case enters as ± its peak. Cb comes from the moment diagram
  (F1-1) unless set; K, the unbraced length and Cb can be overridden per member.
  The table shows the governing ratio, check, equation and load set, and
  **Select failing members** selects them. Verified against the AISC Design
  Examples E.1A, F.1-1A, F.1-2A, G.1A and H.1A (Verification Manual D-01 to D-05).
- **Design → Storey Drift Check.** Storey drift ratios of the static and response
  spectrum results, times an amplification (Cd / Ie for ASCE 7), against an
  allowable ratio, with ASCE 7-22, NCh433 and Eurocode 8 presets.
- **`.osmodel`: `design`.** The check settings (method, Fy, load sets, member
  overrides, drift limit) are saved in an optional `design` object. A project that
  never opened the Design menu saves byte-identical, and editing the settings
  does not make results stale.

- **Verification Manual** (`docs/verification-manual.md`). Twenty-two cases with a
  closed-form or published reference — cantilevers, simply supported and
  fixed-fixed beams, a Timoshenko beam, 3D biaxial bending and torsion, a two-bar
  truss, a support settlement, P-Δ, SDOF and cantilever frequencies, a step load
  in time history, a response spectrum, a simply supported plate and the plastic
  moment of a fibre section, plus the AISC 360-16 design examples E.1A, F.1, G.1A
  and H.1A and an end-to-end beam check — each with the computed value, the reference, the
  relative error and its tolerance. It is generated from real runs by
  `tools/verification_manual.py`, and the integration suite fails when a case
  leaves its tolerance or the manual is out of date.

- **File → Import → PORTICO Model (.s3d).** Opens a model saved by PORTICO
  (`jpreyes/portico-core`) as a new, unsaved project. Nodes, supports, support
  springs, nodal masses, frame members, sections (with PORTICO's section
  modifiers applied), end releases and end springs, static load cases (nodal,
  uniform and trapezoidal loads, self weight), prescribed support
  displacements, combinations and grid lines come across. The dialog reads the
  file's unit system from its `units` label and scales **every** value to the
  project units you pick, by dimension: a `kN-m` file opened in SI metres has
  its forces in newtons and its densities in kg/m³. PORTICO gives a beam its
  local y up and OpenSees its local z, so each member's `Iz`/`Iy`, shear areas
  and bending releases are swapped where needed and distributed loads are
  re-projected onto the OpenSees axes. Quadrilateral areas become `ShellMITC4`,
  diaphragms become rigid diaphragms on PORTICO's master node (the floor mass
  spread over its nodes), rigid links become `rigidLink`s and the other links
  equalDOFs, the mass source comes along, and cable and compression-only
  members become trusses that go slack on the other side (their static cases
  run with Newton; SAP2000 Example 1-012 reproduced). Triangular areas, temperature
  loads and response spectrum cases are not imported yet; the dialog and the
  log count them. PORTICO's own verification models (support settlement, link
  offset, static portal, modal cantilever, Bathe–Wilson frame) solve to the same
  numbers as its published OpenSeesPy runs, to 1e-10.

### Fixed

- The README no longer says the desktop bundle includes OpenSees: since 0.0.20 the
  solver is installed from Options → Solver.

## [0.0.20] — 2026-10-21

The solver becomes a separate download, and the model gets connected and
weighed: OpenSeesPy is no longer shipped inside OpenSees Studio (it has its own
license) and is installed from Options → Solver; every member with a unit
weight carries its self weight; and Merge Joints and Divide Frames at Joints
repair a model that only looks connected.

### Changed

- **The solver is optional: OpenSeesPy is no longer a base dependency.** It is a
  separate program with its own license (free for research, education and
  internal use; commercial redistribution needs a license from its authors), so
  `pip install opensees-studio` now installs the modeller and
  `pip install opensees-studio[opensees]` adds the solver (`dev` includes it).
  Without a solver the application models, exports and reports; Run, the batch
  runs, Check Model Stability and the Material Tester are disabled and say why,
  and the log says at start which solver was found.
- **The desktop bundle no longer includes OpenSeesPy** (about 250 MB lighter
  unpacked on Linux). Install it once from Options → Solver.

### Added

- **Options → Solver.** Shows whether OpenSeesPy is available and which version,
  and points to it: the application's own environment, another Python 3.12 that
  has `openseespy` (the application asks that interpreter where it is, without
  starting OpenSees), or a folder holding the package. The choice is saved in
  `solver.json` in the application data directory. **Download OpenSeesPy from
  PyPI**: shows its license and downloads only after you accept it; fetches the
  two files published for the platform (Linux x86-64, Windows, macOS arm64),
  checks each against its pinned SHA256, unpacks into the application data
  folder and selects it, with progress and Cancel. Other solvers can register as
  Python packages (`opensees_studio.engines` entry point;
  `docs/adr/ADR-0003-solver-engines.md`).
- **Edit → Merge Joints.** Joints closer than a tolerance (a thousandth of the
  model's size to start with) become one: on the selected joints only or on the
  whole model. The lowest id stays; elements, loads, constraints and groups move
  to it, restraints are combined and different masses added, members that end up
  repeated are removed, and joints joined on purpose (zero-length element,
  equalDOF, rigid link, diaphragm) are left alone. The dialog says what will
  merge before you accept; one undo step.
- **Edit → Divide Frames at Joints.** Splits every frame and truss (or the
  selected ones) at the joints lying inside it, and optionally where members
  cross, so a column standing on a beam mid-span is connected to it. Loads follow
  the pieces. The dialog also reports loose joints and joints on a shell edge.
- **Select → Loose Joints, Joints Inside Members, Joints on Shell Edges.**
- **Self weight of every member with a unit weight.** Fiber sections have a unit
  weight applied to their gross area (patches, bars and loose fibres); an
  aggregator weighs what the section it wraps weighs; trusses and BeamWithHinges
  members carry their own unit weight (editable in the Properties panel, on one
  member or many). A truss bar sends half its weight to each joint. The truss
  wizard and Draw Truss give new bars steel's unit weight, and Assign → Frame →
  Hinge keeps the member's weight per length. Members without a unit weight save
  byte-identical.

### Fixed

- **Edit → Mesh could split a zero-length element, a bearing or a link** at a
  joint lying between its two nodes. Only frames and trusses are split now.
- **The fiber section editor dropped a section's loose fibres** when it was
  edited; they are kept.

## [0.0.19] — 2026-10-17

Selection and results, from the way you pick things to the way you read them: a
left-drag box, clicks that accumulate, transforming members instead of their
joints, the node reactions as a table and as a drawing, and a Case selector in
the toolbar so a run of four cases is four clicks away.

### Added

- **A Case selector in the toolbar.** Next to Level, it lists the cases that hold
  results for the model, with name and kind (`DEAD · Static`,
  `RSX-CQC · ResponseSpectrum`). Choosing one repoints the whole window — caption,
  panels, reactions and action states — so the deformed shape, the diagram and
  the overlay cannot disagree about the case.
  The step arrows (◀ ▶, `Step 12/40`) are in place but disabled until a layer
  registers how to redraw itself at another step.

- **The version, in the title bar.** The window is `OpenSees Studio v0.0.18`, so
  a screenshot says which build produced it — the same reason the console now
  prints the version on startup.
- **Node reactions, as a table and as a drawing.** The **Reactions** tab, next to
  Console and Results, lists Fx, Fy, Fz, Mx, My and Mz of every restrained node
  in the case on screen; *Display → Show Reactions* draws a force arrow and a
  moment circle at each of them, proportional to the largest value of that case,
  and *Display → Reactions Table* raises the tab. The table and the drawing
  share one function, so a number and the picture cannot disagree.

### Changed

- **Clicking accumulates, Ctrl removes.** A click used to replace the selection
  unless Ctrl was held; it now adds, so a selection is built by clicking, and
  Ctrl+click takes an item out. Clicking empty space still clears everything.
- **A left drag draws a selection box.** Dragged downwards it takes only what is
  fully inside (joints, members and shells whose joints are all inside); dragged
  upwards it also takes whatever the box touches, so a member that crosses it is
  picked. Ctrl+drag subtracts. The camera turns with a middle-button drag,
  because the left button is the box; the wheel still zooms.
- **Move, Replicate and Mirror accept a frame selection.** They required
  selected nodes, so the element-first workflow — select the members, transform
  them — found the three commands disabled. A member now brings its joints, and
  the actions enable on any selection. A joint shared with an unselected member
  moves too; that member follows its joint, as in a frame program.
- **Selecting a node no longer rebuilds the whole glyph.** `update_selection`
  re-ran the glyph filter over every node sphere on each click; it now writes
  the state array onto the existing glyph, repeated by its stride — 39 ms to
  0.2 ms on 4.840 nodes.
- **Load arrows batch into three actors.** A pattern that loads every joint and
  every member drew one actor per arrow — 1.374 draw calls and 2.1 s to build on
  a 108-node model. The arrows now go into three point clouds (nodal, element,
  point) that a single glyph places, rotates and scales: 8 actors and 54 ms.
  The geometry is pinned by tests on the resulting bounds, so a tip that stops
  landing on its joint fails the suite.

## [0.0.18] — 2026-10-17

A render performance pass, measured before it was optimised. A model of 1.5k
nodes and 4.3k members now builds in ~51 ms with 7 draw calls, down from 606 ms
and 202; a supported 500-node model went from 292 ms to 21 ms. The roadmap
target — 10k nodes / 20k frames at 30 fps — is not reached yet, and the roadmap
lists what is left.

### Added

- **`tools/render_bench.py` and a render budget.** The benchmark builds
  synthetic node/frame grids and measures the geometry build and the number of
  actors without opening a GPU context, so it runs in CI. `tools/render-budget.txt`
  records the ceilings and `tests/tools/test_render_budget.py` fails when one is
  exceeded: the actor count is exact, the time ceilings carry margin for a busy
  runner.

### Changed

- **Frame assignments no longer validate a pydantic model per member.**
  `_Options.is_default()` built a throwaway model and compared it with `==` —
  27k calls on a 13.6k-member model, 241 ms of the 269 ms base render. It now
  compares against a per-class cached field dict: 606 → 446 ms on 1.5k nodes /
  4.3k frames.
- **Supports and section extrusions batch their geometry.** One actor per
  support kind instead of one per restrained joint, and a single merged
  `UnstructuredGrid` for the extrusion overlay: 202 → 7 actors and 492 → 71 ms
  on the same model.
- **The joint marker is cached and lighter.** Its sphere template is built once
  per radius and drops from 8×8 to 6×6: 76 → 51 ms on the same model.

### Known limitations

- Loads still draw one actor per arrow, `update_selection` re-glyphs the whole
  node cloud on every selection change, and every edit rebuilds all categories.
  Those three are the next steps of the pass, listed in the roadmap.

## [0.0.17] — 2026-10-17

### Added

- **Wait cursor while the application works.** Starting the application, opening
  a project, running an analysis or the stability check, and exporting an
  animation now show the wait cursor until the window is ready again. The status
  bar says what is happening, and the cursor is restored even when the operation
  fails. Nested waits are counted, so one finishing early cannot clear it while
  another is still running.

### Fixed

- **Analyze → Run All Cases and Run Selected Cases came back disabled after a
  run.** The window refreshed its menus on the runner's `finished` signal, which
  fires while the run still reports itself as running; the flag only drops in
  the teardown that follows, and nothing listened to it. The menu state now
  refreshes on `runningChanged` too.

## [0.0.16] — 2026-10-17

### Added

- **Viewport caption.** Every 3D view shows, top-left, which results are on
  screen — the case name and kind, or the combination and whether it is an
  envelope — and nothing when the model itself is shown.
- **Analyze → Delete All Results…** clears the session's results and deletes the
  project's results database, after asking. The model and the cases are
  untouched.

### Changed

- **Re-running a case replaces its results.** The results database keeps one run
  per case instead of an append-only history, so the file always reflects the
  latest run; different cases still coexist.

## [0.0.15] — 2026-10-17

The view toolkit — a second viewport on the same model, per-viewport visibility
switches, hiding and inverting what is drawn, zoom and custom colours — plus a
queryable results database and batch run doors.

### Added

- **View → New View Window** (`Ctrl+Shift+N`): an independent viewport on the
  same model, in its own window, with its own camera, colours and visibility
  switches; the selection is shared, so a joint or element picked in one window
  is highlighted in every window at once.
- **View → Visibility**: one switch per category — grids, grid labels, nodes,
  frames, shells, restraints, constraints, frame assignments, loads, node and
  element labels, extruded sections. Hiding is per viewport and never removes
  anything from the model, so the tree, the analysis and the other windows are
  unaffected.
- **View → Hide Selected** (`Ctrl+H`) and **View → Invert Visible**, plus
  **Hide Selected Elements** in the model view's right-click menu.
- **View → Zoom In** (`Ctrl++`) and **Zoom Out** (`Ctrl+-`), next to Zoom
  Extents.
- **View → Colors…**: the background gradient, node, frame, shell and
  selection-highlight colours, per viewport.
- **Results database.** Every finished case is appended to
  `<project>_results.sqlite` beside the model: one row per node, element and
  step — displacements, reactions, local forces, shell resultants, storey shear,
  section cuts, modal eigenvalues and mode shapes — with an append-only `runs`
  history and indexes on the ids. Load combinations record their two bounds; a
  response spectrum records its peaks; a transient records its HDF5 path and
  indexes the node displacement history. A database that cannot be written is a
  warning, never a failed run.
- **Analyze → Run All Cases** (`Shift+F5`) and **Analyze → Run Selected
  Cases…**, which run the whole model or a ticked subset in one child process.
- The `.osmodel` payload records the primary viewport's display settings under
  `view`, omitted while they are the defaults, so an untouched project still
  saves byte-identical. Window geometry and the default viewport persist
  between sessions.

### Changed

- The menu bar enables only **File** and **Help** until a project is created or
  opened; the rest light up with the first New or Open.

### Fixed

- **Display → Export animation** no longer fails when the viewport height or
  width is odd. libx264 with the `yuv420p` pixel format needs both dimensions
  even, so a 1200×537 window aborted with "height not divisible by 2" and a
  broken pipe; frames are now padded by the one pixel needed.

## [0.0.14] — 2026-10-16

The grids release: radial (cylindrical) grids, a Grid Wizard, labels at the
ends of the grid lines, a Grid Line View that isolates the objects on one grid
line, and a right-click menu on the model view that follows the selection.
Projects that use none of it save exactly as before (schema 3 unchanged).

### Added

- **Radial (cylindrical) grids**: a coordinate system's grid can be Cylindrical —
  rings by radius, radial lines by angle and Z levels. Rings close into circles
  when the radial lines go all the way round; the draw tools and Add Node snap
  to the ring × radial-line crossings.
- **Define → Grid Wizard**: a whole Cartesian or radial grid from the number of
  lines, spacing, first position and naming style (A, B, C / 1, 2, 3 / X1, X2)
  per axis, with a preview; into a new system or replacing an existing grid,
  one undo step.
- **Grid labels** at the ends of the lines: ID, ID + coordinate or coordinate,
  with size and colour, at the Start, End or Both ends (per line, or for every
  line at once).
- **Add Row** in the grid table continues the grid: the new line goes one last
  spacing beyond the last line and takes the next id (X3 → X4, C → D).
- **View → Show Grids / Show Grid Labels** and a **right-click menu** on the
  model view with the same switches, a per-system grid toggle and the grid
  dialogs.
- **View → Grid Line View**: pick a grid line by its label and see only the
  joints within a window either side of it (50 mm by default, adjustable, in
  the model's unit) and the elements on them, face on with that line as the
  working plane; View → Show All Objects brings the rest back. Works for
  Cartesian lines, Z levels, rings and radial lines.
- The **right-click menu follows the selection**: with joints, frames or shells
  selected it lists their Assign options plus group, move, replicate, mirror,
  delete; with nothing selected, the grid and view options.

### Fixed

- **Hide All Grid Lines** (and a line's Visibility) now hide the grid: they were
  saved but the view still drew the lines, and the snap still used them.
- **Assign to Group** moves to Ctrl+Shift+G: it shared Ctrl+G with Coordinate
  System/Grids, so neither shortcut did anything.
- Editing a grid in the grid dialog no longer turns a hidden system visible.

## [0.0.13] — 2026-10-15

The OpenSees-coverage release: after a review of the whole OpenSeesPy manual,
the commands a structural model needs have a form — 24 more materials, links and
the triple friction pendulum, layered shells, formula time series and support
motion, every solver option that runs in OpenSeesPy 3.8 — and anything else can
go into a trusted custom command block. The F1 help gains a menu map and a
glossary of every OpenSeesPy command saying where it lives in the application.
Projects that use none of it save exactly as before (schema 3 unchanged).

### Added

- **24 more uniaxial materials** in the Material Library through one generic form
  in OpenSees order: ReinforcingSteel, Concrete06, Concrete07, ModIMKPeakOriented,
  ModIMKPinching, Bilin, Pinching4, ViscousDamper, BilinearOilDamper, Viscous,
  BoucWen, ElasticBilin, ElasticPPGap, MultiLinear, ElasticMultiLinear, PySimple1,
  TzSimple1, QzSimple1 and the wrappers Parallel, Series, MinMax,
  InitStrainMaterial, InitStressMaterial, Fatigue (emitted after what they wrap;
  the Material Tester runs them with it). Hysteretic and HystereticSM get a form.
  Each is built by the live solver in a test; the wrappers check by closed form.
- **Links** (Assign → Joint → Link): `twoNodeLink` with a material per local
  direction (dampers, gaps, hinge springs) and the **Triple Friction Pendulum**
  isolator (3D).
- **Layered shells**: LayeredShell and PlateFiber sections with the plate
  materials J2Plasticity, PlasticDamageConcretePlaneStress, PlateFiber,
  PlateFromPlaneStress and PlateRebar, checked against the elastic plate. **RC
  templates** (rectangular and circular) in the fibre section editor.
- **Time series and support motion**: Define → Add Function TimeSeries (Constant,
  Trig, Triangle, Rectangular, Pulse, checked against OpenSees' evaluation) and
  Define → Add Multi-Support Excitation for the selected supports.
- **Analysis options**: every system, algorithm, convergence test and integrator
  OpenSeesPy 3.8 runs (SparseSYM, NewtonLineSearch, SecantNewton, RaphsonNewton,
  PeriodicNewton, six more tests, MinUnbalDispNorm, GeneralizedAlpha), each run
  live on a cantilever; the transient parameter rows follow the integrator.
- **Help: menu map and command glossary.** F1 help gains a menu map (every menu
  entry in one page) and an annex, "Annex — OpenSees commands": every command
  family of the OpenSeesPy manual (model, elements, uniaxial and nD materials,
  sections, loads, analysis, output, utility, research families) with a line on
  what each does and where it lives in the application — a form, automatic, or a
  custom block.
- **Custom OpenSees commands** (Define → Custom OpenSees Commands): Python blocks
  with `ops` run after the materials or after the elements, with their own tag
  range; a file's blocks are disabled until you trust them, and the exported
  script carries them.

## [0.0.12] — 2026-10-14

The building-workflow release: groups, section cuts, spreadsheet editing,
support springs, modal damping and a calculation report, on top of code seismic
loads, area loads and IFC export. Every addition is optional in the file: a
project that does not use one saves exactly as before (schema 3 unchanged).

### Added

- **Modal damping for transient cases** (Analyze → Cases → Transient: modal
  damping ratio ζ and number of modes). OpenSees `modalDamping` gives each of the
  first N modes exactly ζ, on top of any Rayleigh damping. The eigen solve follows
  the eigen determinism rule (solver from `resolve_modal_solver`, a case routed to
  ARPACK runs in a fresh child). Checked against the logarithmic decrement of a
  damped SDOF. A case without it saves byte-identical to before.
- **Support springs** (Assign → Joint → Springs). Elastic springs to ground per
  DOF (soil springs, flexible bases, bearing pads): each sprung joint gets a fixed
  hidden node and a global `zeroLength`, and the spring force is reported as the
  joint's reaction. Drawn as a green zigzag, exported to IFC as stiffness values.
  Checked against closed forms (propped cantilever, rotational base spring, mass
  on springs). A project without springs saves byte-identical to before.
- **Calculation report** (File → Export → Report, PDF or HTML). The project,
  the model in numbers, materials, sections, load patterns, cases and
  combinations, then the results of every case run on the current model: peak
  displacements, support reactions with their sum, pushover curve, periods,
  storey table and section cuts. PDF is printed by Qt (A4), no extra dependency.

- **Section cuts** (Define → Section Cuts). The resultant force through a group:
  the end forces of the group's elements at the group's joints, with moments
  about their centroid or a typed point. Static cases report the six global
  components in a **Section cuts** tab of the Results panel (checked against
  hand statics of a 3D cantilever and a 2D portal). A group a cut uses cannot be
  removed.

- **Groups** (Define → Groups, Assign → Assign to Group (Ctrl+G), Select → By
  Group). Named, coloured sets of joints and elements, as in SAP2000 and ETABS:
  add the selection to a group, remove it or replace the members, and select a
  group again later. Deleting joints or elements takes them out of every group
  (Undo restores them) and Fix Duplicates moves a merged joint's membership to
  the joint it keeps. A project without groups saves byte-identical to before.
- **Interactive table editing** (Edit → Interactive Table Editing, Ctrl+T).
  Joints (coordinates, restraints, masses), elements (joints, section, material)
  and joint loads as spreadsheets: edit cells, copy and paste blocks from Excel,
  add and delete rows. Only the model's own DOFs are columns. OK validates every
  cell and reference, names a bad one by table, row and column, and applies the
  edit as one undo step.

- **IFC export** (File → Export → IFC). An IFC4 file with the physical model
  (columns, beams, members and slabs/walls/plates with their profiles — AISC I
  and channel shapes, rectangles, pipes, angles — materials and storeys) and the
  structural analysis model (point connections with supports, curve and surface
  members with releases and thickness, one load case per pattern with nodal,
  member, point, surface and imposed-displacement loads and the self weight, and
  load combinations by factor), each analytical member assigned to its physical
  element. Valid against the IFC4 schema for every bundled example. Adds
  `ifcopenshell` to the GUI dependencies (and to the packaged bundle).
- **Seismic loads by the equivalent lateral force method** (Define → Seismic
  Loads). ASCE/SEI 7-16 §12.8 or TBDY 2018 §4.7: base shear from the code
  formulas (with every cap and minimum, and the clause that governs named in the
  preview), shared between the storeys by weight and height (k exponent, or the
  TBDY ΔFN top force). The period is typed or approximated from the building
  height. One load pattern and static case per direction (`EQ X`, `EQ Y`, and
  `±e` cases with accidental eccentricity in 3D), applied at a diaphragm's
  retained node or shared by mass between the floor's joints; a pattern of the
  same name is refilled. One undo step.
- **Surface loads on shells** (Assign → Area → Surface Load on Shells): a
  uniform pressure along global X, Y, Z or the shell normal, sent to the solver
  as consistent nodal forces; it follows the shell through Mesh and Replicate.
- **Floor loads to frames** (Assign → Area → Floor Load to Frames): select a
  floor's joints and every rectangular bay framed by beams on four sides takes
  the load, two-way (45° yield lines: trapezoids and triangles) or one-way along
  X or Y, as trapezoidal member loads in each beam's local axes. Drawn on the
  canvas with the other member loads, and read by the diagrams and the runner
  like any trapezoidal load.
- **Imposed displacements** (Assign → Joint → Imposed Displacement): a static
  support settlement (`sp` in the pattern) on any DOF; the support's own
  constraint is removed first, and the case runs with Transformation even when
  set to Plain, which would ignore a nonzero value.

## [0.0.11] — 2026-10-13

The Z-up release: every model, 2D included, stands on Z as its elevation axis;
a stability check finds mechanisms before a run; the Properties panel edits a
whole selection at once; and the combination generator creates the loads a
model is missing. 2D projects saved by earlier builds are converted when they
are opened (file schema 3).

### Added

- **Edit several items at once in the Properties panel.** With more than one
  joint or element selected, the panel shows what they share and lets you change
  it: restraints and lumped masses of joints; type, section, material, area,
  geometric transformation, beam integration, end offsets and cardinal point of
  elements, each applied where the field exists. Differing values show
  `(varies)` and stay as they are unless changed; Apply is one undo step.

- **The code-combination generator creates the loads the model lacks.** With
  *Create the missing load cases* (on by default), every load the chosen code
  uses that no case carries gets an empty Plain pattern and static case of its
  own (LIVE, ROOF LIVE, SNOW, RAIN, WIND X/Y, EQ X/Y, and DEAD with the self
  weight), in the same undo step as the combinations. The dialog lists them
  before you accept.
- **Analyze → Check Model Stability.** Builds the model as an analysis would,
  assembles its stiffness matrix once and decomposes it into singular values:
  each zero is a mechanism, reported with the joints and DOFs that move in it
  (in global names, Ux/Uz/Ry in 2D), and those joints are selected in the view.
  Free DOFs no element stiffens are listed too. It runs in the analysis child
  process (`python -m opensees_studio.run --project P --check-stability`), so a
  model OpenSees cannot build does not take the window down.

### Changed

- **Z is the elevation axis of every model.** A 2D model now lives in the X-Z
  plane (nodes at y = 0, Z up) with the DOFs Ux, Uz and Ry, the way a 3D model
  stands; OpenSees still solves it in its own x-y plane, and the application
  translates coordinates, loads and results on the way (`core.plane`). Gravity
  is -Z in 2D and 3D; the portal frame and truss wizards, the DXF import and
  File → New 2D Frame / Truss build in XZ, and a 2D project opens face on with
  the XZ working plane. Result columns are named after the global axes (U1, U3,
  R2 for a 2D frame), and a 2D rotation or moment about Y is the OpenSees one
  with its sign changed.
- **File schema 3.** A 2D project saved by an earlier build (X-Y plane, Y up) is
  turned into the X-Z plane when it is opened — nodes, restraints, masses, nodal
  loads, bearing orientations and grid lines together, the same physical model —
  with a notice, and is saved as schema 3. 3D projects only change the number. A
  2D node off the X-Z plane is refused before a run. The wizards no longer offer
  the XY plane: a frame or truss stands in an elevation.

### Fixed

- The deformed shape of a 2D frame no longer moves the joints out of plane by
  their rotation (the third result column was read as a translation).
- The Roller (Z) support preset restrains a 2D model's vertical translation; it
  used to restrain nothing there.

## [0.0.10] — 2026-10-12

The building release: storeys, rigid diaphragms and a mass source for multi-storey
models, load combinations with envelopes and code generators, and the member-level
options a SAP2000 user expects on frames (releases, offsets, modifiers, trapezoidal
loads).

### Added

- **Storeys** (Define → Storeys…): named floor levels with an elevation, typed or
  taken from the Z grid lines of a coordinate system.
- **Rigid diaphragms** (Assign → Joint → Diaphragm…): OpenSees `rigidDiaphragm`
  over every joint of a storey (resolved at build time, supports in the plane
  left out) or over the selected joints, with the retained node either an
  existing joint or a new node at the centre of mass. A retained node no element
  touches gets its out-of-plane DOF fixed by the runner. Drawn on the canvas as
  spokes from the retained node; deleting the retained node deletes it.
- **Rigid links** (Assign → Joint → Rigid Link…): `rigidLink beam` or `bar`
  between two joints, drawn as a thick bar. Assign → Joint → Remove Constraints
  takes the selected joints out of every equalDOF, rigid link and diaphragm.
- **Mass source** (Define → Mass Source…): nodal mass as W / g of the element
  self weight and of chosen load patterns with factors (downward loads only,
  lumped on the element ends), on the lateral translations or also the vertical
  one, optionally lumped at each diaphragm's retained node with the floor's
  rotational inertia (only where that node is at the centre of mass, the case in
  which lumping is exact). Restrained DOF get no mass.
- **Storey table** in the Results panel (a Storeys tab, CSV at full precision):
  storey displacement, inter-storey drift ratio, storey shear and base shear for
  static cases (shear from the global end forces of the members cut above the
  level below, base shear from the reactions), mode shapes, pushovers and
  response spectrum cases (drift and shear combined mode by mode with SRSS or
  CQC, never derived from combined displacements).
- Example `building_3storey_diaphragm` (3 storeys, 2 × 2 bays), verified against
  a hand-built OpenSeesPy model with `rigidDiaphragm` (all periods) and with
  `equalDOF` (the X-sway periods) to 1e-9.

- **Load combinations** (Define → Load Combinations…). A combination includes
  Static and Response Spectrum cases, or other combinations, each with a scale
  factor, and is one of Linear Add, Envelope, Absolute Add or SRSS. Combining is
  post-processing on stored results, never a new solve: every result has a
  maximum and a minimum (a static case has one value, a spectrum peak counts as
  ±peak, a negative factor swaps them), and only what every included case
  provides is combined. Element forces are enveloped as internal
  forces, so the envelope's force diagram is the envelope of the case diagrams.
  A Linear Add, Absolute Add or SRSS that includes a case solved with an
  iterative algorithm, or a model with P-Delta or corotational transformations,
  is applied with a warning. Missing or non-combinable cases and combinations
  that include each other are refused; a case or combination another
  combination uses cannot be deleted. Every edit is one undo step, and a
  project without combinations saves byte-identical to before (schema 2).
- **Running and showing combinations.** Analyze → Run lists the combinations
  after the cases: running one runs only the cases it needs that have no
  current result, in one analysis process, then combines. Results stay current
  until the model changes (editing a combination does not make them stale).
  Display → Show Results Of… switches between stored case and combination
  results. Envelopes draw their max and min force diagrams together, the
  deformed shape has a Max/Min choice, shell contours show the maximum, and the
  results tables and CSV export list Max and Min.
- **ASCE 7-16 LRFD generator** (Generate ASCE 7-16 LRFD… in the combinations
  dialog): the Section 2.3.1 basic combinations from cases tagged Dead, Live,
  Roof live, Snow, Rain, Wind and Earthquake — the role is guessed from the case
  name — with wind and static earthquake in both signs, plus an envelope of
  them.
- **Code combination generators** (Generate from a design code… in the
  combinations dialog, a code picker replacing the LRFD button): ASCE 7-16 LRFD
  and ASD (Section 2.4.1), EN 1990 (ultimate equation 6.10 with each variable
  action leading, the seismic G + E + Σψ2Q, serviceability characteristic,
  frequent and quasi-permanent, ψ factors of Table A1.1 by imposed load
  category, snow altitude, optional favourable permanent action) and
  TS 500 / TBDY 2018 (1.4G+1.6Q, G+nQ±E with the live participation n, 0.9G±E,
  TS 500 wind). An option applies the 100% + 30% orthogonal rule to the
  earthquake cases (±Ex ± 0.3Ey, ±0.3Ex ± Ey). A generated set is ordinary
  editable combinations, one undo step, with an envelope per group (ultimate and
  serviceability states stay apart). The load role is still chosen per case in
  the generator dialog, not stored in the project, so tagging never makes
  results stale or changes a saved file.
- **Response spectrum forces and reactions.** A response spectrum result now
  carries peak reactions, element forces and shell resultants besides the
  displacements: the static response of the model to each mode's equivalent load
  (M·φ·Γ·Sa on the nodal mass), combined component by component with the case's
  SRSS or CQC rule and the same correlation as the displacements (one new
  `core.modal_combination.combine_modal_fields`, no second eigen solve). A
  combination uses them as ±peak, so a combination with a spectrum case has
  forces, reactions and force diagrams, and the "no forces" limitation is gone;
  the Results panel lists the peak reactions and element forces (CSV at full
  precision). A result stored by an earlier build still loads and gives
  displacements only, and a combination using it says to run the case again.

- **Automatic end offsets from connectivity** (Assign → Frame → End (Length)
  Offsets… → Automatic from connectivity): each end's rigid length is the
  largest half-extent, along the member, of the section of the other frame
  members that meet it at that joint (`core.frame_members.connectivity_offsets`).
  Worked out once on OK, stored as ordinary offsets, one undo step.
- **Shear areas on elastic sections** (`ElasticSection.As2` / `As3`, left out of
  the file while unset): a beam-column on such a section runs as an
  `ElasticTimoshenkoBeam`, so the As2 / As3 property modifiers now change a
  result. Verified against `P L³ / 3 E I + P L / G As` (tip load, 2D and 3D in
  both bending directions, modifiers) and `w L⁴ / 8 E I + w L² / 2 G As`
  (uniform load). OpenSees 3.8's Timoshenko element accepts only full-length
  uniform loads, so point, partial and trapezoidal loads on it are refused with
  a message instead of being silently dropped, and it takes no `-release` (a
  released end uses the hidden-node route).
- **Force diagrams with intermediate stations**: a member under uniform, point,
  trapezoidal or self-weight span loads draws its moment and shear from statics
  along the member (parabolic moment under a uniform load, a shear jump at a
  point load), and labels the peak between the ends. Checked against `w L² / 8`,
  `P a b / L`, the triangular-load moment and, with rigid end zones, the clear
  span `w c² / 24`. Static case results only; combinations and envelopes still
  draw straight lines.

### Fixed

- **AISC shapes in a 3D project put the strong axis on the wrong inertia.** The
  table's `Ix` became Iz, which a horizontal 3D beam (local z vertical) bends
  about only sideways, so a W14X90 under gravity deflected as its weak axis.
  The AISC library now takes the project's dimension: 3D gives Iy = Ix and
  Iz = Iy, and turns the fibre profile upright; 2D is unchanged. Sections
  inserted earlier into a 3D project keep the old values: re-insert them. A
  2D rectangle / angle shape hint is also drawn and inserted with its depth
  along local y.

### Changed

- A case left at the `Plain` constraint handler runs with `Transformation` when
  the model has a rigid diaphragm or a rigid link: Plain drops such a constraint
  with a warning and then solves a singular system while reporting success.
- The free DOF count behind the eigen solver routing leaves out the DOF a
  diaphragm eliminates and the ones fixed on a floating retained node.
- Projects without storeys, diaphragms, rigid links or a mass source save
  byte-identical to before.
- A joint a diaphragm constrains may not also retain an `equalDOF` or rigid
  link: the model check refuses it. OpenSees' Transformation handler cannot chain
  such constraints and solves them without an error into wrong results.
- **Frame end releases and partial fixity at diaphragm joints** work. The hidden
  node `equalDOF`'d to the joint would be such a chain (the example building
  with M3 released at one end of its X beams came out with T1 = 0.18 s instead
  of 0.69 s, with pinned beams 0.06 s instead of 1.02 s; Lagrange and Penalty chain
  correctly but get every eigen analysis wrong). At those joints an
  `elasticBeamColumn` with an elastic section is released inside the element
  (`-releasez` / `-releasey`, a zero `G J` for torsion), exactly, also at an
  offset end; any other member with elastic properties, or an elastic member
  with point / partial / trapezoidal loads, a consistent mass or partial fixity
  there, hangs the end off a hidden node held by penalty springs 1e5 times its
  own stiffness (about 1e-7 from exact). A fibre member released at a diaphragm
  joint, or a spring-held end there with an end offset, is refused with a
  remedy. Verified on the
  example building with released and with partially fixed beam ends against
  hand-built OpenSeesPy (element releases, `ModElasticBeam3d`, and hidden nodes
  under the Lagrange handler): 1e-9 and 1e-6.
- Chains of equalDOFs and rigid links are refused by the model check, with a
  remedy: a node that one constraint ties and that retains another (equalDOF
  2->3 plus equalDOF 3->5, or a rigid link whose retained node an equalDOF or
  rigid link constrains), a node constrained twice, a loop, and an equalDOF of a
  node to itself. OpenSees 3.8's Transformation handler, which every eigen
  analysis uses, keeps one constraint per constrained node and solves the rest
  without an error into wrong results (a probe against Lagrange: static
  displacements off by up to 85 %, periods by more). A chain through a node an
  equalDOF of every DOF constrains comes out right and is still accepted.

### Fixed

- A frame end release or partial fixity at a joint that is the constrained node
  of a user `equalDOF` or rigid link no longer hangs off a hidden node
  `equalDOF`'d to that joint. That is the same constraint chain as at a
  diaphragm joint, and OpenSees' Transformation handler, which every eigen
  analysis uses, solved it without an error into wrong results (a beam pinned at
  a joint tied to a column top in U1 and U2 only: the sway of its far end 92 %
  too small; hung off the column top by `rigidLink beam`: 2 % off; only an
  `equalDOF` of every DOF happened to come out right). Such an end now takes
  the diaphragm route: released inside an `elasticBeamColumn` (in 2D with
  `-release`), or held by penalty springs. The springs act in series with the
  member, so a mode the member's own axial stiffness governs comes out about
  1e-5 too soft. Fibre members and spring-held ends with an end offset there are
  refused with a remedy. A joint that only *retains* such a constraint plans as
  before. Verified in 2D and 3D, pinned and partially fixed, at an `equalDOF`
  and at a `rigidLink` joint against hand-built OpenSeesPy (element releases,
  `ModElasticBeam2d` / `3d`, hidden nodes under the Lagrange handler): 1e-9 for
  the pinned ends, 1e-6 (2e-5 for the eigenvalues) for the spring-held ones.

### Added — frame members

- **Frame end releases and partial fixity** (Assign → Frame → Releases/Partial
  Fixity…): T, M2 and M3 per end, each with an optional rotational spring.
  Realised with a hidden node per released end (`equalDOF` on the kept DOFs, a
  `zeroLength` for springs, a penalty spring only for a kept rotation about an
  axis skewed to the global axes), for every beam-column type. The joint's
  reaction includes the force that crosses the release.
- **End (length) offsets with a rigid-zone factor and cardinal-point insertion**
  (Assign → Frame → End (Length) Offsets… / Insertion Point…), as
  `geomTransf -jntOffset`. Loads on a rigid zone go to the joint, force
  diagrams are drawn along the flexible length, and a release at an offset end
  acts at the face through a `rigidLink` (the case then runs with the
  Transformation handler). A 3D Corotational transformation with offsets is
  refused: OpenSees 3.8 ignores them there.
- **Property modifiers** (Assign → Frame → Property Modifiers…) on A, As2, As3,
  J, I22, I33, mass and weight of members with an elastic section.
- **Trapezoidal and partial-span distributed loads** (Assign → Frame →
  Trapezoidal Load…), meshed, replicated and handed over with their member.
- Projects that use none of these save byte-identical to before.

## [0.0.9] — 2026-10-10

The modelling release: loads inside a member, the weight of the structure as a
load case from the first click, a truss in three pages, and a Select menu to
work on what was built.

### Added

- **Point loads inside frame elements** (Assign → Frame → Point Load…). A
  concentrated force (Px, Py, Pz in the element's local axes) at a distance from
  end i, given as a fraction of the length or as an absolute length, emitted as
  `eleLoad -beamPoint`. Only beam-column elements take it; trusses and other
  elements in the selection are skipped. The load is drawn on the canvas, is
  copied by Replicate, follows the piece it falls on when a member is meshed, and
  is handed over (measured from the right end) when a repeated member is
  removed. A pattern without point loads saves byte-identical to before.
- **Self weight and a DEAD case in every new model.** A section can carry a
  unit weight γ (force per volume; Section Library), and a Plain pattern a
  self-weight multiplier (Define → Add Plain Load Pattern): the pattern then
  loads every frame with γ·A per unit length, downward (-Z in 3D, -Y in 2D),
  split over the member's local axes. File → New (3D frame, 2D frame and 2D
  truss) starts with a `DEAD` time series, pattern and linear static case, and
  the default section is steel (γ = 77 kN/m³), so a frame drawn on a fresh model
  has a gravity result straight away. A plate section (shell) has a unit weight
  too: each ShellMITC4 takes γ·h per unit area as consistent nodal forces,
  integrated over the real quadrilateral (a rectangle gives a quarter to each
  corner). Fiber and aggregated sections, BeamWithHinges and trusses carry no
  self weight yet. Sections without a unit weight and patterns without a self
  weight save byte-identical.
- **Truss wizard** (Define → Create Truss…). A simply supported plane truss —
  Pratt, Howe, Warren or Warren with verticals — with parallel chords, a
  pitched top chord or closed at the supports (triangular), from the span, the
  number of panels and the depth; one material and an area for the chords and
  one for the web (a default steel is created when the project has none), in
  any plane, pinned at the left and on a roller at the right, as one undo step.
  In a frame model the rotations of the truss nodes are restrained.
- **Select menu.** Invert Selection (Ctrl+I), Get Previous Selection (Ctrl+P),
  all joints or all elements, by element type, by section, by material (also
  through the fibres of a section), by load pattern, supported joints, joints
  with mass, elements with self weight, the joints of the selected elements and
  the elements between the selected joints. Every query adds to the current
  selection.

### Fixed

- **Element loads on force-based frames lagged one step in a static case.** A
  `forceBeamColumn` or `beamWithHinges` only takes a uniform or point element
  load into its resisting force after the solve, so the first solve of a step
  moved nothing: the default Linear case stopped there, and Newton (or Modified
  / Krylov Newton) with NormDispIncr or EnergyIncr took the zero increment as
  convergence. Both reported the fixed-end reactions (8.42 / 1.58 instead of
  7.5 / 2.5 for a point load at a quarter span) and no end rotation. Such a step
  is now followed by a second solve at the same load with the case's own
  algorithm and test, which gives the converged answer (for Linear and elastic
  sections the exact one, with no tolerance involved). RelativeNormDispIncr
  cannot converge there past the first step and is refused with the reason.
  Cases without element loads on those elements, and Newton with NormUnbalance,
  run as before; no file changes.
- **An empty click on a grid placed a node wherever the pointer happened to
  be** (for example at (-0.0074, 1.9923)). With a visible grid, a click that
  hits no node and no intersection now lands on the nearest grid crossing, in
  the grid's own frame and on the working plane, and the hover preview follows
  the same rule. A project with no grid still places the point where the ray
  meets the plane.

## [0.0.8] — 2026-10-10

The release that makes the drawing tools work on a model that already has
members, and on a Wayland desktop at all.

### Fixed

- **Draw Node / Draw Frame did nothing on a project that already held a frame.**
  Every click near a column or a rafter hit the *member*: the canvas reported an
  element pick, the tools' base handler ignores that signal, and the click
  vanished — no node, no element, and no message, because the handler that would
  have spoken belongs to empty clicks. On a blank model it worked, which is why
  it read as a regression against 0.0.1/0.0.2: there was nothing to hit then. A
  member is now a pick target only for the select tool, while nodes stay
  pickable so an existing node is still reused as an endpoint.
- **Wayland sessions never delivered a mouse event to the 3D canvas.** The canvas
  is a VTK render widget — a native child window — and a native Wayland
  compositor does not route pointer events into it: no orbit, no selection and no
  drawing, with nothing in the log because the event never arrived. The
  application now asks for XWayland (`QT_QPA_PLATFORM=xcb`) when the session
  offers Wayland *and* an X server, which every Wayland desktop ships. An
  explicit `QT_QPA_PLATFORM` still wins.
- **Arming a draw tool threw the view to top.** Draw Node, Draw Frame and Draw
  Truss each called `canvas.view_xy()` on activation, so the camera jumped as
  soon as the tool was picked and the click that followed landed somewhere the
  user had not been looking. They no longer touch the camera; clicks are
  resolved in screen space, so they work in plan, elevation and isometric alike.
- **A click that drifted a few pixels was discarded as a camera drag.** The bound
  was 3 px, so a trackpad, an unsteady hand or a remote desktop lost the click
  silently. The decision now follows the *view*: a gesture is a click unless the
  camera actually turned (more than 3°) or panned, and an accepted click puts the
  camera back where it was so the drift leaves no trace.

### Added

- **The canvas explains itself.** A gesture taken as a drag while a tool is armed
  says so in the status bar ("that was a drag (the view moved), so nothing was
  placed"), a placed node says whether it snapped to the grid or landed on the
  working plane, and a click that cannot be resolved at all (the view ray
  parallel to the active level) is reported in the log instead of vanishing.
- A project without a grid no longer refuses to draw and no longer opens a modal:
  the tool arms, and its prompt says that clicks land on the working plane.
  Clicks near a grid intersection still snap to it.

## [0.0.7] — 2026-10-09

The release that paints what a shell is doing: a colour map of its deformations,
its internal forces and moments, and — for the membrane and bending tensors —
the principal values and the directions they act along.

### Added

- **Display → Show Shell Contours…**: pick a field and the shell faces are
  coloured with a legend. Deformations (`|u|`, `ux`, `uy`, `uz`) warp the mesh;
  membrane forces (`N11`, `N22`, `N12`), bending moments (`M11`, `M22`, `M12`),
  transverse shear (`V13`, `V23`, `V`), and the principals (`N1`, `N2`, `M1`,
  `M2`) are painted on the undeformed shape. A signed field gets a colour range
  symmetric about zero — a moment is read by its sign — and the legend names the
  field with its unit in the project's system (`N11 [kip/in]`).
- **Principal directions** as one segment per element, through its centroid and
  along its major principal axis, with a length proportional to the spread
  between the two principal values: where they are equal there is no direction
  and nothing is drawn. The principals come from Mohr's circle
  (`core/shell_results`), so they do not depend on the arbitrary local axes of
  the mesh — which is the point of contouring them rather than the components.
- **The section resultants now travel with the results.**
  `StaticResults.element_stresses` (and the pushover equivalent) records the
  eight resultants OpenSees reports per shell, averaged over its gauss points
  and in its own order (`N11, N22, N12, M11, M22, M12, V13, V23`, all per unit
  length); the result store writes and reads them, and a file written before the
  field existed still loads.
- A help page (`F1`) for the view: which fields exist, what the principals mean,
  and the limits — a frame model has nothing to paint, and the values are
  section resultants per unit length, not stresses.

### Fixed

- **A wrong belief about the solver, caught by the reference test.** An earlier
  probe concluded that a `Linear` static case reports no section resultants;
  what actually happens is that the response is only materialised when something
  queries the element state, and `ops.reactions()` — which the runner always
  calls before reading responses — does exactly that. A `Linear` case reports
  the same numbers as Newton, so no caveat belongs in the view. The finding, the
  correction and a test that pins it are in
  `reports/SHELL_CONTOURS_PLAN_2026-10-09.md`.
- Two mypy ratchet improvements while passing through: the runner's solver module
  is typed `Any` (it is duck-typed at runtime and a mock in the tests) and
  `MainWindow._post_dock` is typed `QDockWidget | None`, which between them took
  the budget from 367 to **237**.

### Verified

- **A plate strip with a tip moment**, the one bending case with no
  discretisation error in the moment: `M11` comes back as the applied moment per
  unit width element for element (500.0 N·m/m for 500 N·m/m), `V13` is zero, and
  the tip deflection is within 5 % of the cylindrical-bending value `M L² / 2D`
  (4.94e-5 m against 4.80e-5 m — the 3 % is the thick strip and the two-element
  span).
- **Uniform membrane tension** of 2000 N/m reads back as exactly 2000, with
  `N22 = 0` even at ν = 0.2, where the plate contracts freely.
- The principal maths against hand cases (uniaxial, compression, pure shear at
  ±45°, equibiaxial, the trace/determinant invariants, a tensor built from a
  known `(major, minor, 30°)`, and rotation-independence).

## [0.0.6] — 2026-10-09

The release that stops asking you to type numbers it could look up: a library of
typical construction materials, each row tied to the clause it comes from. It
also carries the two fixes the first full CI matrix on Windows turned up.

### Added

- **A library of typical construction materials** (Material Library → From
  library…): 23 named materials — specified concrete strengths from 17 MPa up,
  the reinforcing grades ACI permits (280, 420, 550 and ASTM A706's 690), the
  structural steels AISC tabulates (A992, A36, A572 Gr. 50, A500 Gr. B, plus a
  plain elastic steel) and masonry at its usual specified strengths (clay and
  concrete block, with `Em` = 700 f'm and 900 f'm). Each row names the clause
  its numbers come from, and the picker shows the published value beside the one
  that will be inserted, converted to the project's units — including a mass
  density, whose unit is the coherent `force·s²/length` of the project's system.
  The table is generated by `tools/build_typical_materials.py` from its
  published inputs, so no derived number is typed by hand; a drift check
  regenerates it, and the tests verify every value against its code equation
  (ACI's two `Ec` expressions, which agree at 2320 kg/m³), the exact
  psi/ksi/lb·ft³ conversions, and — through the real solver — the
  Kent-Scott-Park parabola of the library's concrete (0.585786 mm against a
  linear-`E0` 0.500000 mm) and the Menegotto-Pinto curve of its A992 steel
  (10.344830 mm against an elastic line of 1.896552 mm).

### Fixed

- **The exported OpenSees script could not be written on Windows.** The banner
  above the analysis block was ruled with U+2500 BOX DRAWINGS LIGHT HORIZONTAL,
  which cp1252 — the default encoding of `Path.write_text` there — has no byte
  for, so a tool or test that wrote the script with the platform default raised
  `UnicodeEncodeError`. The exporter emits ASCII now, the writer is explicit
  about UTF-8, and a regression test asserts the script stays ASCII. The
  application itself always wrote UTF-8, so no shipped model was affected.

## [0.0.5] — 2026-10-09

The release that works on the model rather than on the input file: a portal
frame wizard that writes its own grid, duplicate detection and repair, a DXF
import for bar layouts, contextual help on F1, a response spectrum built by hand
or from ASCE/SEI 7-16, automatic meshing of members and shells — and display
units that finally convert what they show, in every open view, without a re-run.

### Added

- **A portal frame wizard** (Define → Create Portal Frame): the geometry of a
  2D plane frame from bays and bay width, eave height, a roof of one slope, two
  slopes or none, a section per member group and fixed or pinned bases, in the
  XY, XZ or YZ plane and at a chosen origin. The roof is a line and the column
  tops sit on it, so an interior column is as tall as the roof above its base;
  a gable whose ridge falls mid-bay gets a crown node and a split rafter. The
  whole frame — including the default section, when the project has none — is
  one undoable step, and it arrives selected because the next thing most users
  do is copy it. The geometry is pure `core.frames`, so the wizard, the log line
  and the tests read the same specification.

### Added

- **A duplicate checker and repair** (Edit → Check Model for Duplicates):
  coincident nodes and elements that describe the same member twice, reported
  before anything is touched. The tolerance is one part per million of the
  model's extent, so the same numbers work in metres and in millimetres, and
  the deliberate coincidences — the two nodes of a zero-length element or a
  bearing, and nodes tied by an `equalDOF` constraint — are listed *with the
  reason* and left alone rather than merged, which would quietly delete every
  isolator in the model. Elements are compared by their whole definition, so
  two members over the same nodes with different sections are reported as
  parallel (information) instead of being removed as duplicates.
  The repair is one undoable step: restraints are combined (a support is never
  released by accident), masses that agree are kept once and masses that differ
  are added, and element nodes, `equalDOF` constraints, nodal loads and
  imposed-support lists follow the node that stays. Loads that were copies are
  dropped rather than doubled, an element whose ends merge into one node is
  removed for having no length left, and the element duplicates are recomputed
  *after* the node merge — merging two nodes can turn two members into the same
  member, which a report computed beforehand cannot see. Verified on a real
  solve: a cantilever copied whole shows the *same* tip deflection (the copy
  doubles stiffness and load together) while its supports carry 2000 N instead
  of the 1000 N the structure is meant to; after the repair both match
  `P L³/3EI` and `P`.

### Added

- **An X / Y / Z reference at the origin.** Small red, green and blue arrows
  with their labels, drawn as scene geometry at (0, 0, 0) rather than as a
  corner widget, because the question they answer — which way does +Y run in
  this model — is about the model, and the answer belongs next to the elements
  being looked at. Their length is 8 % of the model's extent, so they stay small
  next to a 100 m frame and visible next to a 100 mm one (an empty project falls
  back to its grid, and a completely empty one to a unit length), and they are
  not pickable: a reference is not part of the structure.

- **Importing a bar layout from a DXF drawing** (File → Import → DXF Drawing,
  `services/dxf_import.py`). `LINE`, `LWPOLYLINE` and `POLYLINE` entities become
  beam-column elements; everything else in the file — circles, text, hatches,
  blocks — is counted and reported, so a drawing that imports four members where
  the user expected two hundred says so instead of looking like a success.
  The dialog makes the three decisions the file cannot make visible before
  anything enters the model: **which layers** are structure (ticked in a list),
  **what a drawing unit is worth** (`$INSUNITS` is turned into a factor to the
  project's own unit, and a unitless file gets factor 1 with a note saying
  nothing was converted), and **which plane** the two-dimensional drawing is
  read as (plan, front or side elevation, or `3D` to keep the file's own axes),
  plus the level it sits at and the origin it starts from. Curved polyline
  segments are imported as straight chords and reported as such. Endpoints that
  land within a tolerance of each other become one node — drawings repeat
  coordinates instead of sharing vertices, and the model must not — with the
  tolerance scaled to the drawing and the number of merges shown. Holes are left
  to the user: everything arrives free, because a drawing cannot say what is
  fixed. The whole import, including the default section when the project has
  none, is one undo step.

- **Contextual help, on F1** (`core/help.py`, `views/help_window.py`). The
  manual ships with the application: **82 topics** in eleven groups, one per menu
  action plus the mechanics behind them. F1 opens it on whatever is on screen —
  the item under the cursor in a menu that is open, the dialog on top (the wizard
  and the DXF import declare their own page), or the contents page otherwise —
  and the topic tree, a filter and cross-reference links move between pages.
  The content is written for the questions that come up while modelling: how the
  command is used, what each parameter means, and the physics where it applies
  (what the roof slope changes and what it does not, why a copy doubles the
  reaction and not the deflection, when a CQC combination matters, what a merge
  tolerance merges). The action→topic table and the topics are tested: a menu
  action without help, a page nothing links to, or a cross-reference to a page
  that does not exist all fail the suite.

### Changed

- **F1 is the help**, so Tools → Draw Node moves to **F4** (F2 and F3 keep Draw
  Frame and Draw Truss). The help key is handled by an application event filter
  rather than a shortcut, because the interesting case — a menu is open and the
  popup owns the keyboard — is one only a filter sees.

- **A response spectrum defined by the user or by ASCE/SEI 7-16.** The Ground
  Motions dialog already built a TBDY 2018 target and read a user table; it now
  also builds the ASCE 7-16 design spectrum, from the mapped `Ss` and `S1` with a
  site class (Tables 11.4-1 and 11.4-2, straight-line interpolation as the tables
  require) or from `SDS`, `SD1` and `TL` directly, and a single button turns
  whatever the form describes into the **tabulated curve a response-spectrum case
  reads** (`target_to_case_spectrum`: sampled at the code's own corner periods so
  the plateau and both decay branches survive, and g converted to the project's
  acceleration unit — a user table is copied point for point, because resampling
  a table somebody typed changes the numbers they meant).
  Two rules of the standard are enforced rather than assumed: **Site Class F**
  (and class E beyond `Ss = 0.75` or `S1 = 0.1`) is a site-specific study
  (§11.4.8) and is refused by name, and where class **D is assumed** because the
  soil is unknown, §11.4.3's `Fa >= 1.2` floor is applied by an explicit
  checkbox. Both tables, the equations and the four branches are pinned by tests,
  and every value was checked against the standard's own text before being
  committed.

- **Meshing** (Edit → Mesh, `core/mesh.py`). Three operations a structural
  modeller expects to be automatic:
  - **members** longer than a target size are split into equal pieces that
    inherit the section, the material and the element's own fields, and whose
    distributed loads follow them (a bar cut in three carries the same `q` on each
    third, not a third of it);
  - **shells** larger than the target are subdivided `m x n` by bilinear
    interpolation in their own natural coordinates, so a general quadrilateral
    meshes without leaving its own edges, the winding a shell's normal depends on
    is preserved, the corners are the nodes that were already there, and two
    meshed shells share their common edge because every new node goes through one
    shared node table;
  - **the joins**: a bar is split at every node lying on it (a column whose top
    lands mid-span of a beam, a frame drawn across a slab edge) and at its
    crossings with other bars, so a crossing becomes a shared node instead of two
    members passing by. A new node created on a shell's *supported edge* inherits
    the DOFs both of that edge's corners have restrained — meshing a slab must not
    quietly unsupport the middle of its edge — while interior mesh nodes and
    crossing nodes stay free, because a crossing is not a support.
  The dialog takes the target size, the scope (selection or the whole model) and
  which of the four operations to run, and shows what the mesh will add and
  replace before it is applied. One command applies the plan in one undo step.
  Verified against closed forms rather than against itself: splitting a
  cantilever into eight pieces leaves its tip deflection unchanged to 1e-9, and a
  uniformly loaded beam split into sixteen keeps its mid-span deflection; meshing
  a 2x2 slab into 4x4 and rebuilding the pressure loads reproduces the
  hand-built 4x4 model to 1e-6 (and the 0.2169 mm of the plate convergence table).

### Fixed

- **The failure report of a run crashed the application when the report had
  already been closed.** The box is created with `WA_DeleteOnClose`, so once the
  user dismisses it Qt has destroyed the C++ object while the window still held
  the Python wrapper; the `finally:` of `Run Analysis` then asked a deleted
  object for its parent and raised inside a Qt slot. The reference is now
  validity-checked before it is touched and dropped as soon as the box
  finishes.
- **An unhandled error in the interface is now reported instead of only
  printed.** `sys.excepthook` puts the traceback in the Console dock, points the
  status bar at it and opens a non-modal dialog saying the model and any running
  analysis are unaffected, so a failure in a slot is visible and the work can be
  saved. The full traceback still goes to stderr, and the analysis child keeps
  the default hook: its JSON protocol and exit codes are what the parent parses.
- **Replicate copied the geometry but not the loads**, so a copied loaded bay
  came back empty: the nodes and elements were new, and nothing re-created the
  nodal and element loads that pointed at the old ids. The copy now carries
  them, and its undo removes exactly the loads it added (by identity, since two
  loads on one node can compare equal). Masses and restraints were already
  copied — they are node fields. Ground-motion and imposed-support patterns are
  deliberately left alone: copying a frame should not multiply a base motion.

### Changed

- **File → New 2D Frame now opens the portal frame wizard and leaves the grid
  the wizard used** (and carries the ellipsis a dialog-opening action should:
  `New 2D Frame…`). A 2D frame project on its own is an empty canvas, and the
  only plane it can build in is the wizard's XY, so the wizard is what turns the
  menu entry into a frame. `core.frames.frame_grid` then writes a grid with a
  line per column position (including the crown line when the ridge falls
  mid-bay), a line per distinct roof level and one on the plane, labelled the
  way every other grid in the application is (`X1`, `X2`…) and placed at the
  origin the user typed. Frame and grid are one undo step, and for a 2D project
  the view switches to the plane so the frame comes up face on with its heights
  in the level list. Define → Create Portal Frame is deliberately unchanged: it
  builds a frame into the project that is already open and touches nothing else.
  Cancelling the wizard still leaves the empty project, which is the right start
  for drawing by hand.

- **Set Display Units now converts the results instead of only relabelling
  them**, and every open view follows the change without a re-run. A project
  carries two systems: `meta.units`, the units its values were typed in, and
  `meta.display_units`, the units results are *shown* in (`null` — the default,
  and what every file written before the field means — is the model's own). The
  model is never rewritten, so changing what you look at can no longer
  re-interpret what you typed. Force diagrams read their colour bar and their end
  labels in the new system, with the unit in the colour-bar title, while the
  drawn ribbon keeps its size — the scale is a geometric multiplier on the model
  values, and converting it too would resize the diagram on every unit change.
  Result tables (displacements, reactions, element forces, pushover curve, node
  histories, response-spectrum peaks), the pushover, time-history, hysteresis and
  response-spectrum plots and the deformed shape's peak displacement all convert
  value and label from one converter, so the two cannot disagree. Rotations stay
  in rad and time in s; curvature, being the inverse of a length, converts the
  other way. Factors come from exact definitions (1 in = 25.4 mm,
  1 lbf = 4.4482216152605 N): 10 000 N·m reads as 88.51 kip·in, 6 mm as
  0.2362 in.

## [0.0.4] — 2026-10-06

The AISC v16 shape library and the shell element — and the crash that running
them turned up, where opening a force diagram over a model with shells closed
the application. It is also the first release whose layering import-linter
enforces, and the first whose archives ship with checksums.

### Added

- **An OpenSees coverage review** (`reports/OPENSEES_COVERAGE_2026-10-04.md`):
  what the application emits, measured against the installed build's 237
  commands (42 used), and what is missing, prioritised — rigid diaphragms and
  links, static imposed displacement, `twoNodeLink` with a rate-dependent
  damper, section-level output, convergence diagnostics, wrapper materials.
- **A bridge from the gidopensees catalog to the runtime**: `CatalogMaterial`
  puts one of the catalog's 58 materials into a project, `core/quantities.py`
  reads the numbers out of the schema's unit-carrying defaults, and the
  material emitters are now one registry shared by the analysis runner and the
  Material Tester instead of two copies of the same commands (which is how
  `HystereticSM` became testable in the tester). One type is wired —
  `Elastic`, verified against the solver — and the rest fail loudly, with the
  measurements that kept them out recorded in `services/catalog_emitters.py`.
- **Script export** (File → Export): the model, and optionally one analysis
  case with its setup and step protocol. The script is generated by running
  the real runner against a recorder, so it is the command sequence the solver
  itself receives rather than a parallel implementation;
  `tests/integration/test_script_parity.py` runs the exported script against
  real OpenSees and compares displacements and eigenvalues with the
  application's.
- **Layering enforced in CI** with import-linter (`[tool.importlinter]`):
  `views > commands > viewmodels > services > core`, plus "core imports no Qt
  and no OpenSeesPy", "services import no Qt except `services/qt_workers.py`"
  and "nobody outside `services/` imports OpenSeesPy directly".
- **Signing and notarization wired** into the bundle workflow, skipped unless
  the signing secrets exist, plus `SHA256SUMS.txt` for every release archive.
- `packaging/build.py --zip-only`, which is what makes signing possible at
  all: the bundle has to be signed before it is compressed.
- **An AISC v16 shape library** (`data/aisc_v16.csv`, `core/aisc.py`): 1,660
  shapes across 13 families, selected by name in Define → Section Library →
  "Add from AISC…" as an elastic or a fiber section. The values are the AISC
  *Steel Construction Manual* 16th ed. US-customary numbers taken from
  `steelpy` (Apache-2.0, vendored licence and regeneration command in
  `data/README.md`), and they were checked against `aiscpy` (GPL-3.0, 13th
  ed.) before being committed: 303/303 W, M, S and HP shapes agree on `Ix`
  within 1%. Nothing is converted silently — the dialog shows the published
  value next to the converted one, and E/G remain the material's choice.
- **`ShellMITC4` shell elements** — walls and slabs. OpenSees wants a plate
  *section* for a shell, not an nDMaterial, so `ElasticMembranePlateSection`
  (E, ν, h, ρ) joins the section union and the runner emits
  `section ElasticMembranePlateSection` before the elements.
  Define → Create Shell from 4 Nodes builds one from the selection and derives
  the counter-clockwise winding from the coordinates, because a click
  selection carries no order: a shell built from a scrambled list is inverted
  or twisted. Faces (shells *and* the quads that had never been drawn) now
  render as filled surfaces with the same picking, selection and deformed-shape
  behaviour as the line elements.

### Fixed

- **Opening a force diagram on a model with shells closed the application.**
  OpenSees returns 24 force components for a `ShellMITC4` where a beam returns
  12; the diagram read them through the beam index map and the renderer then
  unpacked the shell's four nodes into `n_i, n_j` inside a Qt slot, so the
  exception unwound the event loop and the process died with no dialog. Faces
  (shells and quads) are now skipped where the diagram is built *and* where it
  is drawn, and a model with no line results says so in the log instead of
  showing nothing. Found by running the application, not by the test suite;
  `tests/gui/test_force_diagram_shell.py` reproduces the click.
- The Material Tester had its own copy of every `uniaxialMaterial` command.
  It now shares the runner's emitters, so a material cannot behave one way in
  the tester and another way in an analysis.
- Quad and shell elements were never rendered: `QuadElement` was in the model
  but the canvas only drew line elements, so a mesh of quads looked like an
  empty model. Both now build a face polydata.

### Changed

- `docs/gap-analysis-gidopensees.md` re-reviewed at 0.0.3: the ground-motion
  record library row moves to ✅; every other ❌ row was re-verified against
  the code with the generated catalog excluded.

## [0.0.3] — 2026-10-04

The first release built entirely by CI: the 0.0.2 archives were correct only
after being repaired by hand, because of the naming bug below.

### Fixed

- **The macOS archive was named `OpenSeesStudio-linux.zip`** and replaced the
  Linux asset on the release, so what shipped as Linux was a Mach-O bundle no
  Linux machine could run. The name now comes from `sys.platform` (`os.name`
  is `"posix"` on both Linux and macOS), pinned by
  `tests/unit/test_packaging_build.py`.
- **One publisher instead of three**: each platform job attached its own
  archive to the same release, which races and silently overwrites on a name
  collision. A `publish` job now collects the artifacts and writes the
  release once.
- The redundant `verify-source` job (one unit test file, missing `libEGL` on
  Ubuntu) is gone; the main CI `test` job already covers it.

### Added

- **mypy ratchet** (`tools/typecheck.py`, `tools/mypy-budget.txt`): CI fails
  when the number of type errors grows above the recorded budget.
- **Codegen drift test**: the committed catalog is compared byte for byte
  against a fresh codegen run, so a hand edit or a stale regeneration fails.
- Coverage floor (75%, today 76%) and a coverage artifact on the Ubuntu job.
- Python 3.13 and 3.14 in the Linux test matrix.
- `.github/dependabot.yml` (pip and GitHub Actions; the OpenSees wheels are
  ignored because they are ABI-bound to the interpreter).

### Changed

- `-m "not slow"` removed from CI: nothing carried the marker. The CLI parity
  module is now marked `slow` for local runs.
- ADR-0001 moves to Accepted, with its units carve-out recorded.
- README "What works today" lists what actually shipped.

## [0.0.2] — 2026-10-04

The first release with a desktop bundle: download, unpack, run — no Python,
Qt, VTK or OpenSees to install. Built by
`.github/workflows/desktop.yml` for Linux, Windows and macOS.

### Added

- **Packaging for end users** (`packaging/`): a PyInstaller spec and a build
  script that produces `dist/OpenSeesStudio`, plus a smoke test that solves a
  bundled example through the frozen executable and starts the GUI before an
  artifact is published.
- **Frozen-bundle analysis child** (`child_cli.py`): a bundle has no
  `python -m`, so the executable re-enters itself as the analysis CLI. Both
  spawn sites use it; on Windows the child is created without a console
  window.
- **mypy ratchet** (`tools/typecheck.py`, `tools/mypy-budget.txt`): CI now
  fails when the number of type errors grows above the recorded budget.
- **Codegen drift test**: the committed catalog is compared byte for byte
  against a fresh codegen run, so a hand edit or a stale regeneration fails
  CI.
- Coverage floor (75%) and a coverage artifact on the Ubuntu job; Python
  3.13 and 3.14 in the Linux test matrix.
- `CHANGELOG.md`, `.github/dependabot.yml` (pip and GitHub Actions).

### Fixed

- **Not losing unsaved work**: closing, `File → New` and `File → Open` now
  confirm before discarding a modified project. Only a user-initiated close
  asks; a programmatic close during shutdown does not.
- **Draw tools on an empty project**: arming Draw Node / Frame / Truss with
  no grid defined now offers to define one instead of doing nothing.
- **Material Library crash**: a material with no registered form
  (`Hysteretic`, `HystereticSM`) showed a `KeyError`; it now gets a read-only
  placeholder, as the section forms already did.
- **Atomic saves**: `.osmodel` is written through a temporary file and a
  rename, so a failure mid-write no longer truncates the previous file.
- **Future schema refused**: a project written by a newer build is rejected
  with a clear message instead of being loaded and rewritten one version
  down.
- The About box said MIT; the licence is AGPL-3.0.
- The Run dialog is destroyed when it closes, instead of staying alive and
  appended to on every later run.
- Throwaway results directories of finished analyses are removed; transient
  results keep theirs.

### Changed

- The version lives in one place (`src/opensees_studio/__init__.py`);
  `pyproject.toml` reads it with `[tool.hatch.version]`.
- `.github/workflows/ci.yml.disabled`, a stale duplicate of `ci.yml`, is gone.
- `CONTRIBUTING.md` installs `.[gui,dev]`; `[dev]` alone has no Qt.
