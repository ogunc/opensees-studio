<p align="center">
  <img src="docs/logo.svg" alt="OpenSees Studio" width="640">
</p>

<p align="center">
  A modern, SAP2000-style desktop GUI for
  <a href="https://openseespydoc.readthedocs.io/">OpenSeesPy</a> —
  built for structural and earthquake engineers who want a visual
  modeling environment without leaving the OpenSees ecosystem.
</p>

<p align="center">
  <em>Status: Pre-alpha. Active development. APIs and file formats will change.</em>
</p>

<p align="center">
  <strong>English</strong> · <a href="README.es.md">Español</a> ·
  <a href="docs/tutorials/README.md">Tutorials</a> ·
  <a href="docs/verification-manual.md">Verification Manual</a>
</p>

---

![OpenSees Studio main window](docs/screenshots/main_window.png)

## Why

OpenSees is the gold-standard nonlinear FEM solver for earthquake
engineering, but its native interface is Tcl/Python scripts.
OpenSees Studio adds a visual front-end so you can:

- Click to draw nodes, frames, supports, and loads on a snapped grid.
- Object snaps on frame members — midpoint, perpendicular foot and nearest
  point — toggled from the left-hand icon bar, with a colour-coded hover marker.
- Enter frame distributed, point and trapezoidal loads in **global X/Y/Z**;
  each member converts them to its own local axes, with an optional **Local
  axes** checkbox for direct wx/wy/wz entry.
- View → Show Local Axes draws the red/green/blue x/y/z triad beside every
  member midpoint, using the same axes as the analysis.
- Measure between two joints (Tools → Measure Distance, F7); the distance is
  copied to the clipboard.
- Assign materials, sections, and load patterns through dialogs.
- Run static, modal, pushover, and time-history analyses with progress
  and cancel support.
- Inspect results visually — deformed shape, mode shapes, force
  diagrams, pushover curves, time-history plots, hysteresis loops.
- Save the model as a single `.osmodel` JSON file that round-trips
  cleanly (diff-able in Git, scriptable from Python).

Behind the GUI, the same `core` Pydantic model is fully usable from a
script or Jupyter notebook — the GUI is one frontend, not the only one.

## What works today

- **Axes** — Z is the elevation axis of every model. A 2D model lives in the
  X-Z plane (Ux, Uz, Ry per joint), drawn face on like a front elevation; the
  application translates it to OpenSees' own 2D plane and back, and opens 2D
  projects saved by earlier builds (X-Y plane, Y up) in the new layout.
- **Modeling** — grids, nodes, frames (elastic, force-based and
  displacement-based), trusses, corotational trusses, quads, shells
  (`ShellMITC4`, `ShellDKGQ` with drilling stiffness, the geometrically
  nonlinear `ShellNLDKGQ`, and the triangles `ShellDKGT`/`ShellNLDKGT`; Define →
  Create Shell from 3 or 4 Nodes derives the winding from the coordinates,
  Assign → Area → Shell Formulation switches them), zero-length elements (Assign → Joint → Zero-Length Element) and
  zero-length sections, restraints,
  equalDOF constraints, uniform, trapezoidal / partial-span and point loads on
  frames, imposed support motion.
- **Grids** — Cartesian or radial (cylindrical: rings, radial lines, levels)
  coordinate/grid systems; Define → Grid Wizard builds one from counts and
  spacings; Add Row continues the last spacing; labels (ID, ID + coordinate)
  at either or both ends with size and colour; View → Show Grids hides or
  shows them; View → Grid Line View shows only the objects on one grid line
  (± 50 mm by default). Right-click on the model view lists the options of the
  selected joints/frames/shells, or the grid and view options when nothing is
  selected.
- **Spring supports** — Assign → Joint → Springs (to ground per DOF), Assign →
  Frame → Line Springs and Assign → Area → Edge Springs (per unit length) and
  Area Springs (per unit area: a Winkler bed under a raft or a tank), handed to
  the nodes by tributary length or area. Each acts along a direction with the
  supporting medium on one side, and is linear, **compression only** or
  **tension only**; one-sided springs are solved by Newton iteration and the log
  says which let go (lift-off). Checked against Hetényi's beam on an elastic
  foundation and a raft's `q / k` settlement.
- **Area loads and settlements** — Assign → Area → Surface Load on Shells (a
  pressure along X, Y, Z or the shell normal, as consistent nodal forces:
  uniform, or varying by a **joint pattern** — Define → Joint Patterns and
  Assign → Joint → Joint Pattern Values give each joint a value from
  `A·x + B·y + C·z + D` or from a free surface and a unit weight, so a
  hydrostatic or earth pressure on a wall or a tank is exact in resultant and
  lever arm; drawn on the shells as arrows as long as the pressure), Assign → Area → Floor Load to Frames (select a floor's joints: every
  rectangular bay framed by beams takes the load, two-way by 45° yield lines or
  one-way along X or Y, as trapezoidal loads on its beams) and Assign → Joint →
  Imposed Displacement (a static support settlement, `sp`, checked against
  6 E I d / L³ on a two-span beam). Temperature loads are not offered yet: they
  need OpenSees' thermal elements.
- **Nonprismatic (tapered) sections** in the Section Library: build a section
  from prismatic elastic sections with absolute or relative segment lengths and a
  linear, parabolic or cubic variation, choose how many pieces a member is
  subdivided into (minimum 12), and edit it later. Assigning the section
  subdivides the selected members automatically and follows their loads; editing
  the template refreshes the pieces already built from it (their piece count is
  kept, so choose the subdivision count before assigning).
- **SAP2000-style frame assignments** (Assign → Frame): end releases and
  partial-fixity springs (T, M2, M3 per end), end (length) offsets with a
  rigid-zone factor, cardinal-point insertion, and property modifiers
  (A, J, I22, I33, mass, weight, e.g. 0.35 Ig for cracked beams). Releases are
  drawn as dots near the member end and rigid zones as bars; force diagrams run
  along the flexible length and, under span loads, follow statics between the
  ends (parabolic moment under a uniform load). End offsets can be taken
  automatically from the members framing into each joint, and a section with
  shear areas As2 / As3 runs as a Timoshenko beam.
- **Multi-storey buildings** — Define → Storeys (typed, or one per Z grid
  line), Assign → Joint → Diaphragm (OpenSees `rigidDiaphragm` over every joint
  of a storey or the selected joints, with a new retained node at the centre of
  mass whose out-of-plane DOF the runner fixes), Assign → Joint → Rigid Link
  (`rigidLink beam`/`bar`) and Define → Mass Source (W / g of the element self
  weight and of chosen load patterns with factors, e.g. D + 0.3 L, lumped at the
  diaphragm's retained node with its rotational inertia). A case left at the
  `Plain` constraint handler runs with `Transformation`, which these constraints
  need. The Results panel gains a **Storeys** tab: storey displacement,
  inter-storey drift ratio, storey shear and base shear, for static cases, mode
  shapes, pushovers and response spectrum cases (each quantity combined over the
  modes by SRSS or CQC). Checked against a hand-built OpenSeesPy model.
- **Groups** — Define → Groups and Assign → Assign to Group (Ctrl+Shift+G): named,
  coloured sets of joints and elements to select again with Select → By Group.
  Deleting a member takes it out of its groups.
- **Interactive table editing** — Edit → Interactive Table Editing (Ctrl+T):
  joints, elements and joint loads as spreadsheets, with Excel copy and paste,
  added and deleted rows, and one validated undo step.
- **Calculation report** — File → Export → Report: model, loads, cases and the
  current results as a PDF or an HTML page, plus the steel frame check and the
  storey drifts when the project has design settings.
- **Section cuts** — Define → Section Cuts: the force and moment through a group
  (storey or pier shear, overturning moment), in the Results panel of static
  cases.
- **Modal damping** — a transient case can damp each of its first N modes by
  the same ratio ζ (OpenSees `modalDamping`), alone or with Rayleigh damping.
- **Support springs** — Assign → Joint → Springs: elastic springs to ground per
  DOF, their force reported as the joint's reaction.
- **OpenSees coverage** — 24 more uniaxial materials (IMK, Pinching4, dampers,
  pile springs, Parallel/Series/MinMax wrappers …) in one generic form; twoNodeLink
  and Triple Friction Pendulum links; LayeredShell / PlateFiber shells with plate
  materials and RC fibre templates; Constant, Trig, Triangle, Rectangular and
  Pulse series and multi-support excitation; every solver option OpenSeesPy 3.8
  runs; and Custom OpenSees Commands for anything else. The F1 help has a menu
  map and a glossary of every OpenSeesPy command saying where it lives in the app.
- **Seismic loads by the equivalent lateral force method** — Define → Seismic
  Loads: ASCE/SEI 7-16 §12.8 (Cs with its caps and minimums, k-exponent
  distribution) or TBDY 2018 §4.7 (SaR = Sae / Ra, the 0.04 I SDS minimum, the
  ΔFN top force). Storey weights are the masses the analysis uses; the period is
  typed or taken from the code's empirical formula. A preview shows W, V and the
  force of every storey; OK writes `EQ X` / `EQ Y` (and `±e` cases with
  accidental eccentricity in 3D) as load patterns with static cases, refilling a
  pattern of the same name — such as the combination generator's empty `EQ X`.
- **A portal frame wizard** (Define → Create Portal Frame): bays and bay width,
  eave height, one slope / two slopes / flat, the column and rafter sections and
  fixed or pinned bases, in the XZ or YZ plane (a 2D model always in XZ). Column tops follow the roof
  line, so an interior column comes out as tall as the roof above it, and the
  whole frame is one undoable step that arrives selected for copying.
- **Materials** — `Steel01`, `Steel02`, `Concrete01`, `Concrete02`,
  `Concrete04` (Popovics), `ElasticPP`, `Hardening`, `Hysteretic`,
  `HystereticSM`, elastic uniaxial and `ElasticIsotropic`.
- **Sections** — `ElasticSection`, fiber sections (rectangular / circular
  patches, straight rebar layers, a W-shape template), `SectionAggregator`,
  `BeamWithHinges`, and `ElasticMembranePlateSection` (E, ν, h, ρ) for shells;
  geometric transformations and beam integration rules are assignable per
  element.
- **RC walls** — Assign → Frame → RC Wall (MVLEM): the selected vertical members
  of a 2D model become OpenSees `MVLEM` wall segments, with concrete and steel
  fibres across the wall (optional boundary elements) and a shear spring per
  segment height.
- **Concrete Section Wizard** — Define → Concrete Section Wizard: a rectangular,
  circular, T or L reinforced concrete section from its dimensions, clear cover,
  bar sizes (metric φ or US #) and counts, ties and strengths. It adds the cover
  and core concrete (`Concrete02`, or the cyclic `ConcreteCM` of Chang and
  Mander; the core confined after Mander when asked) and
  the bars (`Steel02`), a fiber section, and optionally an elastic section with
  the ACI 318-19 cracked inertia (0.70 Ig columns, 0.35 Ig beams), in one undo
  step.
- **Section Designer** — Define → Section Designer: draw any cross-section with
  a command line (`rect`, `circle`, `poly`, `ishape`, `channel`, `tee`, `angle`,
  `tube`, `pipe`, `hole …`, `move`, `delete`, `center`) or import its closed
  outlines from a DXF (holes found by nesting, scaled by `$INSUNITS`). It shows
  the area, centroid, second moments, principal axes, elastic and plastic moduli
  and the Saint-Venant torsional constant (solved numerically, hollow shapes
  included), and adds an elastic section or a fiber section of one material.
- **AISC v16 shape library** — pick a shape by name in Define → Section
  Library → "Add from AISC…" (1,660 shapes across 13 families). The data is
  US customary and is shown both as published and converted to the project's
  units; E and G stay the material's business. See
  [`src/opensees_studio/data/README.md`](src/opensees_studio/data/README.md)
  for provenance, licence and how the numbers were cross-checked.
- **Seismic isolators** — elastomeric bearings (plasticity and Bouc-Wen,
  2D/3D) and sliding bearings (`flatSliderBearing`, `singleFPBearing`) with
  Coulomb, velocity-dependent and normal-force-dependent friction models.
- **Analyses** — static (load- or displacement-controlled), modal
  (deterministic solver selection, see below), displacement-controlled
  pushover, transient time-history with Rayleigh damping. Chained workflows:
  gravity preload → `loadConst -time 0.0` → pushover or transient. Numberer
  and system options per case.
- **Temperature loads** — Assign → Frame → Temperature Load: a uniform change
  and a gradient across each local axis of elastic members (α ΔT, α g), in static
  cases. OpenSees' elastic elements take no thermal load, so the fixed-end forces
  are applied as equivalent joint loads and added back to the member forces:
  diagrams, combinations and the steel check see `N = EA (ε - α ΔT)` and
  `M = EI (κ - α g)`.
- **Influence lines and moving loads** — an *InfluenceLine* case walks a unit
  load along a chain of frame members (a girder, a crane runway), one linear
  solve per stop, keeping every displacement, reaction and member end force.
  Display → Influence Line plots any of them against the load's position and
  moves a vehicle (axle loads and spacings, e.g. the HL-93 truck) across it in
  both directions, reporting the extreme effects and where the front axle stood.
- **Staged construction** — a *Staged construction* case builds groups of
  elements stage by stage, removes shoring and formwork, and applies each
  stage's loads on the deformed, stressed state of the stages before. New
  elements appear stress-free, new joints at their design position (column
  shortening since built) or following the deformed structure; a stage's self
  weight weighs only what it builds. One result step per stage
  (`examples/staged_frame.osmodel`). Marked time-dependent, the case runs in
  concrete age (days) with creep and shrinkage after the fib Model Code 2010
  (`TDConcreteMC10`, Define → Concrete Creep & Shrinkage). Post-tensioning
  tendons (Assign → Frame → Tendon) act as their equivalent loads: a parabolic
  profile, friction and wobble losses and a long-term loss.
- **Soil-structure interaction for piles** — Assign → Frame → Pile Soil
  Springs builds p-y (Matlock clay, API sand), t-z and q-z springs along a pile
  from its diameter and the soil layers.
- **Load combinations and envelopes** (Define → Load Combinations…) — Linear
  Add, Envelope (max/min), Absolute Add and SRSS of static and response spectrum
  cases, or of other combinations, each with a scale factor. Combining is
  post-processing on stored results: Analyze → Run runs only the cases a
  combination still needs, then combines, and Display → Show Results Of…
  switches between stored results. An envelope draws its max and min force
  diagrams together, offers Max/Min in the deformed shape, and its tables (and
  CSV export) list both. Adding a possibly nonlinear case warns that
  superposition does not hold. A response spectrum case gives displacements,
  reactions, element forces and shell resultants (SRSS or CQC of the response
  to every mode's equivalent load), so a combination with one has forces too.
  **Generate from a design code…** adds the combinations of ASCE 7-16 (LRFD or
  ASD), EN 1990 (ultimate 6.10, seismic, serviceability characteristic,
  frequent and quasi-permanent, with the ψ factors of Table A1.1) or
  TS 500 / TBDY 2018 (G+nQ±E, 0.9G±E) from cases tagged Dead, Live, Roof live,
  Snow, Rain, Wind and Earthquake, wind and static earthquake both ways, with an
  optional 100% + 30% orthogonal earthquake rule, optional ASCE 7 overstrength
  (`Ω0 E`) combinations, and an envelope per group.
- **Results database** — every finished case is appended to
  `<project>_results.sqlite` beside the model: one row per node, element and
  step (displacements, reactions, local forces, shell resultants, storey shear,
  section cuts, modes and mode shapes) with indexes for the usual lookups. One
  run per case: re-running a case replaces its numbers, and
  **Analyze → Delete All Results** clears the file. It is a plain SQLite file, so a notebook, a
  spreadsheet or `sqlite3` can ask questions without opening the application.
  **Analyze → Run All Cases** (`Shift+F5`) and **Run Selected Cases…** run a
  whole batch in one child process.
- **Batch runs of many files** — **File → Run Batch…** solves a list of
  `.osmodel` files (or every one in a folder) unattended: all cases or the ones
  named, several files at a time, a progress row per file and Cancel. Each
  project keeps its results beside it (`<project>_batch_results/` plus the
  results database), and opening it later offers to show them without solving
  again while the model is unchanged. A summary (status, time, error per file)
  is written as `batch_summary.json` and `.csv`. Without the window:

  ```bash
  python -m opensees_studio.batch models/ extra.osmodel --cases all --jobs 4
  ```

  (`--cases "Dead,Modal"` picks cases by name or id, `--engine` another engine,
  `--summary` another summary path; a packaged build takes `--batch` instead.)
- **Response spectra, by hand or by code** — in Ground Motions → Target
  spectrum: a **user table** (period in s, Sa in g), a spectrum from **ASCE/SEI
  7-16** (the mapped Ss and S1 with a site class, using Tables 11.4-1 and 11.4-2
  and Eqs. 11.4-1 to 11.4-4, or SDS, SD1 and TL directly) or the TBDY 2018
  spectrum. "Use as case spectrum" tabulates it — corners included, g turned
  into the project's acceleration unit — for a response-spectrum analysis case
  to read. The tables are transcribed from the standard and pinned by tests; a
  site class F, or class E beyond the tables, is refused by name because ASCE
  7-16 sends those to a site-specific study (§11.4.8).
- **Ground motions** — a project catalog with relative, hash-checked record
  references; AT2, two-column and single-column readers; PGA / PGV / PGD /
  Arias / D5-95 metadata; scaling by PGA, Sa(T1) or a period range;
  TBDY-2018 design spectra (horizontal and vertical) and user target spectra;
  sine and sine-beat generators.
- **Post-processing** - deformed shape (with scale slider), animated mode
  shapes, axial / shear / moment diagrams, pushover curves (in display
  units), time-history plots, hysteresis loops, response-spectrum SRSS / CQC,
  snapshot and video export, full-precision CSV of the result tables.
  Right-click a frame member while a force diagram or a deformed shape is on
  screen to open its axial, shear V2/V3, torsion, moment M2/M3,
  absolute/relative deformation and applied-load diagrams in a 3 x 3 grid, with
  the extreme values labelled, result and units pickers, and a distance cursor
  that reports the value at any section.
- **A reference triad at the origin** — small red / green / blue arrows
  labelled X, Y and Z, sized from the model, so the direction the elements run
  in is never in doubt in an isometric view.
- **Material tester** — run any supported uniaxial material through a
  monotonic or cyclic strain protocol in an isolated model and plot the
  stress–strain history, without a full analysis.
- **Import** — File → Import → DXF Drawing: straight bars from `LINE` and
  `POLYLINE` entities, with the layers to keep ticked in the dialog, the
  drawing's own units (`$INSUNITS`) converted to the project's and the plane
  (plan, elevation or 3D) chosen before anything is inserted. Endpoints that
  land on the same point become one node, and what is not a straight bar —
  circles, text, hatches — is counted and reported rather than guessed at. The
  whole import is one undo step. File → Import → PORTICO Model (.s3d) opens a
  model saved by [PORTICO](https://github.com/jpreyes/portico-core) as a new
  project: nodes, supports, springs, masses, frame members (Timoshenko when the
  section has shear areas), releases, static load cases and combinations, every
  value scaled from the file's unit system (`kN-m`, `kip-in`, …) to the one
  you pick, and PORTICO's local axes (beam y up) mapped onto OpenSees' (beam z
  up). Quadrilateral areas become `ShellMITC4`, diaphragms rigid diaphragms on
  PORTICO's master node, links rigid links or equalDOFs, and the mass source
  comes along; triangular areas and spectrum cases are not imported yet and are
  counted and reported.
  File → Import → SAP2000 Text (.s2k / .$2k) reads the text tables of a
  SAP2000 model as a new project: joints, restraints, added joint masses and
  support springs, grid lines, frames with their sections (rectangular, I, pipe,
  tube, general; a nonprismatic one is subdivided into elastic pieces, 12 by
  default, from its segment table), materials, local-axis angles (mapped to the
  nearest section orientation), end releases, per-frame property modifiers and
  rigid diaphragms
  (with their floating centre-of-mass master), load patterns
  with joint, distributed and point frame loads, temperature loads, support
  settlements and frame added mass, linear static, eigen modal and
  response-spectrum cases, combinations and four-node shells, scaled from the
  file's `CurrUnits` to the nearest unit system. SAP2000's local 2 and 3 are mapped onto OpenSees'
  axes member by member, and every table it does not read is named in the log.
  The exact local-axis rotation is written on S2K export; the S2K import maps
  it to the nearest section orientation (IFC carries it exactly).
  Written from the text format alone (SAP2000 is a trademark of Computers and
  Structures, Inc.; no CSI software is used). **The S2K import is a work in
  progress:** the tables it reads, the approximations and the unsupported
  objects are listed in
  [docs/sap2000-import-status.md](docs/sap2000-import-status.md).
  File → Import → OpenSees Tcl Script (.tcl) reads the model-building part of
  an OpenSees Tcl file (the archived examples included): model dimensions,
  nodes, supports, materials, sections, elements, constraints, plain load
  patterns and their time series. Variables, `expr`, `foreach`, `if`, `proc`,
  `source` and `for` are interpreted, never executed; analysis commands and
  unsupported items are counted in the log.
  File → Import → IFC (.ifc / .ifczip, IFC2x3 or IFC4) builds the project from
  the file's **structural analysis model** (point connections with their
  supports and springs, curve members with their end releases, four-cornered
  surface members as shells, load cases with nodal, point, line and surface
  loads and self weight, factored combinations), or, when the file has none,
  from its **physical model**: the axes of IfcColumn, IfcBeam and IfcMember
  solids are joined where members meet at faces (a beam end onto the column it
  stops at, a secondary beam onto its girder, which is split there), slabs and
  walls become one shell each attached to the nearest member nodes, and the
  column bases at the lowest level can be fixed. A profile named after an AISC
  shape takes the library's properties, any other from its dimensions; E, G,
  density and yield stress come from the material property sets, and every
  value is converted from the file's declared units. A file written by File →
  Export → IFC imports back to the same model.
- **Interface language** — Options → Language: English or Spanish (menus,
  dialogs, buttons; the help pages stay in English).
- **Concrete design** — Design → Concrete Frame Check (ACI 318-19) checks
  every member whose section is a fibre section of concrete and bars (the
  Concrete Section Wizard's or any other, also when the analysis uses its
  cracked elastic twin): P-M interaction by strain compatibility with φ by the
  net tensile strain, biaxial bending (Bresler), shear with the given stirrups,
  the torsion threshold, minimum steel and εt ≥ 0.004 in beams, with the ratios
  painted on the model (Verification Manual D-15).
- **Base plates and bolted connections** — Design → Base Plates checks the
  plate and anchor rods of every column base over the design load sets (AISC
  Design Guide 1, ACI 318-19 Chapter 17): pinned bases concentric, fixed ones
  with their moment, cantilevers by column kind (I-shape, HSS, pipe), and
  sizing of the plate thickness. Design → Connections by Joint classifies every
  member end (beam to column flange or web, beam to girder, brace, splice, base),
  suggests the connection, and checks the shear tabs of simple beam ends (AISC
  Manual Part 10). Design → Base Plate & Anchors and Design →
  Bolted Connection (prying action, eccentric bolt groups) remain as
  calculators that can read the demands from a support's reaction.
- **Design basis and the Direct Analysis Method** — Design → Design Basis
  (AISC) sets the method (LRFD/ASD), the stability design (AISC 360 Chapter C
  or Appendix 7), the lateral system of each direction with R, Ω0 and Cd of
  ASCE 7 Table 12.2-1, and the steel grade of each shape family (A36, A572
  Gr. 50, A992, A588, A500 Gr. B/C, A1085, A53, with the AISC Manual Table 2-4
  defaults). Design → Direct Analysis Method turns every ASCE 7-16 LRFD
  combination into one second-order case: P-Delta in every frame, stiffness
  ×0.8 (C2.3, τb = 1 with 0.001 α Yi), and the notional loads `0.002 α Yi` of
  that combination's own factored gravity; it then reports Δ2/Δ1 per storey
  (C2.2b(d)), and the steel check reads these cases with K = 1. Design →
  Built-Up Shapes defines welded I-shapes and plate girders from their plates
  (kc flange limits, F4/F5, web shear with stiffeners). Design →
  Member Classification shows the physical members (collinear elements of one
  section), their role and the unbraced lengths Lx, Ly and Lb from their bracing
  points; the check uses those lengths, so a meshed member keeps its real ones.
- **Design** — AISC 360-16 member check (LRFD or ASD) for W, M, S, HP,
  channels, tees, equal-leg angles, rectangular and round HSS and pipes:
  tension (D2), compression (E3, E4, E7), flexure (F2–F10), shear (G2–G6) and
  H1 interaction over the combinations already run, at 25 stations, with `Cb`
  from the moment diagram and per-member K, Lb, Cb, net area and shear-lag
  overrides; an optional **B1 P-δ amplification** (AISC 360-16 C2.1b) covers
  the member curvature a first-order analysis leaves out. A **seismic system**
  (AISC 341-22) adds the Table D1.1 width-to-thickness check with `Ry` and
  `Ca`, the SMF joint checks (E3.4a, panel zone J10.6 and continuity plates
  E3.6f), the SCBF F2.3 capacity design and F2.5b brace limits, and the OCBF
  F1.4/F1.5/F1.6 coverage. Separate dialogs edit the **AISC 358-22 RBS
  connections** (5.7 and 5.5 web connection), the **SCBF gusset plates**
  (Whitmore, yielding, buckling, F2.6c demands and weld), the **SCBF column
  splices** (F2.6d) and the **AISC 360 Chapter J connection checks** (J2–J10).
  Assign → Frame → Local Axes rotates a 3D member's section about its axis;
  IFC export and import preserve it. Design → Display Steel Ratios paints every
  member by its ratio; Design →
  Generate Notional Loads writes the AISC 360 C2-1 `0.002 α Yi` pattern
  (α = 1.0 LRFD, 1.6 ASD); Design → Storey Drift Check compares amplified
  storey drifts with ASCE 7, NCh433 or Eurocode 8. The report and the
  calculation memory print the member, joint, connection, gusset, splice and
  Chapter J checks. The settings are saved with the project.
- **Export** — the model, with or without one analysis case, as a plain
  OpenSeesPy script generated from the same command sequence the solver
  receives, so it reproduces the application's numbers; or as **IFC4** (File →
  Export → IFC): the physical BIM model (IfcColumn, IfcBeam, IfcMember, IfcSlab
  with their profiles and materials, in their storeys) and the structural
  analysis model (nodes, supports, members with releases, load cases with their
  loads, combinations), linked element by element, with each section's exact
  values in an `OpenSeesStudio_Section` property set so the file imports back
  unchanged. Uses `ifcopenshell`, which the desktop install brings.
  File → Export → SAP2000 Text writes the frame model back as SAP2000 text
  tables (what the import reads, so the file imports back to the same model),
  including each member's local-axis angle, and reports what it leaves out.
- **Meshing** — Edit → Mesh: split members into pieces no longer than a target
  size (their section, material and distributed loads follow them), subdivide
  shells `m x n` in their own natural coordinates (a general quadrilateral meshes
  inside its own edges, and two meshed shells share their common edge), and join
  it all up: a bar is split at every node lying on it and where it crosses
  another bar, so a frame that meets a slab edge is connected there. A new node
  on a supported shell edge inherits the DOFs both of that edge's corners have
  restrained, so meshing a slab does not quietly unsupport it. One undo step, and
  the dialog shows what it will add before you accept it.
- **Connecting a model** — Edit → Merge Joints makes joints closer than a
  tolerance one (on the selection or the whole model; elements, loads,
  constraints, masses and restraints follow the joint that stays), and Edit →
  Divide Frames at Joints splits every frame and truss at the joints lying
  inside it, and where members cross. Select → Loose Joints, Joints Inside
  Members and Joints on Shell Edges find what still looks connected and is not.
- **Self weight** — a pattern's self-weight multiplier loads every member with
  a unit weight: frames (elastic, fibre and aggregated sections, BeamWithHinges)
  as a uniform load, trusses half to each joint, and shells as consistent nodal
  forces. Every new model starts with a DEAD case that does exactly that.
- **Stability check** — Analyze → Check Model Stability looks for mechanisms
  before anything is solved: the singular values of the assembled stiffness
  matrix, each zero reported with the joints and DOFs that move (and selected in
  the view), plus any free DOF that no element stiffens.
- **Model health** — Edit → Check Model for Duplicates: coincident nodes and
  elements that describe the same member twice, with a tolerance that follows
  the size of the model. Pairs that are deliberate — the two nodes of a
  zero-length element or a bearing, nodes tied by `equalDOF` — are listed with
  their reason and left alone; the repair merges the rest, repoints the loads
  and constraints, and is one undoable step.
- **Review before running** — Analyze → Check Model (F6) finds, without running
  anything, the nodes nothing connects, elements that point at a deleted node or
  have zero length, parts of the model with no support, and **static
  instability**: groups of nodes that can move without deforming any element (a
  square of bars with no diagonal, a beam pinned at one end, a truss modelled with
  free rotations). Each finding names the nodes and elements involved, says what
  to look at, and can be selected in the canvas. Run performs the same check on
  its way in: errors stop at the list with *Run anyway* offered (Cancel is the
  default), warnings go to the console. Stability is a linear, small-displacement
  test of the connectivity, independent of units and of member stiffness. Each
  mechanism is named — sliding or turning as a rigid body, a joint rotating
  freely, members in line, a frame that sways — with what to do, and **Show the
  motion** animates it on the model.
- **Copying geometry** — Edit → Move, Replicate (an offset applied N times,
  which carries the loads of the copied nodes and elements with it) and Mirror
  across a global plane.
- **Persistence** — projects save as a single JSON `.osmodel` file
  (Pydantic-validated, round-trip-clean) with a schema version, and a
  pre-run snapshot offers to recover unsaved work after a crash.
- **Contextual help** — press **F1** and the manual opens on whatever you are
  looking at: the item under the cursor in a menu that is open, the dialog on
  top, or the contents page otherwise. It is written for the questions that come
  up while modelling — how a command is used, what each parameter means, and the
  mechanics behind it (what a slope does to a portal frame, why a fibre section
  yields, what Rayleigh damping is fitted to, why a plate mesh is stiff until it
  is refined).
- **Examples** — 30 verified examples bundled, including the OpenSees Wiki
  Examples-1 through Example-4 family, an RC frame pushover, isolated
  frames, a 3-storey building with rigid diaphragms and a moment-curvature
  workflow. See
  [`examples/README.md`](examples/README.md).

## Tech stack

| Layer        | Library                              |
| ------------ | ------------------------------------ |
| GUI          | PySide6 (Qt 6)                       |
| 3D viewport  | PyVista + pyvistaqt (VTK)            |
| 2D plots     | pyqtgraph                            |
| Solver       | OpenSeesPy 3.8.0.0                   |
| Numerics     | NumPy                                |
| Storage      | Pydantic v2 (model), h5py (results)  |
| Tests        | pytest, pytest-qt                    |
| Lint / type  | ruff, mypy                           |

## Architecture

Strict MVVM + service layer. The `core` package is pure Python — no Qt,
no OpenSeesPy imports — and is fully unit-testable in isolation.

```
views (Qt)  →  viewmodels  →  services (OpenSeesRunner, Persistence)  →  core (model)
```

See [`docs/architecture.md`](docs/architecture.md) for the long form,
including the canonical OpenSeesPy command sequence the runner emits.

Analyses run in a child process. Before every run the project is written
to `<stem>.run-snapshot.osmodel` next to the project file (your own
`.osmodel` is never touched), and `python -m opensees_studio.run` solves
that snapshot while the window stays responsive. The Run dialog shows the
step progress and has a Cancel button that stops the solver and leaves
the model unchanged. If OpenSees exits hard, the application survives and
shows the exit code with the solver's last messages. If the application
itself is killed mid-run, the next File > Open of that project offers
"Restore unsaved changes from the last analysis run?"; the snapshot is
removed by a normal save or close, and when File > New or File > Open
replaces the project.

### Modal analysis: deterministic results

ARPACK, the OpenSees default eigen solver, keeps its random start vector
across `eigen` calls, so only the first eigen call of a process is
reproducible: a second call flips mode signs and rotates the basis of a
repeated eigenvalue pair. OpenSees Studio makes modal results independent
of that history:

- The modal case solver `Auto` (the default) uses the dense `fullGenLapack`
  solver at or below 500 free DOF (a direct method, bit-identical on every
  call; about 1 s at 500 DOF) and `genBandArpack` above it. The threshold
  is `core.modal.DENSE_EIGEN_MAX_FREE_DOF`; the environment variable
  `OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF` overrides it. Above the threshold
  the analysis CLI runs every ARPACK case that follows an earlier eigen
  call in a fresh child process, so each ARPACK eigen call is the first of
  its process. The solver actually used and the free DOF count are shown
  in the results panel, the spectrum dock and the run log, and stored in
  the results manifest, so a model crossing the threshold is visible (the
  two solvers agree to about 1e-13 relative on the examples; the two
  storey shear frame differs by 6.3e-7).
- An explicit `genBandArpack` or `fullGenLapack` is honoured.
  `symmBandLapack` is refused with a message (it needs a positive definite
  mass matrix; lumped masses leave rotational DOF massless). Other solver
  names that this OpenSeesPy build silently maps to ARPACK are not offered;
  a saved case carrying one loads with a notice and runs with `Auto`.
  Projects saved before this change store `genBandArpack` explicitly and
  keep it; set the case to `Auto` to get the routing.
- Mode shapes have a deterministic sign (largest absolute component
  positive; components within 1e-9 of the maximum are tied and the lowest
  DOF index wins, which matters on symmetric frames), and the modes of a
  repeated eigenvalue are made mass-orthogonal (the dense solver returns a
  mass-oblique pair there).
- `OPENSEES_STUDIO_IN_PROCESS=1` (debugging) runs the previous threaded
  in-process worker: below the threshold it is deterministic too, above it
  a second ARPACK call in the GUI process stays history dependent.

### Response spectrum: combination rules

- **CQC** (Complete Quadratic Combination, Der Kiureghian correlation,
  equal or per-mode damping) is the default for new response spectrum
  cases. Inside a repeated mode pair the eigen solver returns an arbitrary
  basis of the eigenspace, and different LAPACK builds return different
  ones. Before combining, each group of repeated modes is turned so one mode
  carries all of its participation in the spectrum's direction and the
  others none; CQC and SRSS then give the same result for every basis (on
  `space_frame_3d` the SRSS roof displacement used to differ by 12 percent
  between the dense and the ARPACK basis, and between Linux and macOS).
- **SRSS** is still available, and saved cases keep their stored rule. When
  the rule is SRSS and any two included modes have a frequency ratio (lower
  over higher) at or above 0.9 (`closely_spaced_ratio` on the case), the
  result carries a warning naming the modes and ratios; it shows in the
  results panel, the spectrum dock and the run log.
- The CQC damping is the case's modal damping ratio; 0 or empty means the
  spectrum's own damping ratio (stored as "none", default 0.05). A CQC run
  never uses zero damping: if case and spectrum would both give zero, 0.05
  is used and a warning is issued. The damping field of the case dialog is
  enabled for CQC only.
- The participation factor and effective mass of a mode use the full modal
  mass (every DOF that carries mass), so the cumulative mass participation
  of a complete set of modes is 100 percent, never more.

## Install (no Python needed)

Prebuilt desktop bundles are attached to the
[releases](https://github.com/ogunc/opensees-studio/releases): download the
archive for your system, unpack it anywhere and run `OpenSeesStudio` (or
`OpenSeesStudio.exe`). The bundle carries its own Python, Qt and VTK. The
OpenSees solver has its own license and is not inside it: install it once from
Options → Solver, which downloads OpenSeesPy from PyPI after you accept its
license.

Unpack the whole folder, not the executable on its own: the libraries live
beside it. A bundle is about 1 GB unpacked, most of it the VTK renderer and the
Qt runtime.

The Linux bundle runs on Ubuntu 22.04 or later, Linux Mint 21 or later, Debian 12
and LMDE 6 (glibc 2.35 or newer), on x86-64.

The first launch of a downloaded bundle may be blocked by the operating
system, since these binaries are not code-signed: on macOS, right-click →
Open the first time; on Windows, "More info" → "Run anyway" in the
SmartScreen prompt.

Maintainers build and publish them with
`python packaging/build.py --gui-smoke --zip`; see
[`packaging/README.md`](packaging/README.md) for what that does and the
traps in it.

## Install (development)

**Desktop GUI** (includes Qt, PyVista, pyqtgraph, imageio):

```bash
git clone https://github.com/ogunc/opensees-studio.git
cd opensees-studio

python -m venv .venv
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # Linux / macOS

pip install -e ".[gui,dev]"
```

**Headless / web reuse** (core + services only, no Qt pulled in):

```bash
pip install -e .
```

This installs only the headless base set (pydantic, numpy, h5py, ezdxf), with
**no solver**: it models, exports and reports. Add the solver with
`pip install -e ".[opensees]"` (the `dev` extra already includes it). It is the
correct install for web backends, scripts, and Jupyter notebooks that reuse
`opensees_studio.core` or `opensees_studio.services` without the GUI.

**The solver is a separate program.** OpenSeesPy has its own license (free for
research, education and internal use; commercial redistribution needs a
license from its authors), so it is an optional extra rather than part of
OpenSees Studio. In the desktop app, Options → Solver shows whether it is
available, downloads it from PyPI after you accept its license (the downloadable
bundle does not include it), or points to another Python 3.12 that has
`openseespy`, or to a folder holding the package. Without it, Run, Check Model Stability and the
Material Tester are disabled. See `docs/adr/ADR-0003-solver-engines.md`.

**A second engine ships with it: [PyNite](https://github.com/JWock82/PyNite)**
(MIT). Choose it in Options → Solver → Engine to run linear static and P-Delta
cases of elastic frames and trusses with no download; it gives the same
results as OpenSeesPy on those models and refuses, with a message, anything it
does not model (nonlinear materials, shells, bearings, transient and modal
cases…), which then needs OpenSeesPy.

Python 3.12 is required: the `openseespywin` and `openseespylinux` 3.8.0.0
wheels declare `Requires-Python >=3.12`, and the Windows `opensees.pyd` links
against `python312.dll` (so use 3.12 exactly on Windows). Pin both
`openseespy==3.8.0.0` and `openseespywin==3.8.0.0` (already pinned
in the `opensees` extra of `pyproject.toml`).

## Quick start — the 60-second tour

```bash
python -m opensees_studio
```

Then:

1. **File → Open** → pick `examples/cantilever.osmodel`.
2. **Analyze → Cases** → run `Tip-Load`.
3. **Display → Show Force Diagram** → component **M3** → linear moment
   peaking at 50 kN·m at the fixed end. Component **V2** → constant
   -10 kN.
4. **Display → Show Deformed Shape** → the classic cantilever curve.

For a nonlinear walkthrough, open `examples/portal_pushover.osmodel`,
run the `Push-X` case, then **Display → Show Pushover Curve** — you'll
see the elastic ramp followed by a yield plateau as the fiber-section
hinges form at the column bases.

### Material Tester

**Define → Material Tester…** (Ctrl+Shift+T) opens a non-modal dialog that
drives one uniaxial material of the current project through a strain history
in an isolated zero-length model and plots stress against strain.

Protocols (all start in compression, the OpenSees sign convention):

- **Monotonic to amplitude**: 0 to -amplitude.
- **Symmetric cyclic, fixed amplitude**: N cycles of 0, -amplitude,
  +amplitude, 0.
- **Cyclic, increasing amplitude**: one such cycle per peak in a list of
  increasing peaks, for example `0.0025 0.005 0.01 0.02`.

*Steps per half-cycle* splits every branch (0 to peak, peak to opposite
peak, peak back to 0) into that many equal strain increments, so a cyclic run
records 3 × steps points per cycle.

Derived values under the plot:

- **Peak stress**: the stress of largest magnitude and the strain where it
  occurs.
- **Secant stiffness at peak**: peak stress divided by that strain.
- **Energy dissipated per cycle** (cyclic protocols): the area enclosed by
  each cycle, the integral of stress d(strain), in stress units (energy per
  unit volume).

**Export CSV…** writes two comment lines (`# material: …`, `# protocol: …`),
a header `strain,stress [<stress unit>]`, then one `strain,stress` row per
point with a point decimal separator. Only materials the tester can drive are
listed (nD `ElasticIsotropic` and `HystereticSM` are not); if a run still
fails, the dialog shows the error message instead of a curve.

### Precision, frame options and analysis settings

- **Numeric input**: every floating-point field accepts scientific notation
  (`1e-10`, `2.9e4`), keeps the full double and shows the shortest text that
  reads back to it. Out-of-range text is refused; the value commits on Enter
  or focus-out.
- **Results panel**: *Significant digits* (default 6, up to 15) changes the
  display only. *Export CSV...* writes the current table at full precision
  with the units in the header. Tables: static displacements, reactions and
  element forces, the pushover curve, modal frequencies, response spectrum
  peaks and modes, and the time history of a chosen node.
- **Assign > Frame > Geometric Transformation...**: Linear, PDelta or
  Corotational for the selected frames (vecxz in 3D as before). Also editable
  in the Properties dock. Default Linear.
- **Assign > Frame > Beam Integration...**: Lobatto, Legendre, NewtonCotes,
  Radau or Trapezoidal with 2 to 10 points for force and displacement
  beam-columns. Also in the Properties dock. Default Lobatto with 5 points.
- **Assign > Frame > Releases/Partial Fixity...**: release torsion or either
  bending moment at each end, optionally with a spring (moment per radian).
  The end hangs off a hidden node tied to the joint with `equalDOF` (a
  `zeroLength` carries the springs), so it works for elastic, force- and
  displacement-based members alike, and the joint's reaction includes it.
- **Assign > Frame > End (Length) Offsets...** and **Insertion Point...**:
  rigid joint offsets (`geomTransf -jntOffset`). Loads on a rigid zone go to
  the joint; a release at an offset end acts at the face (the model then runs
  with the Transformation handler). Offsets, rigid-zone factor and cardinal
  point are also editable in the Properties dock.
- **Editing a selection together**: with several joints or elements selected,
  the Properties dock edits what they share (restraints, masses, type, section,
  material, area, transformation, integration, offsets, cardinal point). Values
  that differ show `(varies)` and stay as they are unless changed; Apply is one
  undo step.
- **Assign > Frame > End (Length) Offsets... > Automatic from connectivity**:
  the rigid length at each end is the largest half-extent along the member of
  the sections of the other frames meeting at that joint.
- **Assign > Frame > Property Modifiers...**: multipliers on the elastic
  section (a derived section per distinct combination), the mass and the self
  weight. The shear-area modifiers act on sections that define As2 / As3.
- **Shear areas** (Define > Section Library, elastic section As2 / As3): the
  member runs as `ElasticTimoshenkoBeam`, verified against
  `P L^3 / 3 E I + P L / G As`. OpenSees 3.8 loads that element with
  full-length uniform loads only; point, partial and trapezoidal loads on it
  are refused.
- **Force diagrams** carry intermediate stations under span loads (uniform,
  point, trapezoidal, self weight) for static case results; combinations and
  envelopes still draw straight lines between the ends.
- **AISC shapes in 3D**: the strong axis `Ix` goes to Iy (the inertia gravity
  bends a horizontal 3D beam about), in 2D to Iz.
- **Assign > Frame > Trapezoidal Load...**: a load varying linearly over part
  or all of a member. Elastic and displacement-based members take it as three
  Gauss-point `-beamPoint` loads (exact end forces), force-based members as the
  native partial `-beamUniform`.
- **Analysis cases**: Static, Transient and Pushover forms have *Numberer*
  (Plain, RCM, AMD; default RCM) and *System* (BandGeneral, BandSPD,
  ProfileSPD, SparseGeneral, UmfPack, FullGeneral). SparseGeneral notes that
  partial pivoting is always on in this build, so `-piv` is not offered; a
  saved project that carries it loads with a notice and runs without it.
- **Hardening material**: `uniaxialMaterial Hardening` (E, sigmaY, H_iso,
  H_kin, optional eta) in the material library and the Material Tester.
- **Fiber Section Editor, Add Template, W-shape (wide flange)**: d, bf, tf,
  tw, fibres across the web depth and through each flange (WFSection2d Nfw
  and Nff), one material. The three patches reproduce `WFSection2d`.

### Ground motions

**Define → Ground Motions…** (Ctrl+Shift+G) manages the project's catalog of
acceleration records: import, metadata (PGA, D5-95 significant duration,
Arias intensity), an acceleration trace preview, remove, and relink.

Supported formats, auto-detected from content with an explicit override:

- **PEER AT2 / NGA**: header lines with `NPTS, DT` in either the new NGA or
  the old SMD spelling, values row-wise.
- **Two columns**: `time acceleration` pairs, whitespace or comma separated.
  The time step must be uniform; a non-uniform column is rejected.
- **Values only**: a bare list of accelerations (any number per line, read
  row-wise) plus a dt you provide.

Records are referenced, not embedded: the project file stores a path
relative to the `.osmodel` plus a sha256 content hash, and the sample values
are re-read from the record file on load. This keeps project files small and
diffable, and it respects the record providers' terms: PEER NGA records may
not be redistributed, so neither this repository nor your `.osmodel` files
carry them. Move a project together with its record files; if a file is
missing or its content changed, the catalog marks the record and analysis
refuses to run that case until you relink the file. A record imported into a
project that has never been saved keeps an absolute path until the first
save, which rewrites it relative to the new `.osmodel`.

**Spectra.** Selecting records plots their elastic response spectra
(pseudo-acceleration, 5 % damping, log period axis) in g. The oscillator
response uses the Nigam-Jennings piecewise-exact recurrence, so the spectrum
depends only on the record's own sampling. A record's samples are converted
to g from its **Units** (g or project units, set in the dialog; a PEER header
that says `IN UNITS OF G` sets it on import). Records with unknown units are
not plotted or scaled until you set them.

**Target spectrum.** Either the TBDY 2018 horizontal design spectrum
(TA = 0.2 SD1/SDS, TB = SD1/SDS, TL = 6 s) or a user table of `period  Sa[g]`
rows interpolated log-log. The TBDY spectrum takes SDS and SD1 directly, or
the mapped Ss and S1 of the AFAD TDTH map with the site class (ZA to ZE; ZF
needs a site-specific study and is refused) and the earthquake level DD-1 to
DD-4 as a label: SDS = Ss Fs and SD1 = S1 F1 with Fs and F1 from Tablo 2.1
and 2.2 (linear between the breakpoints, clamped outside), and the project
stores both the inputs and the derived values. The editor shows the derived
SDS, SD1 and corner periods read-only, and the **Vertical spectrum** option
builds SaeD of Md. 2.3.5 instead (TAD = TA/3, TBD = TB/3, plateau 0.8 SDS,
TLD = TL/2). The vertical spectrum is defined only up to TLD: the overlay
stops there and period-range or Sa(T1) scaling against it refuses periods
beyond TLD with a message. The target is stored in the project and overlaid
on the spectrum plot.

**Scaling.** Three methods, previewed before Apply:

- **PGA**: factor so the record's PGA equals a target PGA in g.
- **Sa(T1)**: factor so the record's Sa at the structure's period T1 equals
  the target's.
- **Period range**: factors for the selected set so the mean spectrum of the
  scaled set is not below alpha times the target over [a T1, b T1], either
  one uniform factor or individual factors (each record first fitted to the
  target shape, then the same uniform step); consecutive selections can be
  paired as H1, H2 with the SRSS of the pair. The preset "TBDY 2018 (engineer
  to confirm)" uses a = 0.2, b = 1.5 and alpha = 1.3 for pairs; confirm it
  against the standard before relying on it. The preview reports the
  governing period and the minimum mean-to-target ratio. The criterion is a
  mean over the set, and TBDY 2018 applies it to at least 11 records (11
  pairs in SRSS mode): with fewer the Scale panel shows a warning, because
  the mean of a small set is not the one the criterion has in mind; the
  factors are still computed and can be applied.

Scale factors live on the time series: Apply writes `PathTimeSeries.factor`
(which also carries the g to project-unit conversion) through one undoable
command, and the catalog record itself is never changed.

**Generated inputs.** **Generate…** in the same dialog builds a synthetic
excitation and stores it as a time series, never as a catalog record: a
continuous sine (amplitude, frequency, duration, optional linear ramp-in and
ramp-out given in cycles) or a sine-beat train (cycles per beat, number of
beats, pause between beats; each beat is a sine under a half-sine envelope,
scaled so its peak equals the amplitude). A plain sine becomes a native
OpenSees `Trig` series; a ramped sine or a sine-beat becomes an embedded
`Path` series with `file_path="generated:<kind>"` and its parameters stored
in the `generator` field, so **Edit…** reopens the generator with the stored
values and swaps the series in place (undoable). The amplitude is given in g
or in project units and the conversion lives in the series factor. The
preview shows the trace and its response spectrum over the current target.
The preset "IEEE 693 style (engineer to confirm)" (5 beats of 10 cycles,
2 s pause) is a starting point to be confirmed against the standard's text;
every value stays editable.

### Seismic isolators (elastomeric and sliding bearings)

**Assign → Joint → Bearing…** connects two selected joints
(bottom, then top; coincident or separated by the bearing height) with an
OpenSees `elastomericBearingPlasticity` (bilinear shear with return-mapping
plasticity), `elastomericBearingBoucWen` (smooth Bouc-Wen shear),
`flatSliderBearing` (friction, no restoring stiffness) or `singleFPBearing`
(single friction pendulum) element.
Shear parameters: `Kinit` (initial stiffness), `Qd` (characteristic
strength), `alpha1` (post-yield stiffness ratio, 0 <= alpha1 < 1), `alpha2`
and `mu` (nonlinear hardening `alpha2 Kinit |u|^mu`, 0 for a plain bilinear
loop) and, for Bouc-Wen, `eta`, `beta`, `gamma`. The axial (`-P`) and moment
(`-Mz`) responses are uniaxial materials picked from the material library;
a 3D project also asks for the torsion (`-T`) and `-My` materials. Optional
`-shearDist`, `-doRayleigh` and `-mass` are exposed; the runner always
writes the `-orient` vectors (the element axis, or the vertical for
coincident nodes, with the shear along global X, or the user's six values),
because OpenSees 3.8 aborts on a zero-length bearing without them.
The dialog shows the derived yield displacement `u_y = Qd / (Kinit (1 -
alpha1))`, the yield force `Qd / (1 - alpha1)` and the secant stiffness at a
displacement you type. Bearings draw with the line style of the other
zero-length elements, are selectable, show a hover tooltip with the key
parameters and list their parameters in the property editor. The runner's
loops were verified against the closed-form bilinear loop (energy per cycle
`4 Qd (u_max - u_y)`) in `tests/integration/test_elastomeric_bearing.py`,
and `examples/isolated_portal2d.py` puts the Example 1b frame on two
isolators under BM68elc.

The sliding bearings reference a friction model from **Define → Friction
Models…** (the Material Library pattern: `Coulomb` with `mu`, `VelDependent`
with `muSlow`, `muFast`, `transRate`, and `VelNormalFrcDep` with `aSlow`,
`nSlow`, `aFast`, `nFast`, `alpha0`, `alpha1`, `alpha2`, `maxMuFact`; every
edit is undoable and a model in use by a bearing cannot be deleted). The
bearing dialog then takes `Kinit` (stick stiffness), for the pendulum
`Reff`, the same `-P`, `-Mz`, `-T`, `-My` materials and optional flags plus
`-iter`, and shows, for an axial load you type, the slip displacement
`mu W / Kinit`, the restoring stiffness `W / Reff` and the isolated period
`2 pi sqrt(Reff / g)` in the project units. Validation mirrors every input
that makes OpenSees 3.8 terminate the process (zero or negative friction
coefficients, negative transition rate, zero `aSlow` or `aFast`, missing or
degenerate `-orient`) or fail the analysis (zero `Reff` or `Kinit`, zero
iterations). `tests/integration/test_friction_bearing.py` verifies the
rectangular flat-slider loop at `mu W`, the sloped pendulum loop with
stiffness `W / Reff`, the energy `4 mu W (u_max - u_y)` per cycle, the
velocity dependence of `VelDependent`, and the pendulum period;
`examples/isolated_portal2d_fp.py` is the isolated frame on single FP
bearings under the same record. The triple friction pendulum is available from
**Assign → Joint → Link** in a 3D model (ISO-3).

## Run the test suite

```bash
pytest tests/unit          # pure-logic tests, milliseconds, no Qt platform needed
pytest tests/gui           # Qt event-loop tests (pytest-qt)
pytest tests/integration   # real OpenSeesPy runs on bundled examples
```

CI runs lint + the non-`slow` subset on Linux / macOS / Windows
× Python 3.12.

## Profiling large models

The application has an opt-in performance monitor. Launch with `--profile` (or
`OPENSEES_STUDIO_PERF=1`) and open **Help → Performance monitor** to see
per-stage timings for the SAP2000 importer, project I/O, the analysis child, the
renderer and undoable commands, plus UI stalls and a one-shot `cProfile`.
`--perf-json report.json` writes the same report on exit.

For repeatable large-model measurements, use the synthetic grid benchmark:

```bash
python tools/perf_bench.py --size large --profile
python tools/perf_bench.py --size xlarge --solver --cprofile
```

See [`docs/performance-profiling.md`](docs/performance-profiling.md) for the
stage names, the JSON format and how to read a report.

## Screen-relative markers

Node markers, supports, load arrows, reactions and mass markers are sized as a
percentage of the viewport height, not as a fraction of the model. They keep the
same on-screen size while you zoom, and **Display → Display Options** sets each
percentage; label height is a separate pixel value. Joint masses are drawn as
purple diamonds when that option is on. The sizes and toggles travel with the
project.

Member end releases are colored dots on the bars: violet torsion, orange M2, red
M3, and yellow partial fixity. **View → Visibility → Releases** shows or hides
them independently of the rigid end-offset bars under **Frame Assignments**.

## Show, hide and isolate

**View > Hide Selected** (Ctrl+H) hides the current selection in the active
viewport. **View > Isolate Selected** (Ctrl+Shift+I) shows only the selected
elements and their joints, or only the selected joints; it is also in the
right-click menu. **View > Show All Objects** restores every hidden object and
clears a grid-line view. A box selection never picks objects hidden in that
viewport, so a drag selects only what is actually drawn.

## Stability check

**Analyze → Check Model Stability** captures the initial stiffness as a sparse
CSR matrix through OpenSees' `PythonSparse`; a small model uses a dense
reference, while a large one uses a shifted sparse eigenvalue search after
diagonal scaling. The report separates mechanisms from negative stiffness and
ill-conditioning, says when a check is partial or unsupported, and lists the
joints and DOFs that move. A connected component with no restraint or grounded
spring is checked with a verified rigid-body translation and reported as a
partial mechanism without waiting for the sparse eigensolver. The CSR pointer's
last entry defines the stored entries even when OpenSees reports a larger
allocated `nnz`, and 32-bit or 64-bit integer buffers are accepted. The child
reports phases, the Analyze menu can cancel it, and the GUI applies a soft 300 s
limit. It is an initial-state check, not a buckling factor or a guarantee for a
nonlinear history. Reproducible families are available with `python tools/stability_bench.py --family frame --size 12`
(or `--family truss --mechanism`).

## Verification

The [Verification Manual](docs/verification-manual.md) compares OpenSees Studio
with closed-form and published solutions: beams (Euler-Bernoulli and Timoshenko,
2D and 3D), trusses, support settlement, P-Δ, modal frequencies, a step-load time
history, a response spectrum, a simply supported plate of shells and the plastic
moment of a fibre section, the same plate with `ShellDKGQ` and `ShellDKGT`
shells and the Scordelis-Lo roof, a column built storey by storey, creep and
shrinkage of a column over 10 000 days, a cantilever bent into a quarter circle
by a tip moment (large rotations), an ACI 318-19 beam and column, and the AISC 360-16 design examples E.1A, F.1, G.1A
and H.1A plus an end-to-end beam check, each with its relative error and
tolerance. The file is
generated from real runs by `tools/verification_manual.py` (`--write` regenerates
it), and CI fails when a case leaves its tolerance or the file is stale.

**Results changes are never silent.** Every case of every project in
`examples/` is pinned by a fingerprint (largest displacement per DOF, reaction
sums, largest element force, norms, periods, step counts) in
`tests/data/results_snapshots.json`; CI fails when one moves by more than 1e-5
relative. A fix that changes numbers on purpose is pinned with
`python tools/results_snapshot.py --write --reason "..."`, which records the
before and after in [docs/results-changes.md](docs/results-changes.md), and the
release notes announce it under **Results changed**.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the phase-by-phase plan.
Phases 0–7 (modeling, analysis, post-processing) are largely done.
Phase 8 (earthquake-engineering primitives — isolators, ground-motion
library, IDA, fiber-section editor polish) is the active edge.

## We're looking for collaborators

This project is most useful to researchers and engineers who already
work with OpenSees and want a faster path from "idea" to "model" —
**and who would rather build that path together than alone.**

If any of the following sounds like you, please open an issue or
say hi:

- 🌉 **Structural / earthquake engineers** comfortable with OpenSees Tcl
  or OpenSeesPy who can spot when a feature is "almost right but not
  quite" — that calibration feedback is gold.
- 🧪 **Researchers** running pushover, IDA, or response-spectrum studies
  who want to validate the GUI against their hand-built scripts.
- 🐍 **Python / Qt developers** interested in scientific desktop apps,
  PyVista / VTK rendering, or Pydantic-driven schema design.
- 📚 **Students** who want to learn structural FEM and modern GUI
  architecture at the same time — example walkthroughs and tests are
  designed to read as documentation.
- 🎨 **UX / icon designers** willing to help shape the dialog set,
  toolbar icons, and overall visual language.

Open issues, bug reports, and reproducible test cases are just as
valuable as code. Pull requests target `main`; `develop` is the
maintainer's experimental branch, not the integration target. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev setup and the architectural
rules enforced in review.

## License

OpenSees Studio is released under the **GNU Affero General Public
License v3.0** ([`LICENSE`](LICENSE)).

Plain-language summary (not legal advice — read the license itself):

- ✅ Use it for **research, education, and personal projects** with no
  obligation other than keeping the copyright notice intact.
- ✅ Modify and fork it freely.
- ⚠️ If you **distribute** it, modified or not, you must release your
  full source under AGPL-3.0.
- ⚠️ If you **run it as a network service** (e.g. host a modified
  version as a SaaS), you must release your modifications under
  AGPL-3.0.

In other words: anyone is free to learn from and build on this code,
but commercial forks and proprietary derivatives must contribute their
changes back to the community. If your use case needs a different
arrangement (e.g. a closed-source commercial license), please open an
issue to discuss.

Copyright © 2026 Ozan and contributors.
