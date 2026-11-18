# Tutorial 3 — Bringing a PORTICO model into OpenSees Studio

**English** · [Español](03-importing-portico.es.md)

[PORTICO](https://github.com/jpreyes/portico-core) is a structural analysis
program that runs in the browser and saves its models as `.s3d` files. This
tutorial opens one here, in the units you choose, so you can analyse it with
OpenSees: fibre sections, nonlinear materials, time histories and the rest.

**You need:** an `.s3d` file. The `examples/` folder of PORTICO has two dozen
(its tutorials and its verification cases).

## 1. Import

**File → Import → PORTICO Model (.s3d)…**. The import **replaces** the open
project, so unsaved changes are asked about first, like File → Open.

![The PORTICO import dialog](img/portico-import.png)

Press **Browse…** and pick the file. The dialog reads it at once:

- **File units**: the system the file's numbers are in, from its `units`
  label (`kN-m`, `kip-in`, `lb-in`…). PORTICO never converts, so the label is
  the only thing that says what a "1" in the file is. Change it if the label is
  wrong.
- **Project units**: the system the new project gets. **Every value is scaled
  to it by its dimension**: lengths, forces, moments, moduli, areas, inertias,
  masses, densities, springs and loads. A `kN-m` file opens in SI (m, N) by
  default, so its forces are multiplied by 1000 and its densities (t/m³) become
  kg/m³. The **Scale** line shows the length and force factors.
- The summary says what the file has and what the project will get. What
  cannot come across is **counted** in it ("Not imported: 1 spectrum load
  case"); the notes under it say what changed on the way.

Press **Import**. The log repeats the summary and the notes. The project has no
file yet: **File → Save As…** keeps it.

## 2. What changed on the way, and why

**Local axes.** PORTICO gives a beam its local **y** up, OpenSees (here) its local
**z**. In 3D almost every member is "turned": its `Iz` and `Iy`, its shear areas
and its bending releases swap, and the section's name ends in `(axes 2-3)` so you
can see which ones. Distributed loads are re-projected onto the OpenSees axes, so
a gravity load stays a gravity load. A 2D model keeps its axes.

**Timoshenko.** PORTICO's members deform in shear when the section has shear
areas, and so do these (an `ElasticTimoshenkoBeam`). OpenSees 3.8 takes no
releases and no trapezoidal load on that element, so such a member loses its
shear deformation, and the summary counts it.

**Areas.** Quadrilaterals become `ShellMITC4`. A PORTICO *membrane* gains bending
stiffness and a *plate* membrane stiffness, which the notes say. Triangles have no
3-node shell here and are counted.

**Floors and links.** A diaphragm becomes a rigid diaphragm on PORTICO's master
node; its mass is spread over the floor's nodes. A rigid link becomes a rigid
link with its lever arm; any other link an equalDOF.

**Self weight.** It is the density times g in the project's units. PORTICO always
multiplies by 9.80665, which is only right in `kN-m`; for a `kip-in` file the
notes warn that PORTICO's own self weight is different.

## 3. Run and compare

**Analyze → Run All Cases**. Each PORTICO static load case became a load pattern
plus a linear static case of the same name, its combinations became
combinations, and a model loaded only by prescribed displacements (a patch test)
got a case of its own.

PORTICO publishes OpenSeesPy runs of five of its verification models. Imported
here they give the same displacements, reactions and eigenvalues to 1e-10: support
settlement (1-005), link offset (1-010), modal cantilever (1-014), static portal
(1-018) and the Bathe–Wilson frame (1-021). `tests/integration/test_s3d_import_run.py`
repeats that comparison whenever `PORTICO_CORE_DIR` points to a copy of PORTICO.

## 4. What does not come across (yet)

Temperature loads, response spectrum cases (the spectrum is not in the file),
triangular areas, unilateral, coupled and soil springs, a diaphragm's rotational
mass and accidental eccentricity, and distributed loads on cables and struts.
(Cables and compression-only struts themselves do come across, as trusses that go
slack on the other side; their static cases run with Newton.)
Each is counted in the summary and the log, never dropped silently. The full list
is in the help page (F1 in the dialog).
