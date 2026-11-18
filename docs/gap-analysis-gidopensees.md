# Gap Analysis — OpenSees Studio vs gidopensees

**Source:** `D:\GitHub\gidopensees` (GPL-3.0, AUTh Lab of R/C and Masonry Structures)
**Scope:** Material / section / element / constraint / load / damping schema coverage.
**Date:** 2026-05-22
**Reviewed:** 2026-10-23 against `src/opensees_studio/core/` and
`services/opensees_runner.py` at `main` after v0.0.22 (commit `49bcdc8`); the
2026-10-04 and 2026-09-18 passes are kept below.

## Review notes (2026-10-23)

Every ❌ and 🟡 row was checked again with the same rule as on 2026-10-04: a
real model class in `core/` that the runner emits and a test runs, never a
stub in `core/catalog/`. Since the last pass the 0.0.13 command coverage, the
shell work, the PORTICO phases and the section tools landed, and 32 rows move:

- **Now ✅ (21 rows).** Materials `PySimple1`, `TzSimple1`, `QzSimple1`,
  `ReinforcingSteel`, `Concrete06`, `SeriesMaterial`, `ParallelMaterial` and the
  nD `J2Plasticity` (the Material Library's signature materials, each built by
  the live solver in `tests/integration/test_material_library_run.py`, Series
  and Parallel also checked for their law); sections `PlateFiberSection`,
  `ElasticMembranePlateSection` and `LayeredShellSection`; custom fibre
  sections from Define → Section Designer; the Timoshenko beam (an elastic
  section with shear areas runs as `ElasticTimoshenkoBeam`); `ShellMITC4Element`;
  `TripleFrictionPendulumElement` (ISO-3); `RigidLink` and `RigidDiaphragm`
  (point and line diaphragms: a diaphragm holds any set of constrained nodes);
  static imposed displacements (`ImposedDisplacement`, `sp` in a Plain
  pattern); line and surface mass (frame and shell `rho`, `MassSource`).
- **Now 🟡 (11 rows, all from ❌).**
  `ElasticPPGap`, `Viscous` and `ViscousDamper` are in the Material Library and
  OpenSees builds them, but the 2026-10-04 measurements stand: the gap material
  does not follow its field names, and with the elements Studio builds the
  strain rate never reaches `Viscous`. They stay partial until a test pins
  their law. The line and surface variants of restraints, nodal forces, imposed
  displacements, equal-DOF constraints and rigid links are done by assigning to
  the selected joints (a window, a group or Select → By …): the same model, but not
  tied to a geometric line or surface that a remesh would follow.
- **Still ❌.** P1: `ShellDKGQ`. P2: `Hyperbolic_Gap`, `BondSP01`, `Ramberg-Osgood_steel`, the nD
  `Elastic_Orthotropic`, `Damage2p`, the three multi-yield soil materials and
  `Contact`, the flexure-shear interaction beam, `Tri31`, `QuadUP`, the brick
  and `BeamContact`, and volume mass (there are no solid elements).
- **Still 🟡.** Region-scoped Rayleigh damping (`region ... -rayleigh`).

**Later the same day:** `ElasticPPGap`, `Viscous` and `ViscousDamper` moved
🟡 → ✅. The 2026-10-04 findings had two causes, neither in the materials: the
gap was measured with `Fy` and `gap` of opposite signs, which OpenSees accepts
with a warning and then answers neither law (Studio now refuses it), and the
dashpots were driven in static or ramped analyses, which have no strain rate. A
transient single-degree-of-freedom oscillator built the application's way
(`ZeroLength`, spring and dashpot in `Parallel`) gives the closed-form overshoot
of a linearly damped system to 0.1 % with both dampers;
`tests/integration/test_gap_and_damper_materials.py` pins the three laws.
`ConcreteCM` moved ❌ → ✅ as well (Material Library and the wizard's
**Concrete law** option), and `FiberInt` to 🟡 with `MVLEM` walls in its place.

Studio-only work since 2026-10-04 that has no gidopensees row (not counted):
PORTICO `.s3d` import, the AISC 360-16 steel check and storey drift check,
influence lines and moving loads, temperature loads on frames, the Concrete
Section Wizard (Mander-confined core), the Section Designer, the generated
Verification Manual, and PyNite as a second engine for linear static and
P-Delta cases.

## Review notes (2026-10-04)

Re-verified every ❌ and 🟡 row against the code, this time by searching for a
real model class or a command the runner emits and **excluding all of
`core/catalog/`** — a generated stub is not an implementation. Result: no ❌
row moved. The material and element backlog is unchanged, and the top P1
targets below are still the top P1 targets.

One row does move, and it is the largest change since the last pass:

- **Ground motion Records (BOOK 8)**: 🟡 → ✅. GM-1/2/3 shipped a real record
  layer, not the "single file, no library" the row described:
  `core/ground_motion.py` (record model plus AT2, two-column and
  single-column readers), `core/ground_motion_metadata.py` (PGA, PGV, PGD,
  Arias intensity, D5-95), `Project.ground_motions` — a catalog whose entries
  are referenced by relative path and content hash, so a moved or edited
  record is detected — `core/scaling.py` (PGA, Sa(T1), period range),
  `core/target_spectrum.py` and `core/tbdy_site.py` (TBDY-2018 horizontal and
  vertical design spectra), `services/peer_record.py`, and the Ground Motions
  dialog with its viewmodel.

Studio-only additions since 2026-09-18, none of which is a gidopensees object
and therefore none of which changes a row:

- Material Tester: a Qt dialog over the headless service (Define menu,
  Ctrl+Shift+T), with CSV export.
- Fiber section editor: W-shape template; beam integration rules and
  geometric transformations assignable per element.
- Analysis cases: numberer and system options; result precision setting and
  full-precision CSV export of the result tables.
- Response spectrum: CQC is the default combination for new cases, and modal
  results are made history-independent (see `core.modal`).

The summary counts were recomputed from the tables after the Records row moved.

## Review notes (2026-09-18)

Every ❌ row below was re-checked against the hand-written model classes in
`core/` (materials, sections, geometry, loads, constraints, analysis) and the
commands the runner emits. Three rows changed:

- `Concrete04` shipped end to end (commit `c89037f`): now ✅.
- Imposed displacements shipped as `ImposedSupportMotionPattern` (commit
  `1abea1c`): transient support motion via `pattern MultipleSupport`. A static
  imposed displacement (`sp` inside a Plain pattern), which is what the
  gidopensees condition emits, is still not available, so the row is 🟡.
- Rayleigh damping gained the Kinit and Kcomm slots and a per-element
  `ZeroLengthElement.do_rayleigh` opt-in (commit `2eccb34`). There is still no
  `region` model and the runner never emits `region ... -rayleigh`, so
  region-scoped coefficients remain open and the row is 🟡.

- Elastomeric bearings shipped on `cc/iso-1` (2026-09-24, ISO-1):
  `ElastomericBearingPlasticityElement` and `ElastomericBearingBoucWenElement`
  in 2D and 3D, emitted with the live OpenSeesPy 3.8.0 argument order and a
  mandatory `-orient`, verified against the bilinear closed form. gidopensees
  has no bearing objects and `core/catalog/generated/` has no stub for them,
  so the rows below are Studio-only additions to the special elements table.
  ISO-2 (2026-09-24, `cc/iso-2`) added `flatSliderBearing` and
  `singleFPBearing` with the three friction models, verified against the
  Coulomb closed form; gidopensees has no friction model objects either.
  The triple friction pendulum stays open (ISO-3).

All other ❌ rows are still genuinely missing. Note that
`core/catalog/generated/` holds an autogenerated Pydantic Spec stub for every
gidopensees object (58 material / section / element stubs, 39 condition stubs,
commit `0325bc8`). Those stubs are schema only: they are not part of `Project`,
the runner does not emit them and no dialog edits them. A stub does not make a
row ✅.

Studio-only additions since the original analysis (no gidopensees counterpart
checked, not counted in the summary): `HystereticSM`, `ResponseSpectrum` with
SRSS / CQC combination, `elasticBeamColumn -cMass`, the headless Material
Tester service.

The summary counts were recomputed from the tables; the original figures did
not match the rows.

### Catalog bridge status (2026-10-04)

`CatalogMaterial` + `services/catalog_emitters.py` connect the generated
catalog to the runtime, one name at a time, with the argument order confirmed
against the solver. Three of the four names probed so far are deliberately
**not** wired, because measuring them contradicted the schema:

- `Viscous` — `uniaxialMaterial Viscous tag C alpha` is accepted, but with the
  elements this application builds the rate never reaches the material: a
  ramped SDOF gave the same response with C = 0, 50 and 100, and an
  imposed-velocity `zeroLength` hard-exited OpenSees.
- `Viscous_Damper` — same element question; needs the same investigation.
- `Elastic_Perfectly_Plastic_with_Gap` — the signature is `tag E Fy gap <eta>`
  (OpenSeesPy docs). Measured through the Material Tester and through an
  imposed-displacement `zeroLength`, the response does not follow the field
  names: with `gap = +0.002` it is zero in both directions, and with
  `gap = -0.002` the compression force peaks at half the yield strain and
  falls to zero at the yield strain.

So the catalog is a **schema source**, not a runtime source: each name needs
its own investigation and a test that runs it. `Elastic` is wired and verified
(`tests/integration/test_catalog_materials.py`); the next candidate should
start by reproducing the material in a script and stating its law.

## How to read this table

| Column | Meaning |
|---|---|
| **Category** | Schema group (material family, element type, etc.) |
| **Object** | Name as it appears in gidopensees BOOK/CONDITION |
| **OpenSees Studio name** | Corresponding class in `core/` (if any) |
| **In Studio?** | ✅ fully supported · 🟡 partial · ❌ missing |
| **In gidopensees?** | ✅ · ❌ |
| **Priority** | P0 = already done · P1 = Phase 8 target · P2 = later |

Priority rationale:
- **P0** — already shipped; included for completeness.
- **P1** — high-value for earthquake-engineering practice; aligns with Phase 8
  roadmap items (isolators, Rayleigh per-region, confined concrete models,
  shell elements, floor diaphragm constraints).
- **P2** — valid but lower-frequency in typical EQ-engineering workflows
  (soil p-y/t-z/q-z springs, 3-D solid elements, multi-yield plasticity,
  contact elements).

---

## 1. Uniaxial Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Uniaxial / linear | Elastic | `ElasticUniaxial` | ✅ | ✅ | P0 |
| Uniaxial / elastic-plastic | Elastic_Perfectly_Plastic | `ElasticPP` | ✅ | ✅ | P0 |
| Uniaxial / elastic-plastic | Elastic_Perfectly_Plastic_with_Gap | `ElasticPPGap` (law pinned in `test_gap_and_damper_materials.py`; Fy and gap of one sign) | ✅ | ✅ | P1 |
| Uniaxial / damper | Viscous | `Viscous` (transient SDOF through `ZeroLength` matches the closed form) | ✅ | ✅ | P1 |
| Uniaxial / damper | Viscous_Damper (Maxwell) | `ViscousDamper` (same oscillator; a soft Maxwell spring damps less) | ✅ | ✅ | P1 |
| Uniaxial / gap | Hyperbolic_Gap | — | ❌ | ✅ | P2 |
| Uniaxial / soil | PySimple1 | `PySimple1` | ✅ | ✅ | P2 |
| Uniaxial / soil | TzSimple1 | `TzSimple1` | ✅ | ✅ | P2 |
| Uniaxial / soil | QzSimple1 | `QzSimple1` | ✅ | ✅ | P2 |
| Uniaxial / bond-slip | BondSP01 | — | ❌ | ✅ | P2 |

## 2. Steel Uniaxial Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Steel | Steel01 | `Steel01` | ✅ | ✅ | P0 |
| Steel | Steel02 | `Steel02` | ✅ | ✅ | P0 |
| Steel | Hysteretic | `HystereticMaterial` | ✅ | ✅ | P0 |
| Steel | Reinforcing_steel (DoDD-Restrepo) | `ReinforcingSteel` (no buckling or fatigue options) | ✅ | ✅ | P1 |
| Steel | Ramberg-Osgood_steel | — | ❌ | ✅ | P2 |

## 3. Concrete Uniaxial Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Concrete | Concrete01_(Zero_tensile_strength) | `Concrete01` | ✅ | ✅ | P0 |
| Concrete | Concrete02_(Linear_tension_softening) | `Concrete02` | ✅ | ✅ | P0 |
| Concrete | Concrete04_(Popovics) | `Concrete04` | ✅ | ✅ | P0 |
| Concrete | Concrete06 | `Concrete06` | ✅ | ✅ | P2 |
| Concrete | ConcreteCM (Chang-Mander) | `ConcreteCM` (Material Library; Concrete Section Wizard → Concrete law) | ✅ | ✅ | P1 |

## 4. Combined Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Combination | Series | `SeriesMaterial` | ✅ | ✅ | P1 |
| Combination | Parallel | `ParallelMaterial` | ✅ | ✅ | P1 |
| Combination | Section_Aggregator (in .mat) | `SectionAggregator` | ✅ | ✅ | P0 |

## 5. nD (Multi-dimensional) Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| nD | Elastic_Isotropic | `ElasticIsotropic` | ✅ | ✅ | P0 |
| nD | Elastic_Orthotropic | — | ❌ | ✅ | P2 |
| nD | J2Plasticity | `J2Plasticity` (nD, for layered shells) | ✅ | ✅ | P2 |
| nD | Damage2p | — | ❌ | ✅ | P2 |
| nD | PressureIndependMultiYield | — | ❌ | ✅ | P2 |
| nD | PressureDependMultiYield | — | ❌ | ✅ | P2 |
| nD | PressureDependMultiYield02 | — | ❌ | ✅ | P2 |
| nD | Contact | — | ❌ | ✅ | P2 |

## 6. Sections

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Section | Elastic_Section | `ElasticSection` | ✅ | ✅ | P0 |
| Section | Fiber | `FiberSection` | ✅ | ✅ | P0 |
| Section | Fiber_Custom | `FiberSection` fibres from Define → Section Designer (any drawn or DXF outline) | ✅ | ✅ | P0 |
| Section | FiberInt (shear-flexure interaction, with `dispBeamColumnInt`) | not in OpenSeesPy 3.8 (`section FiberInt` is unknown to its interpreter); RC walls use `MVLEMElement` (Assign → Frame → RC Wall) | 🟡 | ✅ | P1 |
| Section | Plate_Fiber | `PlateFiberSection` | ✅ | ✅ | P2 |
| Section | Elastic_Membrane_Plate | `ElasticMembranePlateSection` | ✅ | ✅ | P2 |
| Section | LayeredShell | `LayeredShellSection` | ✅ | ✅ | P2 |
| Section | Section_Aggregator | `SectionAggregator` | ✅ | ✅ | P0 |

## 7. Beam-Column Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Frame | Elastic_Beam-Column | `ElasticBeamColumn` | ✅ | ✅ | P0 |
| Frame | Elastic_Timoshenko_Beam-Column | `ElasticBeamColumn` on an `ElasticSection` with shear areas As2 / As3 (emitted as `ElasticTimoshenkoBeam`) | ✅ | ✅ | P1 |
| Frame | Force-Based_Beam-Column | `ForceBeamColumn` | ✅ | ✅ | P0 |
| Frame | Displacement-Based_Beam-Column | `DispBeamColumn` | ✅ | ✅ | P0 |
| Frame | Flexure-Shear_Interaction_DispBeamColumn | — | ❌ | ✅ | P2 |
| Frame | BeamWithHinges | `BeamWithHingesElement` | ✅ | ❌ | P0 |

## 8. Truss Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Truss | Truss | `TrussElement` | ✅ | ✅ | P0 |
| Truss | Corotational_Truss | `CorotTrussElement` | ✅ | ✅ | P0 |

## 9. Surface / Plate Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Surface | Quad | `QuadElement` | ✅ | ✅ | P0 |
| Surface | Shell (ShellMITC4 / MITC4) | `ShellMITC4Element` | ✅ | ✅ | P1 |
| Surface | ShellDKGQ | — | ❌ | ✅ | P1 |
| Surface | Tri31 | — | ❌ | ✅ | P2 |
| Surface | QuadUP (u-p pore pressure) | — | ❌ | ✅ | P2 |

## 10. Solid Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Solid | Standard_Brick_Element | — | ❌ | ✅ | P2 |

## 11. Zero-Length / Special Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Special | Auto_Zero_Length (per-DOF uniaxial) | `ZeroLengthElement` | ✅ | ✅ | P0 |
| Special | Auto_equal_constraint (auto equalDOF) | `EqualDOFConstraint` | ✅ | ✅ | P0 |
| Special | ZeroLengthSection | `ZeroLengthSectionElement` | ✅ | ❌ | P0 |
| Special | Elastomeric bearing, plasticity (`elastomericBearingPlasticity`, 2D and 3D) | `ElastomericBearingPlasticityElement` | ✅ | ❌ | P1 |
| Special | Elastomeric bearing, Bouc-Wen (`elastomericBearingBoucWen`, 2D and 3D) | `ElastomericBearingBoucWenElement` | ✅ | ❌ | P1 |
| Special | Flat slider bearing (`flatSliderBearing`, 2D and 3D, friction models Coulomb, VelDependent, VelNormalFrcDep) | `FlatSliderBearingElement`, `CoulombFriction`, `VelDependentFriction`, `VelNormalFrcDepFriction` | ✅ | ❌ | P1 |
| Special | Single friction pendulum bearing (`singleFPBearing`, 2D and 3D) | `SingleFPBearingElement` | ✅ | ❌ | P1 |
| Special | Triple friction pendulum bearing (ISO-3) | `TripleFrictionPendulumElement` | ✅ | ❌ | P1 |
| Special | BeamContact (master/slave) | — | ❌ | ✅ | P2 |

## 12. Restraints (Boundary Conditions)

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Restraint | Point_Restraints | Node.restraint (6-tuple) | ✅ | ✅ | P0 |
| Restraint | Line_Restraints (auto-apply to nodes on line) | restraints assigned to the selected joints (not tied to a geometric line) | 🟡 | ✅ | P2 |
| Restraint | Surface_Restraints (auto-apply to nodes on surface) | restraints assigned to the selected joints (not tied to a surface) | 🟡 | ✅ | P2 |

## 13. Nodal Loads & Displacements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Load | Point_Forces | `NodalLoad` | ✅ | ✅ | P0 |
| Load | Line_Forces (nodal, along a line) | `NodalLoad` on the selected joints | 🟡 | ✅ | P2 |
| Load | Surface_Forces (nodal, on a surface) | `NodalLoad` on the selected joints; `SurfaceLoad` on shells | 🟡 | ✅ | P2 |
| Load | Line_Uniform_Forces | `UniformElementLoad` | ✅ | ✅ | P0 |
| Load | Point_Displacements (imposed) | `ImposedDisplacement` in a Plain pattern (static `sp`) and `ImposedSupportMotionPattern` (transient) | ✅ | ✅ | P1 |
| Load | Line_Displacements (imposed, on nodes along line) | `ImposedDisplacement` on the selected joints | 🟡 | ✅ | P2 |
| Load | Surface_Displacements (imposed, on nodes on surface) | `ImposedDisplacement` on the selected joints | 🟡 | ✅ | P2 |

## 14. Ground Motions

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Ground motion | Point_Ground_Motion_from_Record | `PathTimeSeries` + `UniformExcitationPattern` | ✅ | ✅ | P0 |
| Ground motion | Point_Sine_Ground_Motion | `TrigTimeSeries` + `UniformExcitationPattern` (GM-3; sine-beat and ramped sine as generated `PathTimeSeries`) | ✅ | ✅ | P1 |
| Ground motion | Records (BOOK 8 — ground motion file library) | `Project.ground_motions` catalog (relative path + content hash), AT2 / two-column / single-column readers, metadata (PGA/PGV/PGD/Arias/D5-95), scaling by PGA / Sa(T1) / period range, TBDY-2018 target spectra | ✅ | ✅ | P1 |

## 15. Constraints

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Constraint | Point_Equal_constraint (master + slave) | `EqualDOFConstraint` | ✅ | ✅ | P0 |
| Constraint | Line_Equal_constraint (slave nodes on line) | `EqualDOFConstraint`, one per selected joint (Assign → Joint → EqualDOF) | 🟡 | ✅ | P1 |
| Constraint | Point_Rigid_link (Bar / Beam) | `RigidLink` (beam / bar) | ✅ | ✅ | P1 |
| Constraint | Line_Rigid_link (slave nodes on line) | `RigidLink`, one per selected joint | 🟡 | ✅ | P1 |
| Constraint | Point_Rigid_diaphragm (master + slave, XY/YZ/ZX plane) | `RigidDiaphragm` (Assign → Joint → Diaphragm) | ✅ | ✅ | P1 |
| Constraint | Line_Rigid_diaphragm (slave nodes on line) | `RigidDiaphragm` with the selected joints as constrained nodes | ✅ | ✅ | P1 |

## 16. Mass

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Mass | Point_Mass | node mass (Properties dock + SetMassCommand) | ✅ | ✅ | P0 |
| Mass | Line_Mass (auto-lump to nodes) | frame `rho` and `MassSource.element_self_mass` (unit weight over g) | ✅ | ✅ | P1 |
| Mass | Surface_Mass | shell section `rho` and `MassSource` (self weight and load patterns over g) | ✅ | ✅ | P2 |
| Mass | Volume_Mass | — | ❌ | ✅ | P2 |

## 17. Rayleigh Damping

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Damping | Global αM + βK (TransientCase fields) | `TransientCase.rayleigh_alpha_m/beta_k/beta_k_init/beta_k_comm` | ✅ | 🟡 | P0 |
| Damping | Mode-1 stiffness-proportional βK auto-compute | `TransientCase.rayleigh_mode1_damping` | ✅ | ❌ | P0 |
| Damping | Per-region Rayleigh (Line/Surface/Volume/Point) | `ZeroLengthElement.do_rayleigh` (per-element opt-in only; no `region -rayleigh`) | 🟡 | ✅ | P1 |

---

## Summary

Recounted from the tables on 2026-10-23.

| Status | Count |
|---|---|
| ✅ Fully in OpenSees Studio | 62 |
| 🟡 Partial (4 at P1, 6 at P2) | 10 |
| ❌ P1 targets | 1 |
| ❌ P2 deferred | 15 |
| Total rows | 88 |

**Top targets** (highest earthquake-engineering impact, not fully in Studio yet):

1. ~~`FiberInt`~~: it is gidopensees' *shear-flexure* interaction section for
   walls (with `dispBeamColumnInt`), not a P-M section, and OpenSeesPy 3.8 does
   not define it. RC walls are modelled with `MVLEM` (Assign → Frame → RC
   Wall); `SFI_MVLEM` with the `FSAM` panel material would add the coupling.
2. ~~`ConcreteCM` (Chang-Mander)~~: in the Material Library, and the Concrete
   Section Wizard builds its cover and Mander-confined core with it (Tsai's
   envelope with Mander's `r` is Mander's curve; pinned to 0.2 %).
3. `ShellDKGQ` — the shell for walls and slabs with drilling DOFs
   (`ShellMITC4` is there).
4. ~~`ElasticPPGap`, `Viscous`, `ViscousDamper`~~: validated (see below).
5. Region-scoped Rayleigh damping (`region ... -rayleigh`) — only the
   per-element `do_rayleigh` opt-in on `ZeroLengthElement` exists.
6. Geometry-tied assignments (line and surface restraints, loads, constraints)
   — today they are assigned to selected joints and must be reassigned after a
   remesh.
7. The per-book multi-record semantics of gidopensees BOOK 8 (a set of records
   in one object); Studio references records one at a time.
