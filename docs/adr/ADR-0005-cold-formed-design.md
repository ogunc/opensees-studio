# ADR-0005: Cold-formed steel design — AISI S100 by the Direct Strength Method

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-11-22 |

---

## 1. Context

Define → Section Library → Add Cold-Formed (AISI) already builds lipped and
plain channels, zees, hats and angles (`core/sections/cold_formed.py`) with
their gross properties by the linear method. The steel frame check
(`services/steel_design.py`, ADR-0004) only covers AISC v16 hot-rolled shapes:
a member made of a cold-formed section is not checked at all.

Cold-formed members fail by local and distortional buckling of their thin
flats long before they yield, so the AISC 360 equations do not apply. AISI
S100-16 (reaffirmed 2020) is the specification. It gives two routes to member
strength: the Effective Width Method (Appendix 1 and the element rules) and the
Direct Strength Method (DSM, Chapters E and F), which needs the elastic local
and distortional buckling loads of the whole section from a rational analysis
(Appendix 2).

## 2. Decision

1. **AISI S100-16 is a second specification inside the steel frame check, not
   a separate check.** A member whose section carries a `ColdFormedShape` is
   checked by AISI; every other steel member keeps AISC 360. Demands, load
   sets, physical members, unbraced lengths, `Cb`, `MemberCheck`,
   `LimitStateCheck`, the ratio dock, the 3D ratio view and the calculation
   memory are reused as they are.

2. **DSM first; the Effective Width Method later.** DSM treats every profile
   with the same equations, includes distortional buckling, and reports a
   result that can be traced from the buckling loads. Effective widths are a
   later alternative for comparison.

3. **The elastic buckling loads come from our own finite strip solver**
   (`core/design/fsm.py`): the semi-analytical finite strip method with simply
   supported ends, solved over a range of half-wavelengths (the signature
   curve). It is written from the published theory (Cheung 1976; Schafer and
   Ádány 2006). No code is taken from CUFSM, so the solver has no licence
   obligations and stays pure NumPy in `core`.

4. **Hand formulas check the solver** (`core/design/aisi_buckling.py`): the
   plate buckling stress and the element model of local buckling. They are a
   cross-check and a fallback, not the method.

5. **Material comes from the section.** A cold-formed section is linked to a
   material (A653 SS Gr. 33 or Gr. 50 sheet from the default library), which
   gives `Fy`, `Fu` and `E`. The AISC grade table (`steel_grades.py`) is not
   extended with sheet steels, because its `Ry` values are AISC 341's and the
   AISI seismic standard (S400) is out of scope.

6. **Same rules as ADR-0004.** `core` stays headless; every limit state reports
   its equation, demand, capacity and assumptions; LRFD and ASD; each equation
   enters with a test against a published example or a closed-form solution.

## 3. Phases

| Phase | Content | Gate |
|---|---|---|
| 1 | Missing section properties (principal axes, `j`, `ro`); finite strip solver and signature curve; hand-formula cross-check; this ADR | Plate buckling, global flexural-torsional and lateral-torsional buckling reproduced by the solver |
| 2 | `core/design/aisi_s100.py`: D tension, E2–E4 compression, F2–F4 flexure, G2 shear, LRFD and ASD; distortional buckling where the signature curve has no clear minimum; the finite strip model of the double-C box and back-to-back I, and the built-up compression rules of I1.2 (modified slenderness from the fastener spacing) | AISI Design Manual DSM examples within 1 % |
| 3 | Dispatch in `steel_frame_check`, H1.2 and H2 interaction, torsional unbraced length `Lt`/`Kt`, signature-curve panel, calculation memory, help, example model | Unit, GUI and integration suites; example pinned in the results snapshot |
| 4 | Web crippling (G5, H3), purlins by the R-factor method (I6.2), other built-up sections, inelastic reserve, Effective Width Method, local catalogue by gauge, screw connections (J4) | Per item |

**Built-up pairs.** Two equal channels joined toe to toe (box) or back to
back (I) are a section option from phase 1 (`ColdFormedShape.assembly`), so
they can be modelled and analysed now; their design goes with phases 2 and 3,
and the steel frame check covers them as soon as it covers single channels.

## 4. Consequences

- Phase 1 changes no behaviour: it adds properties and the solver, and nothing
  calls them from the GUI yet.
- `ColdFormedProperties` gains `jx` and `jy` (defaulted fields) and the
  derived `x0`, `y0`, `ro`, `I1`, `I2` and `principal_angle`. The `.osmodel`
  format does not change.
- **Distortional buckling without a minimum.** A signature curve shows a
  distinct distortional minimum for many lipped sections in bending, but in
  compression it is often only a shoulder (the 9CS2.5x059 channel is one).
  The solver then reports no distortional load instead of guessing one.
  Phase 2 must close that gap before DSM uses `Pcrd`: by the constrained
  finite strip method (modal identification) or by the closed-form
  distortional expressions of Appendix 2, checked against the specification.
- A signature curve of 90 half-wavelengths takes about a second for a
  20-node section; the check will compute it once per section and cache it.

## 5. Verification

- `tests/unit/test_fsm.py`: plate supported on both edges (k = 4), one edge
  free (k = 6(1 − ν)/π² + (b/a)²), plate in bending (k = 23.9), long lipped C in
  compression (flexural-torsional buckling) and in bending (lateral-torsional
  buckling) against the closed forms from the section's own properties, mesh
  convergence, and the element model as a lower bound of the local load.
- `tests/unit/test_cold_formed.py`: the 9CS2.5x059 properties (A, Ix, Iy, J,
  Cw, xo, j, ro) against the AISI Cold-Formed Steel Design Manual, the
  monosymmetry constant of a sharp channel in closed form, and the principal
  axes of a zee.
