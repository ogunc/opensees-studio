# Tutoriales

[English](README.md) · **Español**

Recorridos paso a paso sobre los ejemplos incluidos. Cada uno está en inglés y en
español.

1. [Diseño de un marco de acero (AISC 360-16)](01-steel-frame-design.es.md) —
   perfiles de la Section Library, combinaciones, Design → Steel Frame Check,
   ajustes por miembro y la verificación de derivas. Modelo:
   `examples/steel_frame_design.osmodel`.
2. [Un edificio con losas rígidas: modos, espectro y derivas](02-building-spectrum-drift.es.md) —
   pisos, diafragmas, fuente de masa, CQC y un límite de deriva de NCh433. Modelo:
   `examples/building_3storey_diaphragm.osmodel`.
3. [Traer un modelo de PORTICO a OpenSees Studio](03-importing-portico.es.md) —
   File → Import → PORTICO Model, escalado de unidades y qué cambia en el camino.

Las capturas de los diálogos se generan con el código actual mediante
`tools/tutorial_screenshots.py`
(`QT_QPA_PLATFORM=offscreen python tools/tutorial_screenshots.py`), así que se
pueden renovar cada vez que cambie un diálogo.
