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

## Regenerating the .osmodel files

If you change the Python scripts, run them to regenerate the saved models:

```bash
python examples/cantilever.py
python examples/portal_frame.py
python examples/space_frame_3d.py
python examples/sdof_pushover.py
```

Each script builds the project, saves it, reloads it, and asserts a clean
round-trip. The Python source is the source of truth; the `.osmodel` files
are generated artifacts checked in for convenience.
