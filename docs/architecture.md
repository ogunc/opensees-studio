# Architecture

## Layering

OpenSees Studio uses a strict **MVVM + service layer** architecture. Dependencies
flow in **one direction only**: outer layers may depend on inner layers, never
the reverse.

```
┌─────────────────────────────────────────────────────────────────┐
│  views/         Qt widgets, dialogs, 3D canvas — PySide6 only   │
│       ▲                                                          │
│       │ signals/slots, viewmodel binding                         │
│  viewmodels/    Qt-aware adapters, QUndoStack, selection state   │
│       ▲                                                          │
│       │ pure Python calls                                        │
│  services/      OpenSeesRunner, PersistenceService, Results      │
│       ▲                                                          │
│       │                                                          │
│  core/          Project, Node, Element, Material — pure Python   │
│                 NO Qt imports. NO openseespy imports.            │
└─────────────────────────────────────────────────────────────────┘
```

### Why this matters

- The `core` package is testable without a display server, without OpenSees,
  and without Qt. CI runs `pytest tests/unit/` in milliseconds.
- Replacing OpenSeesPy with another solver (e.g. `xara`, a future fork) only
  touches `services/opensees_runner.py`.
- A future CLI or Jupyter frontend reuses `core` and `services` unchanged.

## Package map

| Package | Responsibility | Allowed imports |
|---|---|---|
| `core` | Domain entities and invariants | stdlib, numpy, pydantic |
| `services` | I/O, solver invocation, persistence | core + stdlib + h5py + openseespy |
| `viewmodels` | Bridge core ↔ Qt; expose Qt signals; manage undo/redo | core, services, PySide6 |
| `views` | Pure UI; no business logic | PySide6, pyvistaqt, viewmodels |
| `commands` | `QUndoCommand` subclasses; mutate model via services | services, viewmodels |

## Threading

The Qt main thread owns all widgets. Heavy computation happens elsewhere:

- **OpenSees analysis** runs in a `QThread` worker (`services.opensees_runner.AnalysisWorker`).
- The worker emits `progress(int)`, `log(str)`, `finished(ResultsHandle)` signals.
- The worker checks `QThread.currentThread().isInterruptionRequested()` between
  analysis steps so the user can cancel.
- Results are written to HDF5; only a lightweight `ResultsHandle` (file path +
  metadata) crosses the thread boundary.

## Persistence

- Project files: `*.osmodel` — a JSON document validated by Pydantic models.
  Human-readable, diff-able, version-controllable.
- Results files: `*.osresults.h5` — HDF5; one group per analysis case; datasets
  for displacements, reactions, element forces, stresses.

## OpenSeesPy command sequencing

`OpenSeesRunner` always emits commands in this order; the model layer enforces
that all required pieces exist before a run can be requested:

1. `wipe()` and `model('basic', '-ndm', ndm, '-ndf', ndf)`
2. `node(...)` for every node
3. `fix(...)` for every restrained DOF
4. `uniaxialMaterial(...)` / `nDMaterial(...)`
5. `section(...)` (if used)
6. `geomTransf(...)` for frame elements
7. `element(...)` for every element
8. `timeSeries(...)`
9. `pattern(...)` with nested `load(...)`
10. `recorder(...)`
11. `system / numberer / constraints / integrator / algorithm / analysis`
12. `analyze(...)`

Any deviation from this order is a runtime error in OpenSees. The runner
asserts the order at the service boundary; the UI never has to think about it.
