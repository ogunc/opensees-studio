# Shell contour view — plan and what the solver actually reports

**Date:** 2026-10-09
**Requested for:** 0.0.7
**Status:** implemented for 0.0.7 (`f58b331`, `1b695db`, `980f45f`, `c529059`,
`1bcbd63`); this note is kept as the record of what the solver reports.
**Scope:** a colour-mapped (contour) view of (a) the deformations of shell
elements and (b) the internal forces and moments acting in their principal
directions.

---

## 1. What the solver gives us, measured

Probe: one `ShellMITC4`, 1 m × 1 m, `ElasticMembranePlateSection` with
E = 30 GPa, h = 0.2 m, quarter-symmetry restraints and a *uniform* uniaxial
tension of 2000 N/m — a state whose answer is known by hand, so a wrong slot in
the response vector cannot hide.

```
algorithm        analyze   eleResponse(tag, "stresses")[0]   applied N11
Linear                 0                                  0          2000
Newton                 0                               2000          2000
ModifiedNewton         0                               2000          2000
KrylovNewton           0                               2000          2000
```

Three facts that decide the implementation:

1. **`eleResponse(tag, "stresses")` returns the section stress resultants**, not
   stresses: with N11 = 2000 N/m applied, the reported value is `2000` (force per
   unit length), and with ν = 0.2 the strain vector's second slot is `-6.667e-8`
   = `-ν ε11` while the resultant stays zero (free Poisson contraction, so
   `N22 = 0`).
2. **The vector is 4 gauss points × 8 components**, in this order:

   | slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   |---|---|---|---|---|---|---|---|---|
   | quantity | N11 | N22 | N12 | M11 | M22 | M12 | V13 | V23 |
   | unit | N/m | N/m | N/m | N·m/m | N·m/m | N·m/m | N/m | N/m |

   (`stresses` and `strains` share the layout: slots 0–2 membrane, 3–5 bending,
   6–7 transverse shear. In the probe only slot 0 of each 8 was non-zero, with a
   stride of exactly 8.)
3. **Read the response *after* ``ops.reactions()``.** Asking
   ``eleResponse(tag, "stresses")`` straight after ``ops.analyze(1)`` on a
   `Linear` case returns zeros; after ``ops.reactions()`` — a state query — the
   same call returns the real resultants, and Newton-shaped algorithms return
   them either way.

   ```
   algorithm        N11 straight after analyze   after reactions()
   Linear                                   0                 2000
   Newton                                2000                 2000
   ModifiedNewton                        2000                 2000
   ```

   The runner calls ``ops.reactions()`` before reading any element response, so
   a `Linear` case is *not* a special case in the application; an earlier draft
   of this note (and a view warning built on it) was wrong, and
   ``tests/integration/test_shell_contour_reference.py`` pins the correction.

OpenSees reports the resultants in the **element's local frame**. The principal
quantities are frame-independent, so the principal view needs no transformation;
the component view (N11 vs N22 …) must rotate them into the element frame, which
is what the element itself already does.

## 2. Plan

**Phase 1 — carry the data.** `StaticResults.element_stresses: dict[int, ndarray]`
(shape `(n_steps, 8)`, the mean over the element's gauss points) filled by
`_run_static` from `eleResponse(el.id, "stresses")`, skipped for elements that do
not answer; persisted by `services/result_store.py` (a new HDF5 group and a
manifest flag, so an old result file still loads) and read back by `load_results`.
Pushover records it at the final step the same way.

**Phase 2 — the maths.** `core/shell_results.py`:
`principal(a, b, ab) -> (major, minor, angle_deg)` by Mohr's circle
(`σ1,2 = (a+b)/2 ± √(((a-b)/2)² + ab²)`, `θp = ½ atan2(2ab, a-b)`), plus named
fields for the contour picker: displacement components and magnitude, N11/N22/N12,
M11/M22/M12, V13/V23, and N1/N2/M1/M2 with their directions. Verified against
hand cases: uniaxial (θ = 0), pure shear (θ = ±45°, principals ±|N12|),
equibiaxial (any θ, principals equal), and the invariants
`σ1 + σ2 = a + b`, `σ1 σ2 = ab - ab²`.

**Phase 3 — the picture.** `views/canvas3d/shell_contour_renderer.py`: node-averaged
scalar on the shell faces with a colour bar, optional warp by the displacement
field (the deformation view), and principal-direction glyphs at element centres
(arrow length ∝ |σ1 - σ2|, orientation θp) for the principal view. Colour limits
from the data; a zero field must not divide by zero.

**Phase 4 — the UI.** Display → *Show Shell Contours…*: a dock with the field
picker (grouped: deformations, membrane, bending, shear, principal), the step
spinner for multi-step results, a colour-map choice and a "reset view" button;
the canvas keeps the model geometry and the overlay is torn down with the dock.
Help topic `display.shell_contours` (+ `ACTION_TOPICS` entry), the way the force
diagram and the deformed shape already work.

**Phase 5 — the evidence.** Unit: the principal maths and the field extraction.
Integration: a plate strip in pure bending (`M = qL²/8`), the uniform-tension
probe above (`N11 = P/b` exactly), and a pure shear case (`N12 = V/b`) — plus the
existing `tests/integration/test_shell_plate.py` solution as a cross-check. GUI:
the dock lists the fields, renders an actor and a scalar bar, and reports the
"no shells in this model" message instead of an empty map.

## 3. Decisions taken while implementing

- **Node-averaged values**, with the element's own value used for the direction
  glyphs and for the per-element reading. A shared node reads the mean of the
  elements that meet there, which is what makes the picture continuous; an
  element with no resultants contributes nothing rather than a zero.
- **A new dock**, not a colour-by box on the Deformed Shape one: this view
  warps, chooses a step and draws directions, and the Deformed Shape control
  stays the small thing it is.
- **A signed field is centred on zero** in the colour map, and a constant field
  gets a band instead of a degenerate one; a hydrostatic state draws no
  direction.
