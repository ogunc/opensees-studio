# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), with the caveat
that this is pre-alpha: minor and patch releases may change the `.osmodel`
schema (it carries a `schema_version`, and a file from a newer build is now
refused instead of silently downgraded).

## [Unreleased]

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
