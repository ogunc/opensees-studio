# Gap Analysis — OpenSees Studio vs gidopensees

**Source:** `D:\GitHub\gidopensees` (GPL-3.0, AUTh Lab of R/C and Masonry Structures)
**Scope:** Material / section / element / constraint / load / damping schema coverage.
**Date:** 2026-05-22

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
| Uniaxial / elastic-plastic | Elastic_Perfectly_Plastic_with_Gap | — | ❌ | ✅ | P1 |
| Uniaxial / damper | Viscous | — | ❌ | ✅ | P1 |
| Uniaxial / damper | Viscous_Damper (Maxwell) | — | ❌ | ✅ | P1 |
| Uniaxial / gap | Hyperbolic_Gap | — | ❌ | ✅ | P2 |
| Uniaxial / soil | PySimple1 | — | ❌ | ✅ | P2 |
| Uniaxial / soil | TzSimple1 | — | ❌ | ✅ | P2 |
| Uniaxial / soil | QzSimple1 | — | ❌ | ✅ | P2 |
| Uniaxial / bond-slip | BondSP01 | — | ❌ | ✅ | P2 |

## 2. Steel Uniaxial Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Steel | Steel01 | `Steel01` | ✅ | ✅ | P0 |
| Steel | Steel02 | `Steel02` | ✅ | ✅ | P0 |
| Steel | Hysteretic | `HystereticMaterial` | ✅ | ✅ | P0 |
| Steel | Reinforcing_steel (DoDD-Restrepo) | — | ❌ | ✅ | P1 |
| Steel | Ramberg-Osgood_steel | — | ❌ | ✅ | P2 |

## 3. Concrete Uniaxial Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Concrete | Concrete01_(Zero_tensile_strength) | `Concrete01` | ✅ | ✅ | P0 |
| Concrete | Concrete02_(Linear_tension_softening) | `Concrete02` | ✅ | ✅ | P0 |
| Concrete | Concrete04_(Popovics) | — | ❌ | ✅ | P1 |
| Concrete | Concrete06 | — | ❌ | ✅ | P2 |
| Concrete | ConcreteCM (Chang-Mander) | — | ❌ | ✅ | P1 |

## 4. Combined Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Combination | Series | — | ❌ | ✅ | P1 |
| Combination | Parallel | — | ❌ | ✅ | P1 |
| Combination | Section_Aggregator (in .mat) | `SectionAggregator` | ✅ | ✅ | P0 |

## 5. nD (Multi-dimensional) Materials

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| nD | Elastic_Isotropic | `ElasticIsotropic` | ✅ | ✅ | P0 |
| nD | Elastic_Orthotropic | — | ❌ | ✅ | P2 |
| nD | J2Plasticity | — | ❌ | ✅ | P2 |
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
| Section | Fiber_Custom | `FiberSection` (manual fibres) | 🟡 | ✅ | P0 |
| Section | FiberInt (interaction P-M) | — | ❌ | ✅ | P1 |
| Section | Plate_Fiber | — | ❌ | ✅ | P2 |
| Section | Elastic_Membrane_Plate | — | ❌ | ✅ | P2 |
| Section | LayeredShell | — | ❌ | ✅ | P2 |
| Section | Section_Aggregator | `SectionAggregator` | ✅ | ✅ | P0 |

## 7. Beam-Column Elements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Frame | Elastic_Beam-Column | `ElasticBeamColumn` | ✅ | ✅ | P0 |
| Frame | Elastic_Timoshenko_Beam-Column | — | ❌ | ✅ | P1 |
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
| Surface | Shell (ShellMITC4 / MITC4) | — | ❌ | ✅ | P1 |
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
| Special | BeamContact (master/slave) | — | ❌ | ✅ | P2 |

## 12. Restraints (Boundary Conditions)

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Restraint | Point_Restraints | Node.restraint (6-tuple) | ✅ | ✅ | P0 |
| Restraint | Line_Restraints (auto-apply to nodes on line) | — | ❌ | ✅ | P2 |
| Restraint | Surface_Restraints (auto-apply to nodes on surface) | — | ❌ | ✅ | P2 |

## 13. Nodal Loads & Displacements

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Load | Point_Forces | `NodalLoad` | ✅ | ✅ | P0 |
| Load | Line_Forces (nodal, along a line) | — | ❌ | ✅ | P2 |
| Load | Surface_Forces (nodal, on a surface) | — | ❌ | ✅ | P2 |
| Load | Line_Uniform_Forces | `UniformElementLoad` | ✅ | ✅ | P0 |
| Load | Point_Displacements (imposed) | — | ❌ | ✅ | P1 |
| Load | Line_Displacements (imposed, on nodes along line) | — | ❌ | ✅ | P2 |
| Load | Surface_Displacements (imposed, on nodes on surface) | — | ❌ | ✅ | P2 |

## 14. Ground Motions

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Ground motion | Point_Ground_Motion_from_Record | `PathTimeSeries` + `UniformExcitationPattern` | ✅ | ✅ | P0 |
| Ground motion | Point_Sine_Ground_Motion | — (no `TrigTimeSeries`) | ❌ | ✅ | P1 |
| Ground motion | Records (BOOK 8 — ground motion file library) | `PathTimeSeries.file_path` (single file, no library) | 🟡 | ✅ | P1 |

## 15. Constraints

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Constraint | Point_Equal_constraint (master + slave) | `EqualDOFConstraint` | ✅ | ✅ | P0 |
| Constraint | Line_Equal_constraint (slave nodes on line) | — | ❌ | ✅ | P1 |
| Constraint | Point_Rigid_link (Bar / Beam) | — | ❌ | ✅ | P1 |
| Constraint | Line_Rigid_link (slave nodes on line) | — | ❌ | ✅ | P1 |
| Constraint | Point_Rigid_diaphragm (master + slave, XY/YZ/ZX plane) | — | ❌ | ✅ | P1 |
| Constraint | Line_Rigid_diaphragm (slave nodes on line) | — | ❌ | ✅ | P1 |

## 16. Mass

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Mass | Point_Mass | node mass (Properties dock + SetMassCommand) | ✅ | ✅ | P0 |
| Mass | Line_Mass (auto-lump to nodes) | — | ❌ | ✅ | P1 |
| Mass | Surface_Mass | — | ❌ | ✅ | P2 |
| Mass | Volume_Mass | — | ❌ | ✅ | P2 |

## 17. Rayleigh Damping

| Category | Object (gidopensees) | OpenSees Studio name | In Studio? | In gidopensees? | Priority |
|---|---|---|---|---|---|
| Damping | Global αM + βK (TransientCase fields) | `TransientCase.rayleigh_alpha_m/beta_k` | ✅ | 🟡 | P0 |
| Damping | Mode-1 stiffness-proportional βK auto-compute | `TransientCase.rayleigh_mode1_damping` | ✅ | ❌ | P0 |
| Damping | Per-region Rayleigh (Line/Surface/Volume/Point) | — | ❌ | ✅ | P1 |

---

## Summary

| Status | Count |
|---|---|
| ✅ Fully in OpenSees Studio | 34 |
| 🟡 Partial | 3 |
| ❌ P1 targets (Phase 8 additions) | 23 |
| ❌ P2 deferred | 21 |

**Top P1 targets** (highest EQ-engineering impact, not in Studio yet):

1. `ElasticPP_with_Gap` — bearing pad / isolation gap nonlinearity
2. `Viscous` / `Viscous_Damper` — supplemental damping devices
3. `ReinforcingSteel` — DoDD-Restrepo model for well-detailed rebar
4. `Concrete04` (Popovics) / `ConcreteCM` (Chang-Mander) — better confined concrete
5. `Series` / `Parallel` — material combination building blocks for isolation systems
6. `RigidDiaphragm` — floor slab constraint, essential for 3D building models
7. `RigidLink` — column/beam offset rigid connections
8. `Shell` (MITC4 / ShellDKGQ) — wall / slab elements
9. `FiberInt` — P-M interaction section for axial-flexure coupling
10. `PointDisplacement` imposed load — displacement-based loading at nodes
11. Per-region Rayleigh damping — finer damping control for mixed models
12. Sine ground motion / ground motion record library — GM workflow completion
