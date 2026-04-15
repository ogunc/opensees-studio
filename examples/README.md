# Example models

Pre-built `.osmodel` files plus the Python scripts that produce them.
Each model is set up with whichever case types the post-processing
features need, so you can exercise the full GUI without manually
defining materials, sections, loads, and analysis cases.

## Files

| Model | Nodes | Elements | Cases | Best for demonstrating |
|---|---|---|---|---|
| `cantilever.osmodel` | 6 | 5 | Static, Modal | Force diagrams (V/M), deformed shape, mode shapes |
| `portal_frame.osmodel` | 4 | 3 | Static, Modal, Transient | All Display features, simplest 3D |
| `space_frame_3d.osmodel` | 12 | 16 | Static, Modal, Transient | Realistic 3D rendering, multiple modes, EQ-pulse time-history |

## Quick tour

### 1. Force diagrams — `cantilever.osmodel`
```
File → Open → cantilever.osmodel
Analyze → Cases  → run "Tip-Load"
Display → Show Force Diagram → component "M3" → linear moment, max at fixed end
                              → component "V2" → constant shear (-10 kN)
                              → component "N"  → ~zero (no axial load)
Display → Show Deformed Shape  → classic cantilever curve
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

## Regenerating the .osmodel files

If you change the Python scripts, run them to regenerate the saved models:

```bash
python examples/cantilever.py
python examples/portal_frame.py
python examples/space_frame_3d.py
```

Each script builds the project, saves it, reloads it, and asserts a clean
round-trip. The Python source is the source of truth; the `.osmodel` files
are generated artifacts checked in for convenience.
