# Plan — importar modelos PORTICO y cerrar las brechas donde nos supera

**Fuente:** [`jpreyes/portico-core`](https://github.com/jpreyes/portico-core)
(AGPL-3.0-or-later, open-core con CLA y edición Pro comercial), revisado en el
commit `7468071` (v0.2.0, 2026-07-18).
**Fecha:** 2026-10-21.

Regla de licencia para todo este plan: las dos bases son AGPL, pero PORTICO
pide CLA porque vende una edición comercial. **No se copia código**: se
reimplementa en Python a partir de la documentación y de las referencias
publicadas (fórmulas de los códigos, soluciones cerradas). Los modelos `.s3d`
de `examples/` se usan como *entrada de prueba* leída en tiempo de test, no
se vendorizan sin revisar su licencia caso por caso.

---

## Fase A — Importador `.s3d` (File → Import → PORTICO Model…)

### Estado (2026-10-21): A1 hecho

`services/s3d_import.py`, `views/dialogs/s3d_import.py`, ayuda
`file.import_s3d`. Lo aprendido al implementarlo, que corrige lo supuesto abajo:

- **Unidades.** La app PORTICO calcula siempre en kN-m-t (el selector de
  unidades está bloqueado); la etiqueta `units` del archivo sólo dice en qué
  sistema están los números (los benchmarks de SAP vienen en `kip-in` y
  `lb-in`). El importador escala **todo** por dimensión al sistema que elige el
  usuario (por defecto el más cercano: `kN-m` → SI m-N, `kip-in`/`lb-in` →
  US in-kip). Masa coherente = fuerza·s²/longitud (t en kN-m). El peso propio
  de PORTICO usa siempre g = 9.80665, que sólo es correcto en kN-m: para otro
  sistema el importador usa g en las unidades del proyecto y lo advierte.
- **Ejes locales.** PORTICO: `z = x × ref`, `y = z × x` (viga con y arriba).
  OpenSees (nuestro `vecxz`): viga con z arriba. En 3D casi todo miembro sale
  "intercambiado": `Iz`↔`Iy`, `Avy`↔`Avz`, `ry`↔`rz` en releases (la sección se
  nombra "(axes 2-3)"). En 2D los triedros coinciden. Las cargas distribuidas
  se proyectan como vectores, exacto para cualquier giro.
- **Timoshenko.** PORTICO es Timoshenko siempre que haya áreas de corte; en
  OpenSees 3.8 `ElasticTimoshenkoBeam` no admite releases ni cargas
  trapezoidales, así que esos miembros pierden la deformación por corte (se
  cuenta y se informa).
- **`prescDisp`** ya entra en A1: PORTICO lo impone en todos los casos
  estáticos, así que va en un patrón que corren todos.
- **Cargas sobre nodos o elementos inexistentes**: PORTICO las ignora en
  silencio (pasa en su `portico_simple.s3d`); aquí se cuentan.
- **Paridad**: 1-005, 1-014, 1-018 y 1-021 dan los mismos números que las
  corridas OpenSeesPy publicadas por PORTICO (error ≤ 1e-10).
  `tests/integration/test_s3d_import_run.py` las corre con
  `PORTICO_CORE_DIR` apuntando a un checkout; sin él se saltan, y quedan los
  voladizos con solución cerrada.
- **A2 (hecho):** áreas QUAD → `ShellMITC4` (membrana y placa pasan a cáscara
  completa, se advierte), diafragmas → `rigidDiaphragm` con el `masterId` de
  PORTICO (la masa del piso se reparte por igual entre sus nodos; PORTICO usa
  el tributario de vigas), links rígidos → `rigidLink` beam/bar y no rígidos →
  equalDOF, fuente de masa → `MassSource` (masa en UX, UY, UZ como PORTICO), y un
  modelo sólo con `prescDisp` recibe su propio caso estático. 1-010 coincide con
  PORTICO. Queda: triángulos (no hay cáscara de 3 nodos), casos de espectro (el
  espectro no está en el archivo), cargas térmicas, resortes
  unilaterales/acoplados/de suelo, Icm y excentricidad accidental de diafragmas,
  y cable/solo-compresión.

### A.1 Formato observado

Inventario sobre los 23 `.s3d` de `examples/` (`version: "1.0"`):

| Clave | Contenido | Destino en Studio |
|---|---|---|
| `units` | `kN-m` (17), `kip-in` (5), `lb-in` (1) | `UnitSystem`; `lb-in` no existe → factor de escala explícito o rechazo con mensaje |
| `mode` | `3D` / `2D` | `ndm`; un 2D se lleva al plano **X-Z** vía `core.plane` (verificar qué plano usa PORTICO en 2D) |
| `nodes[]` | `x,y,z`, `restraints{ux..rz}`, `nodeMass{mx..irz}`, `springs{kux..krz}`, `prescDisp` | `Node` + `Restraint6`, masa nodal, `Node.spring`; `prescDisp` → `ImposedDisplacement` |
| `elements[]` | `n1,n2,matId,secId`, `releases[12]`, `compressionOnly`, `cable` | `ElasticBeamColumn` (Timoshenko si la sección trae `Avy/Avz`) + releases de `frame_options`; `cable`/`compressionOnly` → advertencia (fase posterior) |
| `materials[]` | `E,G,nu,rho,alpha`, `design` | material elástico; `rho` es **masa** por volumen en PORTICO (comprobar) |
| `sections[]` | `A,Iz,Iy,J,Avy,Avz,kappay,kappaz`, `mod`, `Zz` | `ElasticSection` con áreas de corte; `mod` → modificadores de `frame_options` |
| `areas[]` | `QUAD`/`CST`, `behavior` membrane/plate/shell, `thickness`, `planeStrain`, `drilling` | `ShellMITC4Element` / `QuadElement`; `CST` → advertencia o quad degenerado (decidir) |
| `diaphragms[]` | `z`, `nodes`, `cm`, `mass`, `eccentricity`, `masterId` | `RigidDiaphragm` (+ masa en el nodo maestro) |
| `links[]` | `master`, `slave`, `rigid`, `dofs` | `RigidLink` / `EqualDOFConstraint` |
| `loadCases[]` | `type` static/spectrum, `selfWeight`, `specDir`, `loads[]` | `PlainLoadPattern` + `StaticCase`; `spectrum` → `ResponseSpectrumCase` sin espectro (pedirlo) |
| `loads[]` | `nodal{F}`, `dist{w,dir}` (+ trapezoidal), `temp{dTtop,dTbot}` en áreas | `NodalLoad`, `UniformElementLoad`/`TrapezoidalElementLoad`; `temp` → advertencia (Fase F) |
| `combinations[]` | `factors` | combinación de carga |
| `grids` | `x[],y[],z[]` | `GridSystem` Global |
| `massSource` | fuente de masa | `core.mass_source` |

### A.2 Diseño

- `services/s3d_import.py` (sin Qt), con el mismo contrato que
  `services/dxf_import.py`: devuelve `S3dImport(project, notes,
  dropped: Counter)`. **Nunca descarta en silencio**: todo lo no traducido
  se cuenta y se muestra.
- Validación defensiva: JSON que no es objeto, colecciones que no son listas,
  ids duplicados o referencias rotas → `S3dImportError` con mensaje claro.
- Convenciones a fijar con un test cada una (son la fuente de bugs):
  1. **Ejes locales**: PORTICO usa `VERT = 0.9994` y `ez = ex × ref`
     (`ref` = Z global, o X si el miembro es casi vertical). Traducir a
     `vecxz` explícito por elemento para que coincida.
  2. **Signo de `dist` con `dir: "gravity"`**: `w > 0` apunta a −Z.
  3. **Orden de `releases[12]`**: (i: ux..rz, j: ux..rz) — confirmar contra
     `js/solver/timoshenko.js`.
  4. **Iz / Iy**: confirmar cuál es fuerte respecto a los ejes locales.
  5. **Peso propio**: `selfWeight: true` → nuestro peso propio por unidad de
     peso (ρ·g), no como masa.
- Viewmodel + diálogo `S3dImportDialog` (resumen: conteos, unidades,
  advertencias) y un solo paso de undo, como el DXF.
- Ayuda: página en `core/help.py` (`TOPICS` + `ACTION_TOPICS`), README,
  CHANGELOG.

### A.3 Pruebas

- `tests/unit/test_s3d_import.py`: un `.s3d` mínimo escrito en el test
  (portal 2 barras), cada convención de A.2 con su propio caso, archivos
  corruptos.
- `tests/integration/test_s3d_parity.py`: importar `verif_1-018_static_portal`,
  `verif_1-014_modal_cantilever`, `verif_1-021_modal_bathe_wilson` y
  `verif_1-005a_settlement`, resolver con OpenSees y comparar contra los JSON
  de `tools/verif/opensees/results/` de PORTICO (su propia corrida
  OpenSeesPy) y contra la solución analítica. Si el archivo fuente no está
  disponible, el test se salta con razón explícita (no se vendoriza).

### A.4 Alcance por etapas

| Etapa | Contenido | Tamaño |
|---|---|---|
| A1 | nodos, apoyos, resortes, masas, materiales, secciones, barras, releases, cargas nodales/distribuidas, peso propio, casos estáticos, combinaciones, grillas | M — ✅ hecho |
| A2 | áreas shell/plate/membrane, diafragmas, links, `prescDisp`, casos de espectro | M — ✅ hecho (salvo espectros y triángulos) |
| A3 | export `.s3d` (ida y vuelta) — opcional, solo si hay demanda | S |

---

## Fase B — Manual de verificación (prioridad alta) — ✅ hecho

**Estado (2026-10-21):** `tools/verification_manual.py` genera
`docs/verification-manual.md` con 15 casos (V-01 a V-15) y
`tests/integration/test_verification_manual.py` falla si un caso sale de su
tolerancia o el archivo no está al día. Hallazgo: con un material
elastoplástico perfecto, pasado ~10 desplazamientos de fluencia el elemento
`forceBeamColumn` deja de converger su estado seccional y el momento sube por
encima de Mp (V-15 se limita a 8 y lo documenta). Bathe–Wilson y el equilibrio
global de todos los ejemplos quedan para una ampliación.

Es lo que PORTICO tiene y nosotros no: un documento publicable que dice
"caso X, referencia Y, error Z %".

- `docs/verification/` con un archivo por caso: modelo, referencia
  (analítica / publicada), tabla de resultados, error relativo, veredicto.
- Generado, no escrito a mano: `tools/verification_manual.py` corre los casos
  (reutilizando `tests/integration`), escribe la tabla y falla si un error
  supera la tolerancia declarada. Un job de CI (o el job de integración
  existente) lo ejecuta, así el manual nunca queda desactualizado.
- Catálogo inicial (ya tenemos casi todos como tests de integración):
  voladizo con carga puntual y UDL, pórtico estático, voladizo modal,
  Bathe–Wilson (si se puede reproducir con datos publicados), viga con quads,
  armadura básica, pushover SDOF, P-Δ vs. fórmula de amplificación,
  asentamiento de apoyo, equilibrio global ΣR = ΣF en todos los modelos de
  `examples/`.
- Casos que solo nosotros podemos mostrar: sección de fibras vs. momento-
  curvatura teórico, Steel02/Concrete02 cíclico vs. curvas de referencia.

Tamaño: M. No depende de la Fase A, pero la Fase A le agrega casos.

---

## Fase C — Verificación de diseño D/C (AISC 360-16 primero) — ✅ hecho (AISC + derivas)

**Estado (2026-10-21):** `core/design/aisc360.py` (D2, E3, E4, E7, F2, F3, F6,
G2.1, G6, H1), `core/design/settings.py` (`Project.design`, omitido si no se
usa y fuera de la huella de resultados), `services/steel_design.py` (demandas en
25 estaciones por miembro, expansión de combinaciones, ± espectro, Cb por F1-1)
y el menú Design con Steel Frame Check y Storey Drift Check. Verificado contra
los ejemplos AISC E.1A, F.1-1A, F.1-2A, G.1A y H.1A (manual D-01 a D-05).
**2026-10-22:** canales (E4, F2, F6, G6), tees (F9), ángulos de alas iguales
(E3 en z, E4, F10, G3), HSS rectangulares (E7, F7, G4) y circulares/tubos (E7-6,
F8, G5) en `core/design/aisc360_shapes.py`; Design → Display Steel Ratios on
Model colorea por D/C y el reporte de cálculo imprime la verificación.
Pendiente: ángulos de alas desiguales y dobles (flexión en ejes principales),
rotura en tracción (área neta), torsión, ACI 318.

Ya tenemos la librería AISC v16 (`core/aisc.py`), combinaciones de código
(`core/code_combinations.py`, ASCE 7) y fuerzas de elemento.

- `core/design/aisc360.py` (puro, sin Qt): tracción (D2), compresión (E3,
  con pandeo flexural; E4 después), flexión (F2–F3 para W y canales),
  corte (G2) e interacción H1-1. Cada función devuelve capacidad, demanda,
  D/C y la ecuación aplicada, para que el reporte la cite.
- Parámetros por miembro: K, longitud no arriostrada Lb, Cb (por defecto 1.0
  con advertencia), método LRFD/ASD.
- `services/design_check.py`: envolvente de combinaciones → D/C por miembro.
- Vista: colorear miembros por D/C (reusar la escala de `DiagramRenderer`),
  tabla de resultados y sección en el reporte (`services/report.py`).
- Pruebas: ejemplos resueltos del *AISC Design Examples* (v16), ecuación por
  ecuación, más un caso de punta a punta.
- Después, en este orden: derivas de entrepiso (ya existe
  `core/storey_results.py`; falta el chequeo contra límite), ACI 318
  (flexión/corte de vigas, P-M de columnas), NCh433/espectros locales como
  *preset* opcional.

Tamaño: L (AISC) + M (derivas).

---

## Fase D — Tutoriales y documentación en español — ✅ hecho

**Estado (2026-10-21):** tres tutoriales en inglés y español en
`docs/tutorials/` (diseño de acero AISC + derivas sobre el nuevo ejemplo
`steel_frame_design`, edificio con diafragmas + espectro + derivas NCh433,
importar PORTICO), `README.es.md`, y `tools/tutorial_screenshots.py` que genera
las capturas de los diálogos sin GPU. El visor 3D necesita OpenGL y no se
captura en un contenedor; queda el tutorial de pushover con fibras y la
internacionalización de la interfaz.

- `docs/tutorials/` con 3 tutoriales paso a paso con capturas:
  1. Edificio de 3 pisos con diafragma: modal + espectro (`building_3storey_diaphragm`).
  2. Pushover de un pórtico de acero con fibras hasta el colapso
     (`portal_pushover.py`) — aquí OpenSees muestra lo que PORTICO no puede.
  3. Tiempo-historia con registro PEER y escalamiento a espectro objetivo.
- Capturas generadas por script con la app real (reutilizar `tools/` y el
  harness GUI), para que se regeneren cuando cambie la UI.
- Español: traducir README y tutoriales como `*.es.md` (patrón de PORTICO).
  Internacionalizar la UI queda fuera de este plan (costo alto con Qt).

Tamaño: M.

---

## Fase E — Análisis de práctica profesional — 🟡 en curso

**Estado (2026-10-21):** líneas de influencia y cargas móviles hechas: caso
`InfluenceLineCase` (una resolución lineal por parada, modelo construido una
sola vez), `InfluenceLineResults` en el almacén y el CLI, Display → Influence
Line con envolvente de vehículo en ambos sentidos, caso V-16 del manual y el
ejemplo `bridge_influence_line` (camión HL-93). Temperatura en marcos hecha
(cargas nodales equivalentes y corrección de esfuerzos, V-17). Quedan: etapas
constructivas, temperatura en cáscaras, tendones. Cables/solo compresión: hechos en el importador
(barras con material elástico de un solo lado, casos con Newton).

Solo lo que OpenSees permite hacer bien:

| Funcionalidad | Cómo en OpenSees | Tamaño |
|---|---|---|
| Etapas constructivas | casos encadenados (`preload_case_ids` ya existe) + activar/desactivar elementos por etapa (`remove element`, o rigidez reducida); empezar por "agregar por etapa" | L |
| Cargas móviles / líneas de influencia | barrido de carga unitaria en estático lineal, envolvente; sin solver nuevo | M — ✅ hecho |
| Gradiente térmico | `eleLoad -beamThermal` en barras; en shells solo si el elemento lo soporta | S–M — ✅ hecho en marcos (cargas equivalentes + corrección; `-beamThermal` no existe para el elemento elástico) |
| Cables / solo compresión | `CorotTruss` + material ENT / tensión-solo (ya hay `CorotTrussElement`) | S — ✅ hecho (importador: truss + `Elastic` con `Eneg`, Newton; SAP 1-012 A/B/C) |
| Tendones de pretensado | carga equivalente (fase 1); `Steel` con preesfuerzo inicial (fase 2) | M |

---

## Fase F — Lo que no se copia

- **Solver JS / app web**: nuestro motor es OpenSees por diseño (ADR-0003).
- **Asistente LLM**: fuera de alcance de este plan; si llega, como servicio
  opcional que produce un `Project`.
- **Mallado libre** (Blossom, etc.): solo si los usuarios lo piden; hoy
  `core/mesh.py` cubre el mallado mapeado.

---

## Orden propuesto

1. ✅ **A1** importador básico + tests de paridad (desbloquea casos para B).
2. ✅ **B** manual de verificación generado en CI.
3. ✅ **C** AISC 360 D/C + chequeo de derivas.
4. ✅ **A2** áreas, diafragmas, links, fuente de masa.
5. ✅ **D** tutoriales y documentación en español.
6. **E** análisis de práctica profesional, por demanda.

Cada ítem es un PR propio y cumple el checklist de `CLAUDE.md` (help pages,
docs, CHANGELOG, gates).
