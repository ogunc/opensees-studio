# Example models

Pre-built `.osmodel` files plus the Python scripts that produce them.
Each model is set up with whichever case types the post-processing
features need, so you can exercise the full GUI without manually
defining materials, sections, loads, and analysis cases.

## Files

| Model | Nodes | Elements | Cases | Best for demonstrating |
|---|---|---|---|---|
| `cantilever.osmodel` | 6 | 5 | Static × 2, Modal | Point & distributed loads, force diagrams, deformed shape, mode shapes |
| `portal_frame.osmodel` | 4 | 3 | Static, Modal, Transient | All Display features, simplest 3D |
| `space_frame_3d.osmodel` | 12 | 16 | Static, Modal, Transient (5% damping) | Realistic 3D rendering, multiple modes, damped EQ time-history |
| `sdof_pushover.osmodel` | 2 | 1 | Pushover, Modal | Monotonic pushover curve, HystereticMaterial |
| `portal_pushover.osmodel` | 4 | 3 | Pushover, Modal | Fiber sections, BeamWithHinges, nonlinear pushover with yielding |
| `ex1a_canti2d.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Original OpenSees Ex 1a with shared gravity, push, and earthquake cases |
| `ex1b_portal2d.osmodel` | 4 | 3 | Static preload, Pushover, Transient EQ | Original OpenSees Ex 1b elastic portal frame with distributed gravity |
| `ex2a_canti2d_elastic_element.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Variable-driven cantilever example with derived parameters |
| `ex2b_canti2d_inelastic_section.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | First nonlinear cantilever with aggregated uniaxial section |
| `ex2c_canti2d_inelastic_fiber_section.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Fiber-section cantilever with coupled axial-flexural nonlinearity |
| `ex3_canti2d_elastic_element.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Example 3 elastic build with unit-scaled parameters |
| `ex3_canti2d_inelastic_section.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Example 3 aggregated-section nonlinear build |
| `ex3_canti2d_inelastic_fiber_section.osmodel` | 2 | 1 | Static preload, Pushover, Transient EQ | Example 3 fiber-section nonlinear build |
| `ex4_portal2d_elastic_element.osmodel` | 4 | 3 | Static preload, Pushover, Transient sine | Example 4 elastic portal frame with separated build/analysis workflow |
| `ex4_portal2d_inelastic_section.osmodel` | 4 | 3 | Static preload, Pushover, Transient sine | Example 4 aggregated-section portal frame variant |
| `ex4_portal2d_inelastic_fiber_section.osmodel` | 4 | 3 | Static preload, Pushover, Transient sine | Example 4 fiber-section portal frame variant |
| `ex1a_canti2d_eq.osmodel` | 2 | 1 | Static preload, Transient EQ | OpenSees Ex 1a style gravity + base excitation workflow |
| `eigen_two_storey_shear_frame.osmodel` | 6 | 6 | Modal | equalDOF floor constraints, mode shapes, eigenvalue workflow |
| `eigen_two_storey_one_bay_frame.osmodel` | 6 | 6 | Modal | classic elastic frame modal example, sway mode shapes |
| `concrete04_cantilever.osmodel` | 2 | 1 | Static (gravity), Pushover | Popovics Concrete04 fiber section; proof-of-concept for the Concrete04 end-to-end stack |

## Quick tour

### 1. Force diagrams — `cantilever.osmodel`
```
File → Open → cantilever.osmodel
Analyze → Cases  → run "Tip-Load"
Display → Show Force Diagram → component "M3" → linear moment, max at fixed end (50 kN·m)
                              → component "V2" → constant -10 kN along the whole span
                              → component "N"  → ~zero (no axial load applied)
                              → component "T"  → ~zero (no torsion → console hint, no diagram)
Display → Show Deformed Shape  → classic cantilever curve
```
The load is applied along the global Y axis (perpendicular to the beam,
in the horizontal plane). With the default 3D vertical-reference
convention this gives V2 / M3 — i.e. the "in-plane bending" pair.

**Distributed load (UDL) variant** — run the second case to see a
parabolic moment diagram:
```
Analyze → Cases → run "Uniform-Load"
Display → Show Force Diagram → M3 → parabolic, max 25 kN·m at fixed end
                              → V2 → linear, max 10 kN at fixed end
```

### 2. Mode shapes — `portal_frame.osmodel` or `space_frame_3d.osmodel`
```
File → Open → space_frame_3d.osmodel
Analyze → Cases  → run "Modal-6"
Display → Animate Mode Shape → mode 1 = X-sway, mode 2 = Y-sway
                             → ▶ Play, scrub timeline, change scale
```

### 3. Time-history & hysteresis — `portal_frame.osmodel` or `space_frame_3d.osmodel`
```
File → Open → space_frame_3d.osmodel
Analyze → Cases  → run "EQ-4s"  (~5-10 sec on a modern laptop)
Display → Time-History Plot
   - Node 12 (roof corner) + DOF 1 (X displacement) → "Add trace"
   - Node 9 + DOF 1 → another trace, compare phase
Display → Hysteresis Plot
   - X = Node 12 / DOF 1, Y = Node 12 / DOF 3 → orbit
```

### 4. Pushover — `sdof_pushover.osmodel`
```
File → Open → sdof_pushover.osmodel
Analyze → Cases → run "Push-X"
Display → Show Pushover Curve
   → linear segment from origin, then softens through yield
```
Note: this demo keeps the column elastic (proper nonlinear hinges require
BeamWithHingesElement with fibre sections — infrastructure is in place,
fibre-section editor is future work).

### 5. Nonlinear pushover with fiber hinges — `portal_pushover.osmodel`
```
File → Open → portal_pushover.osmodel
Analyze → Cases → run "Push-X"
Display → Show Pushover Curve
   → initial linear stiffness, then yield plateau as base hinges form
   → peak base shear corresponds to concrete crushing + rebar yield
```
The columns use BeamWithHingesElements with FiberSections (concrete core
+ rebar layers) wrapped in a SectionAggregator (torsion spring).

### 6. Gravity + time-history chain — `ex1a_canti2d_eq.osmodel`
```bash
File → Open → ex1a_canti2d_eq.osmodel
Analyze → Cases → run "Earthquake"
Display → Time-History Plot
   - Node 2 + DOF 1 (Ux) → horizontal response of the cantilever tip
   - Node 2 + DOF 2 (Uy) → verify gravity stays essentially locked
```
This model is intentionally tiny but important for workflow coverage:
it demonstrates the general transient recipe of
`Static preload → loadConst reset → UniformExcitation transient`
using a real ground-motion record imported into a `PathTimeSeries`.

### 7. Original OpenSees Ex 1a bundle — `ex1a_canti2d.osmodel`
```bash
File → Open → ex1a_canti2d.osmodel
Analyze → Cases → run "Push" or "Earthquake"
Display → Show Pushover Curve / Time-History Plot
```
This is the original cantilever-column Example 1a packaged as one model
with a shared gravity preload plus both lateral load variants. It is a
good small benchmark for checking that pushover and transient workflows
behave consistently on the same geometry.

### 8. Original OpenSees Ex 1b bundle — `ex1b_portal2d.osmodel`
```bash
File → Open → ex1b_portal2d.osmodel
Analyze → Cases → run "Push" or "Earthquake"
Display → Show Pushover Curve / Time-History Plot
```
This is the original elastic portal-frame Example 1b bundled as one
project. It is especially useful because the gravity preload is carried
by a distributed beam load instead of nodal loads only.

### 9. Variable-driven cantilever example — `ex2a_canti2d_elastic_element.osmodel`
```bash
File → Open → ex2a_canti2d_elastic_element.osmodel
Analyze → Cases → run "Push" or "Earthquake"
Display → Show Pushover Curve / Time-History Plot
```
This is the Ex2a cantilever tutorial recast as a project model. It is
useful when we want the same basic physics as Ex1a but with all major
dimensions and derived quantities exposed as named parameters.

### 10. Nonlinear aggregated-section cantilever — `ex2b_canti2d_inelastic_section.osmodel`
```bash
File → Open → ex2b_canti2d_inelastic_section.osmodel
Analyze → Cases → run "Push" or "Earthquake"
Display → Show Pushover Curve / Time-History Plot
```
This is the first nonlinear cantilever benchmark in the tutorial series.
It demonstrates how separate axial and flexural uniaxial responses can
be aggregated into one section and used by a force-based beam-column element.

### 11. Fiber-section cantilever example — `ex2c_canti2d_inelastic_fiber_section.osmodel`
```bash
File → Open → ex2c_canti2d_inelastic_fiber_section.osmodel
Analyze → Cases → run "Push" or "Earthquake"
Display → Show Pushover Curve / Time-History Plot
```
This is the Ex2c fiber-section counterpart to Ex2b. It is useful for
checking coupled axial-flexural section behavior with inelastic concrete
and steel materials assigned directly to fibers and rebar layers.

### 12. Example 3 build variants — `ex3_canti2d_*.osmodel`
```bash
File → Open → ex3_canti2d_elastic_element.osmodel
Analyze → Cases → run "Push" or "Earthquake"
```
The Example 3 family is useful when we want the same cantilever analyses
to run on three different build styles: elastic element, aggregated
uniaxial section, and fiber section, all with unit-scaled parameters.

### 13. Modal shear-building example — `eigen_two_storey_shear_frame.osmodel`
```bash
File → Open → eigen_two_storey_shear_frame.osmodel
Analyze → Cases → run "Modal-2"
Display → Animate Mode Shape
   - mode 1 → in-phase storey sway
   - mode 2 → out-of-phase storey sway
```
This example is useful for validating modal workflows on a tiny model
that still needs multi-point constraints (`equalDOF`) to behave like an
idealized shear frame.

### 9. Modal elastic frame example â€” `eigen_two_storey_one_bay_frame.osmodel`
```bash
File â†’ Open â†’ eigen_two_storey_one_bay_frame.osmodel
Analyze â†’ Cases â†’ run "Modal-2"
Display â†’ Animate Mode Shape
   - mode 1 â†’ in-phase sway of the two storeys
   - mode 2 â†’ upper storey reverses relative to the first storey
```
This is the Chopra Example 10.5 frame counterpart to the shear-building
example above. It gives us a small modal benchmark with ordinary
beam-column frame behavior and no multi-point constraints.

### 13. Example 4 portal-frame variants
```bash
File -> Open -> ex4_portal2d_elastic_element.osmodel
Analyze -> Cases -> run "Push" or "Sine-Uniform"
Display -> Show Pushover Curve / Time-History Plot
```
The Example 4 family keeps the OpenSees split between model-building
and analysis files, but moves it into project variants. These are
useful benchmarks for pinned-base frame sway, distributed gravity on the
beam, and support-motion dynamics without depending on an external
earthquake file. The fiber-section transient is intentionally retained
as a strong nonlinear stress test and may stop early while still
producing useful partial histories.

## Regenerating the .osmodel files

If you change the Python scripts, run them to regenerate the saved models:

```bash
python examples/cantilever.py
python examples/portal_frame.py
python examples/space_frame_3d.py
python examples/sdof_pushover.py
python examples/portal_pushover.py
python examples/ex1a_canti2d.py
python examples/ex1b_portal2d.py
python examples/ex2a_canti2d_elastic_element.py
python examples/ex1a_canti2d_eq.py
python examples/ex2b_canti2d_inelastic_section.py
python examples/ex2c_canti2d_inelastic_fiber_section.py
python examples/ex3_canti2d_elastic_element.py
python examples/ex3_canti2d_inelastic_section.py
python examples/ex3_canti2d_inelastic_fiber_section.py
python examples/ex4_portal2d_elastic_element.py
python examples/ex4_portal2d_inelastic_section.py
python examples/ex4_portal2d_inelastic_fiber_section.py
python examples/eigen_two_storey_shear_frame.py
python examples/eigen_two_storey_one_bay_frame.py
```

Each script builds the project, saves it, reloads it, and asserts a clean
round-trip. The Python source is the source of truth; the `.osmodel` files
are generated artifacts checked in for convenience.
