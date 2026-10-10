# Catálogo de habilidades

35 skills en siete tracks. Estado: `ready` (todo lo afirmado es verificable y no
queda ningún `VERIFICAR`) · `draft` (útil y utilizable, con puntos `VERIFICAR`
abiertos que impiden marcarla como verificada) · `stub` (esqueleto).

La columna **V** es el número de marcas `VERIFICAR` abiertas; el detalle está en la
sección *Registro de verificación* de cada skill. Fuente de verdad máquina-legible:
`skills/index.json`, regenerado con `python skills/scripts/validate_skills.py --index`.

## Núcleo numérico (`core/`) — 6

| # | Skill | Estado | V | Fuente principal |
|---|---|---|---|---|
| 1 | `core/fem-formulation-core` | draft | 8 | Bathe; Zienkiewicz; Cook; documentación de OpenSees |
| 2 | `core/fem-materials-and-sections` | draft | 6 | Mander; Kent–Scott–Park; Menegotto–Pinto; AISC |
| 3 | `core/nonlinear-and-solver-strategies` | draft | 9 | Crisfield; OpenSees `algorithm`/`integrator`; ASCE 41 |
| 4 | `core/modal-and-time-history` | draft | 6 | Chopra; Clough y Penzien; Newmark (1959); HHT (1977) |
| 5 | `core/fem-verification-and-benchmarks` | draft | 7 | NAFEMS; MacNeal–Harder; PEER; OpenSees |
| 6 | `core/performance-and-scaling` | draft | 2 | Davis; SuiteSparse; PETSc |

## Sismo (`seismic/`) — 3

| # | Skill | Estado | V | Fuente principal |
|---|---|---|---|---|
| 7 | `seismic/seismic-hazard-and-site-response` | draft | 9 | ASCE 7-22 caps. 11 y 21; NSR-10 A.2; E.030 |
| 8 | `seismic/seismic-analysis-procedures` | draft | 13 | ASCE 7-22 cap. 12; RNC-07; NSCM-22 |
| 9 | `seismic/load-combinations-and-limit-states` | draft | 13 | ASCE 7-22 cap. 2; NTC; NSR-10 B.2; RNC-07 |

## Códigos (`codes/`) — 8

| # | Skill | Jurisdicción | Edición | Estado | V |
|---|---|---|---|---|---|
| 10 | `codes/asce7-22-seismic-design` | EE. UU. | ASCE/SEI 7-22 | draft | 7 |
| 11 | `codes/nicaragua-rnc07-nscm22` | Nicaragua | RNC-07 (2007) y NSCM-22 (2022) | draft | 8 |
| 12 | `codes/mexico-ntc-rcdf-cfe` | México | NTC-RCDF y MDOC/CFE 2020 | draft | 6 |
| 13 | `codes/colombia-nsr10` | Colombia | NSR-10 (A, B, C, F) y CCP-14 | draft | 12 |
| 14 | `codes/peru-e030` | Perú | E.030 (con E.060 y E.090) | draft | 5 |
| 15 | `codes/chile-nch433-nch2369` | Chile | NCh433 y NCh2369 | draft | 29 |
| 16 | `codes/ecuador-nec15` | Ecuador | NEC-15 (SE-DP y SE-HM) | draft | 7 |
| 17 | `codes/code-crosswalk-and-extension` | Transversal | — | draft | 1 |

## Diseño (`design/`) — 3

| # | Skill | Estado | V | Fuente principal |
|---|---|---|---|---|
| 18 | `design/concrete-aci318` | draft | 12 | ACI 318-19 |
| 19 | `design/steel-aisc360-341` | draft | 5 | AISC 360-22; AISC 341-22; AISC 358-22 |
| 20 | `design/foundations-and-soil-structure` | draft | 13 | ASCE 7-22 caps. 12.13 y 19; NSR-10 H; E.050; NCh2369 |

## Plataforma (`platform/`) — 3

| # | Skill | Estado | V | Fuente principal |
|---|---|---|---|---|
| 21 | `platform/platform-architecture-and-services` | **ready** | 0 | `docs/architecture.md`; ADR-0002; `CLAUDE.md` |
| 22 | `platform/gui-cad-workflow-and-ux` | draft | 3 | Experiencia SAP2000/ETABS; WCAG 2.2 |
| 23 | `platform/results-reporting-and-compliance-audit` | draft | 5 | Práctica de memorias de cálculo; ASCE 7-22 |

## GitHub (`github/`) — 5

| # | Skill | Estado | V | Fuente principal |
|---|---|---|---|---|
| 24 | `github/repo-workflow-and-branching` | draft | 5 | `CONTRIBUTING.md`; `CLAUDE.md`; Convencional Commits |
| 25 | `github/actions-ci-and-quality-gates` | draft | 4 | `.github/workflows/ci.yml`; `tools/typecheck.py` |
| 26 | `github/releases-versioning-and-distribution` | draft | 3 | `.github/workflows/desktop.yml`; `tools/release_notes.py`; `packaging/` |
| 27 | `github/gh-cli-and-collaboration` | draft | 5 | Documentación de GitHub CLI y Git |
| 28 | `github/security-and-supply-chain` | draft | 3 | `.github/dependabot.yml`; guías de seguridad de GitHub |

## Interoperabilidad (`interop/`) — 7

Dos programas de terceros, de los que se reimplementan capacidades en OpenSees
Studio. Ambos son **GPL-3.0**; el proyecto es **AGPL-3.0** y la combinación está
amparada por la sección 13 de ambas licencias (ver la skill 35).

| # | Skill | Origen | Estado | V |
|---|---|---|---|---|
| 29 | `interop/gid-problem-type-schemas` | gidopensees 3.0.0-beta | draft | 4 |
| 30 | `interop/gid-model-to-opensees-conversion` | gidopensees 3.0.0-beta | draft | 3 |
| 31 | `interop/opensees-tcl-python-parity` | ambos | draft | 4 |
| 32 | `interop/opstool-data-layer-and-odb` | opstool 1.0.26 | draft | 6 |
| 33 | `interop/opstool-visualization-and-gui` | opstool 1.0.26 | draft | 5 |
| 34 | `interop/opstool-preprocessing-and-analysis` | opstool 1.0.26 | draft | 5 |
| 35 | `interop/upstream-licensing-and-attribution` | ambos | draft | 3 |

| Origen | Qué es | Licencia | Solapamiento con el proyecto |
|---|---|---|---|
| [gidopensees](https://github.com/rclab-auth/gidopensees) (AUTh) | *Problem type* de GiD que convierte un modelo GiD en OpenSees, con salida dual Tcl y Python | GPL-3.0 | Esquemas ya importados por ADR-0001 (`core/catalog/generated/`, solo esquema, sin cablear) |
| [opstool](https://github.com/yexiang92/opstool) | Paquete de Python de pre-proceso, post-proceso y visualización para OpenSeesPy | GPL-3.0 | Post-proceso y visualización; el proyecto ya tiene `services/result_store.py`, `services/deformation.py` y el lienzo PyVista |

## Cobertura por capacidad

| Capacidad | Skills |
|---|---|
| Modelado y ensamblaje | 1, 2, 21, 22 |
| Solución lineal y no lineal | 3, 6 |
| Dinámica y sismo | 4, 7, 8, 9 |
| Cumplimiento normativo | 10–17 |
| Dimensionamiento y revisión | 18, 19, 20 |
| Verificación y entrega | 5, 21, 23 |
| Proceso de desarrollo y publicación | 24–28 |
| Interoperabilidad con programas externos | 29–35 |

## Cómo cerrar un `draft`

Casi todas las skills están en `draft` por la misma razón: los valores tabulados de
los códigos no se pudieron leer de la copia oficial durante la redacción. Cerrarlas
es un trabajo acotado y siempre el mismo:

1. Abrir el bloque `> ⚠️ VERIFICAR` en la sección *Datos normativos*.
2. Transcribir el valor del documento oficial (norma · edición · tabla o artículo).
3. Registrarlo en el archivo de datos versionado correspondiente
   (`data/<jurisdiccion>/<code_id>/*.json`) con `value`, `unit`, `source` y
   `verified: true`.
4. Añadir la prueba unitaria que compara el valor del archivo con el publicado.
5. Borrar el bloque y actualizar la fila del *Registro de verificación*.
6. Cuando no quede ninguna marca, cambiar `metadata.status` a `ready` y ejecutar
   `python skills/scripts/validate_skills.py --index` (el validador rechaza
   `ready` con marcas pendientes).

## Cómo añadir una habilidad

1. Copiar `_meta/skill-template.md` a `<track>/<nombre>/SKILL.md`.
2. Fijar `name` = nombre del directorio y `metadata.track` = track.
3. Cerrar todos los `VERIFICAR` o dejar `status: draft`.
4. Registrar la fila en este catálogo.
5. Ejecutar `python skills/scripts/validate_skills.py --index`.
