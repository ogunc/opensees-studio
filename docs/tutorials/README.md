# Tutorials

**English** · [Español](README.es.md)

Step-by-step walkthroughs on the bundled examples. Each one is in English and in
Spanish.

1. [Designing a steel moment frame (AISC 360-16)](01-steel-frame-design.md) —
   Section Library shapes, combinations, Design → Steel Frame Check, member
   overrides and the storey drift check. Model: `examples/steel_frame_design.osmodel`.
2. [A building with rigid floors: modes, response spectrum and drift](02-building-spectrum-drift.md) —
   storeys, diaphragms, mass source, CQC and an NCh433 drift limit. Model:
   `examples/building_3storey_diaphragm.osmodel`.
3. [Bringing a PORTICO model into OpenSees Studio](03-importing-portico.md) —
   File → Import → PORTICO Model, unit scaling and what changes on the way.

Tutorial 1 covers the AISC 360-16 member and drift checks. The AISC 341-22
seismic checks, the AISC 358-22 RBS connections and the AISC 360 Chapter J
connection checks are documented in the in-app help (F1) on their Design menu
pages; the design decisions and scope are in
[ADR-0004](../adr/ADR-0004-steel-design.md).

The dialog screenshots are generated from the current code by
`tools/tutorial_screenshots.py` (`QT_QPA_PLATFORM=offscreen python tools/tutorial_screenshots.py`),
so they can be refreshed whenever a dialog changes.
