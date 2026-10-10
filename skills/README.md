# Skills — Plataforma de análisis estructural por FEM para ingeniería civil

Biblioteca de **habilidades (skills) accionables** para construir y mantener una
herramienta profesional de análisis estructural por elementos finitos orientada a
ingeniería civil, capaz de **diseñar** y de realizar **análisis sísmicos** conforme a
los reglamentos nacionales de Latinoamérica y al **ASCE 7-22**.

Cada skill es una carpeta con un `SKILL.md` autocontenido: qué problema resuelve,
cuándo usarla, formulación, procedimiento, datos normativos con cita, verificación y
trampas conocidas. Están escritas para que las consuma **un agente o una persona**:
formato *Agent Skills* (`name` + `description` en el frontmatter) y contenido técnico
denso debajo.

**35 skills en siete tracks**: `core` (6), `seismic` (3), `codes` (8), `design` (3),
`platform` (3), `github` (5) e `interop` (7). El estado y los puntos abiertos de cada
una están en `_meta/catalog.md` y en `index.json`.

---

## 1. Cómo se usa

| Consumidor | Cómo la usa |
|---|---|
| Agente de código | Carga el `SKILL.md` cuya `description` coincide con la tarea antes de escribir código. |
| Ingeniero / revisor | Lee el skill como especificación de requisitos y checklist de aceptación. |
| QA | Usa la sección *Verificación* de cada skill como matriz de pruebas. |
| Product owner | Usa `_meta/catalog.md` como mapa de capacidades y hoja de ruta. |

Regla de oro: **una skill no inventa valores normativos**. Todo coeficiente
(\(R\), \(C_d\), \(\Omega_0\), límites de deriva, factores de sitio) va con cita de
norma, edición y artículo/tabla, o va dentro de un bloque `> ⚠️ VERIFICAR:`.

---

## 2. Mapa de habilidades

### Núcleo numérico (`core/`)

| Skill | Qué resuelve |
|---|---|
| `core/fem-formulation-core` | Elementos barra 3D, armadura, shell y sólido; matrices de rigidez, transformación de ejes, liberaciones, diafragma rígido, MPC y ensamblaje. |
| `core/fem-materials-and-sections` | Constitutivas (elásticas, plásticas, fibras), propiedades de sección, torsión, `FiberSection`, integración y bibliotecas de perfiles. |
| `core/nonlinear-and-solver-strategies` | Pushover, rótulas plásticas, Newton–Raphson/krylov, arc-length, criterios de convergencia y control de paso. |
| `core/modal-and-time-history` | Autovalores, degeneración, amortiguamiento, Newmark/HHT, integración paso a paso y escalado de registros. |
| `core/fem-verification-and-benchmarks` | Patch test, benchmarks analíticos y de la literatura, paridad de resultados y tolerancias de regresión. |
| `core/performance-and-scaling` | Numeración de GDL, solvers dispersos, memoria, paralelismo y perfiles de modelos grandes. |

### Sismo (`seismic/`)

| Skill | Qué resuelve |
|---|---|
| `seismic/seismic-hazard-and-site-response` | Peligro sísmico, clasificación de sitio (Vs30), amplificación, espectros elástico/reducido/diseño y su construcción multi-periodo. |
| `seismic/seismic-analysis-procedures` | Fuerza lateral equivalente, modal espectral (CQC/SRSS), corrección de cortante basal, torsión accidental, P-Δ, 100/30, THA y derivas. |
| `seismic/load-combinations-and-limit-states` | Combinaciones LRFD/ASD, sismo, viento, servicio, envolventes y estados límite. |

### Códigos (`codes/`)

| Skill | Jurisdicción |
|---|---|
| `codes/asce7-22-seismic-design` | EE. UU. — ASCE 7-22 (caps. 11, 12, 13, 15, 16) |
| `codes/nicaragua-rnc07-nscm22` | Nicaragua — RNC-07 (nacional) y NSCM-22 (Managua) |
| `codes/mexico-ntc-rcdf-cfe` | México — NTC-RCDF y MDOC/CFE |
| `codes/colombia-nsr10` | Colombia — NSR-10 (Título A/B) |
| `codes/peru-e030` | Perú — E.030 y complementos |
| `codes/chile-nch433-nch2369` | Chile — NCh433 y NCh2369 |
| `codes/ecuador-nec15` | Ecuador — NEC-15 (SE-DP, SE-HM) |
| `codes/code-crosswalk-and-extension` | Transversal — tabla de equivalencias entre códigos y **cómo añadir un país nuevo** sin tocar el núcleo. |

### Diseño (`design/`)

| Skill | Qué resuelve |
|---|---|
| `design/concrete-aci318` | Diseño y revisión de concreto reforzado (flexión, cortante, torsión, P-M, detailing sismorresistente). |
| `design/steel-aisc360-341` | Diseño de acero (LRFD/ASD, pandeo, P-M, conexiones) y sismorresistente (AISC 341/358). |
| `design/foundations-and-soil-structure` | Cimentaciones, capacidad de carga, asentamientos, pilotes, resortes Winkler e interacción suelo–estructura. |

### Plataforma (`platform/`)

| Skill | Qué resuelve |
|---|---|
| `platform/platform-architecture-and-services` | Arquitectura por capas, contratos entre módulos, persistencia, ejecución en subproceso y trazabilidad de unidades. |
| `platform/gui-cad-workflow-and-ux` | Flujo de modelado tipo CAD/SAP2000, snapping, undo/redo, tablas y accesibilidad. |
| `platform/results-reporting-and-compliance-audit` | Post-proceso, envolventes, memorias de cálculo, reportes y auditoría automática de cumplimiento. |

### GitHub y proceso de desarrollo (`github/`)

| Skill | Qué resuelve |
|---|---|
| `github/repo-workflow-and-branching` | Modelo de ramas `main`/`develop`, Conventional Commits, ciclo del pull request, revisión arquitectónica del proyecto, issues y forks. |
| `github/actions-ci-and-quality-gates` | Los flujos de CI reales (jobs `lint`, `test`, `gui`), matriz y versiones fijadas, puertas de calidad, secretos, artefactos y cómo depurar un fallo. |
| `github/releases-versioning-and-distribution` | Versionado semántico, CHANGELOG y notas de versión, tag `v*`, empaquetado de escritorio en tres plataformas, firma, hashes y publicación. |
| `github/gh-cli-and-collaboration` | La herramienta `gh` de punta a punta: issues, PR, revisiones, ejecuciones, artefactos, releases, secretos y automatización en bash. |
| `github/security-and-supply-chain` | Mínimo privilegio del token, secretos, protección de ramas, Dependabot, fijado de acciones por SHA, SBOM y procedencia. |

### Interoperabilidad con programas externos (`interop/`)

| Skill | Programa de origen | Qué resuelve |
|---|---|---|
| `interop/gid-problem-type-schemas` | gidopensees | Anatomía del *problem type* de GiD (`.prb`, `.mat`, `.cnd`, `.uni`, macros Tcl, escritores Basic) y su uso como fuente de esquema. |
| `interop/gid-model-to-opensees-conversion` | gidopensees | Conversión de un modelo GiD a modelo OpenSees: nodos, materiales, secciones, elementos, condiciones y bloques de análisis. |
| `interop/opensees-tcl-python-parity` | ambos | Correspondencia comando a comando Tcl ↔ OpenSeesPy, conversión de tipos y arnés de paridad de salidas. |
| `interop/opstool-data-layer-and-odb` | opstool | Base de resultados (ODB) sobre xarray/zarr/netcdf4, respuestas nodales y de elemento, datos modales y de pandeo. |
| `interop/opstool-visualization-and-gui` | opstool | API de visualización (modelo, modos, respuestas, animaciones, secciones) y su traslado al lienzo propio. |
| `interop/opstool-preprocessing-and-analysis` | opstool | Masas y cargas de gravedad, transformación de cargas, malla de secciones de fibra, importación de Gmsh y asistentes de análisis. |
| `interop/upstream-licensing-and-attribution` | ambos | GPL-3.0 frente a AGPL-3.0, modos de reutilización, atribución, procedencia por archivo y marca. |

---

## 3. Recetas de composición

- **Añadir el análisis sísmico de un país nuevo** → `codes/code-crosswalk-and-extension`
  (contrato del módulo de código) → el skill del país más parecido → registrar en
  `_meta/catalog.md`.
- **Implementar el motor de análisis** → `core/fem-formulation-core` →
  `core/fem-materials-and-sections` → `core/nonlinear-and-solver-strategies` →
  `core/fem-verification-and-benchmarks` (no se acepta un solver sin sus benchmarks).
- **Implementar el módulo sísmico** → `seismic/seismic-hazard-and-site-response` →
  `seismic/seismic-analysis-procedures` → `codes/asce7-22-seismic-design` o el
  skill nacional → `seismic/load-combinations-and-limit-states`.
- **Cerrar la fase de diseño** → `design/concrete-aci318` o
  `design/steel-aisc360-341` → `design/foundations-and-soil-structure` →
  `platform/results-reporting-and-compliance-audit`.
- **Antes de publicar una versión** → `core/fem-verification-and-benchmarks`
  + sección *Verificación* de cada skill tocado + `platform/results-reporting-and-compliance-audit`
  + `github/releases-versioning-and-distribution`.
- **Contribuir un cambio** → `github/repo-workflow-and-branching` (rama, commits, PR)
  → `github/actions-ci-and-quality-gates` (qué debe pasar en verde) →
  `github/gh-cli-and-collaboration` (comandos).
- **Endurecer el repositorio** → `github/security-and-supply-chain` →
  `github/actions-ci-and-quality-gates`.
- **Traer una capacidad de un programa externo** → `interop/upstream-licensing-and-attribution`
  (antes de copiar nada) → el skill del programa → `codes/code-crosswalk-and-extension`
  si además cambia el contrato de datos.

---

## 4. Convenciones de contenido

1. **Unidades.** Internamente SI coherente (N, m, kg, s, Pa, K); la capa de
   presentación convierte. Ninguna fórmula mezcla unidades sin declararlo.
2. **Trazabilidad normativa.** Toda magnitud regulada indica *norma · edición ·
   artículo/tabla*. Sin cita, no entra.
3. **Incertidumbre explícita.** Lo no comprobado va en `> ⚠️ VERIFICAR:` con qué
   falta y dónde se comprueba.
4. **Verificabilidad.** Cada algoritmo relevante trae caso de prueba con resultado
   esperado y tolerancia.
5. **Idioma.** Español técnico; los nombres de tablas y artículos se conservan en su
   idioma original.
6. **Sin secretos ni datos personales.**

Detalle completo en `_meta/style-guide.md`; plantilla en `_meta/skill-template.md`.

---

## 5. Estructura

```
skills/
├── README.md              ← este índice
├── index.json             ← catálogo máquina-legible (generado)
├── _meta/
│   ├── catalog.md         ← catálogo con estado y fuente normativa
│   ├── skill-template.md  ← plantilla canónica
│   └── style-guide.md     ← reglas de redacción y verificación
├── core/   seismic/   codes/   design/   platform/   github/   interop/
└── scripts/validate_skills.py
```

## 6. Validación

```bash
python skills/scripts/validate_skills.py          # valida frontmatter, secciones y nombres
python skills/scripts/validate_skills.py --index  # además regenera skills/index.json
```

El validador no necesita dependencias externas. Falla (exit ≠ 0) si un `SKILL.md`
no cumple el contrato: nombre distinto al directorio, `description` vacía o demasiado
larga, `metadata.track` ausente, secciones obligatorias faltantes o contenido por
debajo del mínimo.
