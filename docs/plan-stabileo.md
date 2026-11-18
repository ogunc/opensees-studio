# Plan — lo que vale la pena tomar de Stabileo

**Fuente:** [`lambdaclass/stabileo`](https://github.com/lambdaclass/stabileo)
(AGPL-3.0, solver propio en Rust/WebAssembly, normas CIRSOC), revisado el
2026-11-13 (v0.5.0).
**Fecha:** 2026-11-13.
**Perfil que guía la selección:** OpenSees Studio es una herramienta de
**análisis y diseño profesional**. Quedan fuera la docencia (método de rigidez
paso a paso, ejercicios), la IA, lo web (recálculo en vivo, enlaces), las normas
latinoamericanas y el portugués; también el análisis armónico y el colapso
plástico.

Regla de licencia: no se copia código. Se reimplementa sobre OpenSees a partir
de la literatura y de los códigos publicados. Todas las piezas necesarias
existen en OpenSeesPy 3.8 (probado: `ShellDKGQ`, `ShellNLDKGQ`, `ShellDKGT`,
`TDConcreteMC10`, `PySimple1`, `TzSimple1`, `QzSimple1`, `InitStressMaterial`,
`remove element`).

Cada punto es un PR con su ayuda, README/README.es, CHANGELOG y los gates de
`CLAUDE.md`. Cada entrega suma sus benchmarks externos al Verification Manual
(punto 9).

---

## Fase 0 — Confianza en los resultados

| # | Entrega | Estado |
|---|---|---|
| 10 | **Snapshots de resultados y "Results changed".** Cada caso de cada ejemplo fijado por una huella en `tests/data/results_snapshots.json`; CI falla si un número se mueve más de 1e-5; `--write --reason` registra el antes/después en `docs/results-changes.md`. | Hecho |
| 11 | **Diagnóstico de mecanismos.** Check Model (y la revisión de Run) clasifica cada movimiento libre (cuerpo rígido, rotación libre, nudo entre barras alineadas, desplazamiento lateral), nombra nudos y elementos, dice qué hacer y **Show the motion** lo anima. | Hecho |

## Fase 1 — Análisis

| # | Entrega | Verificación | Estado |
|---|---|---|---|
| 1 | Láminas `ShellDKGQ`, `ShellNLDKGQ`, `ShellDKGT` (triángulos) | Placa de Timoshenko (V-18), Scordelis-Lo (V-19) | Hecho |
| 2 | Construcción por etapas: fases que agregan/quitan grupos y aplican cargas sobre el estado anterior | Columna construida piso a piso (V-20), retiro de puntal | Hecho |
| 3 | Postensado como cargas equivalentes (trazado parabólico, fricción, wobble, pérdida diferida) y fluencia/retracción fib MC2010 (`TDConcreteMC10`) en etapas dependientes del tiempo | Viga con cable recto y parabólico (cerradas), columna a 10 000 días (V-21) | Hecho |
| 4 | Interacción suelo-estructura: asistente de pilote con resortes p-y / t-z / q-z por estrato | Fórmulas de Matlock y API a mano; capacidad axial = fuste + punta | Hecho |

## Fase 2 — Diseño

| # | Entrega | Verificación | Estado |
|---|---|---|---|
| 5 | Hormigón armado ACI 318-19: P-M por compatibilidad (cualquier sección de fibras), biaxial (Bresler), corte, umbral de torsión, cuantía mínima y εt en vigas; ratios en el modelo. Pendiente para una segunda entrega: esbeltez, muros especiales y detallado sísmico, memoria de cálculo | Viga y columna a mano (D-15) | Hecho (1.ª entrega) |
| 6 | Placas base (AISC DG1 + ACI 318 cap. 17) y uniones apernadas: prying y grupos excéntricos (método elástico), como calculadoras | Expresiones de DG1, ACI y Manual AISC a mano | Hecho |

## Fase 3 — Producto

| # | Entrega | Estado |
|---|---|---|
| 8 | Interfaz en español: catálogo `data/i18n/es.json`, filtro de eventos que traduce cada ventana al mostrarse, Opciones → Idioma, traducciones de Qt; las páginas de ayuda quedan en inglés | Hecho |

## Transversal

| # | Entrega | Estado |
|---|---|---|
| 9 | Verificación externa en el Verification Manual: placa de Timoshenko con DKG (V-18), Scordelis-Lo (V-19), construcción por etapas (V-20), fluencia MC2010 (V-21), elástica de grandes rotaciones (V-22), viga y columna ACI (D-15); 37 casos en total | Hecho |
