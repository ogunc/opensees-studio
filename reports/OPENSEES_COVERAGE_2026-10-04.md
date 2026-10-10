# OpenSees coverage — what the application uses, and what it does not

**Date:** 2026-10-04
**Reviewed:** `src/opensees_studio/` at `8bb37f7`, against the OpenSeesPy build
installed with the project (`openseespy` 3.8.0.0, 237 public commands).
**Scope:** what the runner can express, measured against the solver's own
command surface. Not a judgement of the model layer or the UI.

---

## 1. Method

Three sources, all machine-readable, so this can be re-run instead of
re-argued:

1. **The solver's command surface**: `dir(openseespy.opensees)` on the
   installed build — 237 public names. This covers *commands*, and commands
   take material, element, section and time-series names as **strings**, which
   `dir` cannot see.
2. **What the application emits**: every `ops.<command>(` / `self._ops.<command>(`
   call in `src/opensees_studio/`, and every string argument passed to
   `ops.element/uniaxialMaterial/nDMaterial/section/timeSeries/pattern/frictionModel`.
3. **The object inventories**: the gidopensees catalog
   (`tools/gidopensees_import/schemas.json`, 58 materials + 39 conditions) and
   the OpenSeesPy documentation tree for the element and material families.

Result: **42 of 237 commands are used**. The rest of this document is what the
other 195 are, which ones are worth having, and which are deliberately out.

## 2. What the application emits today

Commands (42):

```
algorithm analysis analyze beamIntegration constraints eigen eleForce eleLoad
eleResponse element equalDOF fiber fix frictionModel geomTransf groundMotion
imposedMotion integrator layer load loadConst mass model nDMaterial node
nodeDisp nodeEigenvector nodeReaction numberer patch pattern rayleigh
reactions recorder remove section system test timeSeries uniaxialMaterial
wipe wipeAnalysis
```

Objects named by string:

| Family | Emitted |
| --- | --- |
| `uniaxialMaterial` (10) | Concrete01, Concrete02, Concrete04, Elastic, ElasticPP, Hardening, Hysteretic, HystereticSM, Steel01, Steel02 |
| `nDMaterial` (1) | ElasticIsotropic |
| `element` (15) | bbarQuad, beamWithHinges, corotTruss, dispBeamColumn, elasticBeamColumn, enhancedQuad, forceBeamColumn, quad, truss, zeroLength, zeroLengthSection, elastomericBearingPlasticity, elastomericBearingBoucWen, flatSliderBearing, singleFPBearing |
| `section` (3) | Elastic, Fiber, Aggregator |
| `timeSeries` (4) | Constant, Linear, Path, Trig |
| `pattern` (3) | Plain, UniformExcitation, MultipleSupport |
| `frictionModel` (3) | Coulomb, VelDependent, VelNormalFrcDep |
| `recorder` (2) | Node, Element |
| `geomTransf` | per element, from the model's transformation (Linear, PDelta, Corotational) |
| `beamIntegration` | per element, from the model's rule (the Gauss, Lobatto, Radau and hinge families the UI offers) |

Analysis options are exposed per case (system, numberer, constraints, test,
algorithm, integrator) and most of them are selectable from the UI.

## 3. What is missing, by domain

Priorities: **P1** = a structural engineer hits this within a normal project;
**P2** = needed for a class of work, not for most; **P3** = convenience or
specialist.

### 3.1 Constraints — the biggest hole for real buildings (P1)

| Command | What it buys | Evidence |
| --- | --- | --- |
| `rigidDiaphragm` | Floor slabs as rigid diaphragms. Without it, 3D building models either need hand-written `equalDOF` sets or are wrong. | unused; also a ❌ P1 row in the gidopensees gap analysis |
| `rigidLink` | Rigid offsets between a column and a beam node. | unused; ❌ P1 row |
| `equalDOF_Mixed` | Equal-DOF between different DOF counts (solid-to-shell transitions). | unused; ❌ P1 row |
| `region` | Region-scoped Rayleigh damping, i.e. damping a part of the model. | unused; the ❌ P1 "per-region Rayleigh" row |

`equalDOF` is the only multi-point constraint the runner emits, which is why
no example in the repository exceeds 64 elements: a real building needs
diaphragms.

### 3.2 Output and recorders — what the engineer cannot see (P1)

The runner reads results through `nodeDisp`, `nodeReaction`, `eleForce` and
`eleResponse`. Section-level and element-level output is untouched:

| Command | What it buys |
| --- | --- |
| `sectionForce`, `sectionDeformation` | Moment-curvature at a section along an element, rather than end forces only. The moment-curvature workflow currently has to infer it. |
| `basicForce`, `basicDeformation` | Element basic forces — the frame quantities a designer reports, free of rigid-body motion. |
| `recorder` variants: envelope, `pvd`, `CollapseRecorder` | Envelope recorders for peak-response tables; `pvd`/collapse recorders for ParaView and collapse studies. The app implements its own HDF5 transport, so these are a *choice*, but the envelope recorder has no equivalent. |
| `numIter`, `testNorm`, `systemSize`, `numFact` | Convergence diagnostics. The roadmap lists a "dedicated convergence diagnostics dock" as pending, and these are the commands that would feed it. |
| `getEleTags`, `getNodeTags`, `eleNodes`, `eleType`, `eleResponse` (broader) | Model introspection; useful for validation and for the export script. |

### 3.3 Element families (P1-P2)

| Missing | Why it matters |
| --- | --- |
| `twoNodeLink` | The natural element for isolators and dampers. The app has four bearing elements, but no general two-node link. |
| `ShellMITC4`, `ShellDKGQ`, `ShellNLDKGQ`, `SSPquad`, `LayeredShell` | Walls and slabs. The app has `quad`, `bbarQuad` and `enhancedQuad`, which are plane elements, not shells. A shell workflow is listed as out of scope in the roadmap, but a *shell element* is what an RC wall needs. |
| `dispBeamColumnInt`, `nonlinearBeamColumn` | Flexure-shear interaction and the classic distributed-plasticity element. The app has `dispBeamColumn`/`forceBeamColumn`, so this is a refinement rather than a gap. |
| `ElasticTimoshenkoBeam`, `ModElasticBeam2d` | Shear-deformable members and stiffness modifiers (the `I`/`A` factors a designer applies for cracked sections). |
| `zeroLengthND`, `CoupledZeroLength`, `zeroLengthContact*` | Multi-DOF and contact zero-length elements; the app's `zeroLength`/`zeroLengthSection` cover the common cases. |
| `TFP`, `TripleFrictionPendulum`, `multipleShearSpring`, `KikuchiBearing`, `LeadRubberX`, `HDR`, `ElastomericX` | The rest of the isolator family. The app has the four most-used ones (ISO-1/ISO-2); the triple pendulum is the notable omission (roadmap ISO-3). |
| `CatenaryCableElement`, `pipe`, `curvedPipe` | Cable and pipe structures. |
| `quadUP`, `brickUP`, `stdBrick`, `SSPbrick`, `FourNodeTetrahedron`, `tri31` | Soil and continuum. Out of scope today (P2/P3 in the gap analysis). |
| `block2D`, `block3D`, `mesh`, `remesh`, `IGA` | Mesh generation and isogeometric analysis; a different product. |

### 3.4 Material families (P1-P2)

The catalog's 58 names and the gap analysis agree on the backlog; the top
items are unchanged by this review:

| Missing | Priority |
| --- | --- |
| `Viscous`, `ViscousDamper`, `BilinearOilDamper`, `Damper` | P1 (supplemental damping) — **but see §4, they are not usable as-is** |
| `ReinforcingSteel`, `Dodd_Restrepo`, `Steel4`, `SteelMPF` | P1 (reinforcement models beyond Steel02) |
| `ConcreteCM`, `Concrete06`, `Concrete07`, `FRPConfinedConcrete`, `ConfinedConcrete01` | P1 (confinement; `Concrete04` shipped) |
| `Parallel`, `Series`, `MinMax`, `InitStrain`, `InitStress`, `Multiplier`, `Penalty`, `TensionOnly`, `Fatigue`, `SimpleFracture` | P1 (wrapper materials — isolation systems are built from these) |
| `HyperbolicGap`, `ElasticPPGap`, `ENT` | P1 (gap and no-tension behaviour) |
| `Pinching4`, `Bilin`, `ModIMKPeakOriented`, `ModIMKPinching`, `HystereticBackbone` + `hystereticBackbone` | P1/P2 (calibrated component models; the app has `Hysteretic`, `HystereticSM`) |
| `PySimple1`, `TzSimple1`, `QzSimple1`, `PyLiq1`, … | P2 (soil springs) |
| `J2Plasticity`, `DruckerPrager`, `PM4Sand`, `PressureDependMultiYield*`, `PlateFiber`, `FSAM` | P2/P3 (geotechnical and continuum) |

### 3.5 Analysis features (P1-P2)

| Missing | What it buys |
| --- | --- |
| `modalDamping`, `modalDampingQ` | Damping assigned per mode instead of Rayleigh. The app offers Rayleigh only, including the Kinit/Kcomm slots. |
| `setElementRayleighDampingFactors` | Per-element damping without a region. Cheaper than `region -rayleigh` and often enough. |
| `updateMaterialStage`, `InitialStateAnalysis` | Construction staging and geostatic initial stress. Needed for staged construction and for any soil model. |
| `setPrecision`, `logFile` | Output precision and a solver log file. The app has a result-precision setting but the solver's own precision is fixed. |
| `setNumThreads` | The installed build is threaded; the app never sets the thread count. |
| `modalProperties`, `responseSpectrumAnalysis` | OpenSees' own modal/RSA commands. The app computes both itself (`core.modal`, `core.modal_combination`) for determinism and for CQC — this is a deliberate choice, not a gap. |
| `database`, `save`, `restore` | Checkpointing a running analysis. The app's crash recovery is snapshot-based, which covers the same need differently. |
| `parameter`, `sensitivityAlgorithm`, `computeGradients`, `randomVariable`, reliability commands | Sensitivity and reliability analysis: a different product surface, out of scope. |
| `searchPeerNGA`, `sdfResponse`, `ShallowFoundationGen`, `stripXML`, `convertBinaryToText`, PFEM/parallel commands | Utilities and other products' entry points. |

### 3.6 Restraints, loads and patterns

| Missing | What it buys |
| --- | --- |
| `sp` | **Static** imposed nodal displacement. The transient half shipped (`ImposedSupportMotionPattern` → `groundMotion` + `imposedMotion` + `MultipleSupport`); a static settlement or a prescribed displacement case still cannot be expressed. This is the cheapest P1 item in the list: one pattern field and one emitter. |
| `pressureConstraint` | Pressure on a surface. |
| `Triangular`, `Rectangular`, `Pulse` time series | Shaped pulses; `Trig` covers sines and sine-beats, and a ramp/pulse can be a `Path`, so this is convenience. |
| `modulatingFunction`, `correlate` | Modulating a ground motion, and correlated multi-support input. Relevant to multi-support excitation work. |
| Imposed *line* and *surface* displacements/forces, line/surface restraints and masses | The gidopensees P2 rows; convenience layered on `sp`/`load`/`mass`. |

## 4. What this review found that the gap analysis could not

The gidopensees gap analysis counts names. It cannot tell whether a name
works, and this review found three that do not behave as their schema says —
recorded in `services/catalog_emitters.py` and in the gap analysis:

- `Viscous` is accepted by the solver, but the **rate never reaches the
  material** with the elements the application builds: a ramped SDOF responded
  identically with C = 0, 50 and 100, and an imposed-velocity `zeroLength`
  hard-exited OpenSees. So "P1: add Viscous" is really "P1: add an element
  that feeds rate to a material, then Viscous".
- `Elastic_Perfectly_Plastic_with_Gap` does not follow its field names: with
  `gap = +0.002` it is zero in both directions, and with `gap = -0.002` the
  compression force peaks at half the yield strain and falls to zero at the
  yield strain.
- `ViscousDamper` needs the same element investigation as `Viscous`.

That reframes one item: the missing piece for supplemental damping is
**`twoNodeLink`** (§3.3), not the material.

## 5. Top recommendations, in order

1. **`rigidDiaphragm` + `rigidLink`** (P1): the constraint commands that make
   multi-storey 3D models possible, and the reason no bundled example exceeds
   64 elements.
2. **`sp` in a Plain pattern** (P1, small): static imposed displacement, which
   also unlocks settlement and prescribed-displacement studies.
3. **`twoNodeLink` + `ViscousDamper`** (P1): the element and the material
   together are what supplemental damping needs; either alone is useless.
4. **Section-level output** (`sectionForce`/`sectionDeformation`, or the
   basic-force pair) (P1): moment-curvature and wall/section response without
   post-processing end forces.
5. **Convergence diagnostics** (`numIter`, `testNorm`, `systemSize`) (P2):
   the data behind the "diagnostics dock" the roadmap already wants.
6. **Wrapper materials** (`Parallel`, `Series`, `MinMax`, `InitStrain`) (P1):
   a small, self-contained family that isolation and retrofitting workflows
   are built from.
7. **`setElementRayleighDampingFactors`** (P2): per-element damping, cheaper
   than a full `region` model and useful sooner.

Everything in §3.5's last block (sensitivity, reliability, PFEM, parallel,
isogeometric) and §3.3's continuum/soil families is out of scope on purpose:
they are different products sharing a solver.

---

## Reproduction

```python
import openseespy.opensees as ops, pathlib, re
surface = {n for n in dir(ops) if not n.startswith("_")}
text = "\n".join(f.read_text() for f in pathlib.Path("src/opensees_studio").rglob("*.py"))
used = set(re.findall(r"\b_?ops\.([A-Za-z_]\w*)\s*\(", text))
print(len(surface), len(used & surface), sorted(surface - used))
```
