# SAP2000 text (`.s2k`) import: status and limitations

> **Work in progress.** The importer is usable on real models and is being
> extended wave by wave, but it is not a complete SAP2000 reader. A table or
> object it cannot carry is named in the import report instead of disappearing
> silently; this page lists what is read today, what is not, and the known
> approximations.

SAP2000 is a trademark of Computers and Structures, Inc. (CSI). OpenSees Studio
is not affiliated with CSI. The reader was written from the public shape of the
text format alone, without CSI software, and has not been checked by CSI or
inside SAP2000 itself.

## What is imported

- Units (`PROGRAM CONTROL`), the active DOFs (a frame model in the X-Z plane can
  become 2D), grid lines, joints and restraints, added joint masses and support
  springs, and the mass-source semantics that are reported.
- Frame elements as `elasticBeamColumn` elements: rectangular, I, pipe,
  box/tube and general elastic sections, their materials, local-axis angles,
  end releases and partial-fixity springs, per-frame property modifiers, and
  nonprismatic sections.
- Four-node shell elements as `ShellMITC4` on an elastic plate section.
- Rigid diaphragms on SAP2000's floating centre-of-mass master joint.
- Plain load patterns with their self-weight multiplier, joint forces,
  distributed frame loads (uniform, trapezoidal or over part of the member),
  point frame loads, temperature changes on frames, ground displacements on
  restrained DOFs and frame added mass.
- Linear static cases (including the static case a case names as its initial
  condition), eigen modal cases, CQC/SRSS response-spectrum cases with their
  tabulated spectra, and load combinations.

### Nonprismatic sections

A `FRAME SECTION PROPERTIES 05 - NONPRISMATIC` definition is read in the file's
segment order and becomes a `NonprismaticSection` template. Each member is
subdivided into ordinary elastic beam-columns — 12 pieces by default, editable
from 12 to 200 — with the section interpolated at each piece. This is a
numerical approximation of SAP2000's taper, not the same internal integration;
the import dialog asks for the piece count. The template and its pieces are
documented in the application help and in the changelog.

## Known limitations

The import report on each file is authoritative: it names every table that was
not read and every approximation that was made. The main gaps are:

### Analysis cases

- Nonlinear static (`NonStatic`) cases, staged construction, buckling
  (`LinBuckling`), modal history and direct-integration history (`LinModHist`),
  steady-state and moving-load cases are not imported.
- Only CQC and SRSS modal combinations are imported. `ABS` and "10 Percent"
  combinations are reported; a second direction, a non-zero angle, accidental
  eccentricity or a second scale factor on a spectrum case is reported rather
  than guessed.
- A modal or spectrum case whose initial condition is another case is run from
  zero when that initial condition is not a supported static preload;
  the report says so.
- Load-pattern mass in the SAP2000 mass source is not modelled; element and
  added masses are. The report distinguishes the two when they differ.

### Elements and constraints

- Links (`CONNECTIVITY - LINK` and its property tables), tendons, cables,
  solids, plane/2D quadrilateral areas and nonlinear link types are not imported.
- Only four-node `ShellMITC4` shells are imported; other area elements are
  reported.
- Rigid links, equalDOF and body constraints are not imported. Rigid
  diaphragms are supported only in a 3D, single-level floor; a 2D or
  multi-level diaphragm is reported.
- Storeys, groups and section cuts are not imported.

### Frames and sections

- Frame end offsets, length offsets, insertion points, rigid zones,
  P-Delta/Corotational transformation assignments and axial/shear end releases
  are not imported; frames import as linear members.
- Curved frames are imported straight.
- Local-axis angles other than a multiple of 90° are approximated by the
  nearest orientation when the section is not symmetric; the report names the
  affected members.
- Section geometry: rectangles, I-shapes, pipes and rectangular tubes keep a
  drawing shape; other shapes keep their properties but not their exact
  drawing. A `Circle` section keeps its properties and is reported.
- A 3D section with `J = 0` gets a small torsional constant; a 2D section may
  carry zero in the out-of-plane inertia and torsion. Both are reported.
- A zero `AMod`, `JMod`, `I22Mod` or `I33Mod` frame modifier is refused rather
  than turned into a singular member; a zero shear-area modifier is accepted
  and disables shear deformation. On a nonprismatic frame the segment sections'
  own shear areas govern, as SAP2000's own example results do.
- The advanced nonprismatic definition is read as equal subdivisions of the
  member; SAP2000's own segment-by-segment integration is not reproduced.

### Loads

- `FRAME LOADS - GRAVITY` and element moment loads are not imported; the report
  names them.
- Some point-load local/projected directions are reported. Distributed loads
  support the global, gravity, projected and local directions the importer
  knows.
- A temperature change that varies along the member is imported with its mean
  value; the variation itself is reported. Gradients are per unit length, as
  SAP2000 writes them.
- A ground displacement on a free or spring-supported DOF is reported: this
  program's support spring has a fixed ground end.
- Self-weight uses the section's unit weight and the frame weight modifier.

### Results and export

- Only model tables are read; SAP2000 result tables inside the file are ignored.
- The S2K export is a best-effort writer for the model it knows: elastic frames
  and shells, sections, releases, partial fixity, frame property modifiers,
  diaphragms, load patterns with joint/frame loads, static/modal/spectrum cases
  and combinations. It does not write a SAP2000 `NONPRISMATIC` table (the
  subdivided elastic pieces are written instead), end offsets, insertion points,
  rigid links/equalDOFs, the mass source, shell/floor loads, imposed
  displacements, temperature loads, nonlinear/history/buckling cases or groups.
  The export report lists what it left out.

### Validation

The importer is exercised against SAP2000's 68-file `ex1000` example set; all 68
files import. The local comparison against the result tables stored in those
files is a development aid, not a certification: it currently has complete
comparisons for 35 static, 13 modal and 3 response-spectrum cases, with some
known stale-result and mass-matrix exceptions tracked in the comparison report.
Files from other SAP2000 versions and models that use the limitations above can
still fail to reproduce SAP2000.

## What happens to what is not imported

Every table not in the reader's list is counted and named in the import log
(for example `table not read: CONNECTIVITY - LINK`). Individual rows the reader
cannot use — an oblique local axis, a curved frame, an unsupported load
direction, a zero torsional constant — are counted under a descriptive key.
The import never silently changes a model: if a value is approximated, the log
says how.

## Roadmap

The next waves target links and tendons, nonlinear/staged/buckling/history
cases, shear deformation on members with releases or non-uniform loads,
axial/shear releases, element moment loads, the remaining section geometry, and
the modal mass-matrix differences. The detailed comparison and plan live with
the development notes; this page is updated when a wave lands.
