---
name: gid-model-to-opensees-conversion
description: >-
  Convierte un modelo GiD preparado con el problem type gidopensees en un
  Project de OpenSees Studio: lee OpenSees.prb, OpenSees.mat, OpenSees.cnd y
  OpenSees.uni, interpreta el lenguaje Basic de los escritores de bas/ (*set
  var, *set Group, *loop nodes *OnlyInGroup, tcl(), *format), traduce cada
  objeto a Node, Element, Material, Section, Load, Constraint y AnalysisCase, y
  resuelve la partición de restricciones de los nudos y líneas de intersección.
  Úsala al importar un modelo .gid, al interpretar un escritor .bas o su pareja
  *Py.bas, al depurar un factor 1000 en kN/kPa/ton, o cuando un ops.fix no
  coincide con lo declarado en GiD.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "gidopensees 3.0.0-beta"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, analysis]
---

# Conversión de un modelo GiD (gidopensees) a un modelo OpenSees

## Cuándo usar esta skill

- Llega un modelo preparado con el *problem type* `gidopensees` (un `.gid` con `OpenSees.prb`, `OpenSees.mat`, `OpenSees.cnd`, `OpenSees.uni`) y hay que convertirlo en un `Project`.
- Hay que interpretar un escritor de `bas/` — `<Objeto>.bas` (Tcl) o `<Objeto>Py.bas` (OpenSeesPy) — o depurar por qué las dos salidas difieren.
- Un `ops.fix` del modelo generado no coincide con lo definido en GiD, o un nudo de intersección queda con la restricción equivocada.
- Una magnitud aparece multiplicada o dividida por 1000 (kN ↔ N, kPa ↔ Pa, ton ↔ kg) al pasar de la salida de GiD al modelo de Studio.
- **No** usar esta skill para el post-proceso de gidopensees (`post/`, `exe/OpenSeesPost.exe`) ni para el formato ODB de `opstool`: son flujos distintos. Para el esquema puro de un material, → `core/fem-materials-and-sections`.

## Alcance y límites

Cubre la conversión de pre-proceso completa: inventario de esquema, unidades, geometría, materiales, secciones, elementos, restricciones, acciones y casos de análisis, con la partición de restricciones que exige el problema conocido del proyecto.

Queda fuera la malla de fibras de GiD, la generación de texto Tcl, el post-proceso a GiD, los ejecutables de `exe/`, las plantillas binarias de `geo/` y el intérprete Basic de GiD. Supuestos: edición `gidopensees 3.0.0-beta` (30/11/2023) y pares `(ndm, ndf)` admitidos por Studio `(2,2), (2,3), (3,3), (3,6)`.

## Entradas y supuestos

| Dato | Origen | Si falta |
|---|---|---|
| Árbol de datos del problema | `OpenSees.prb` (BOOK/TITLE/QUESTION/VALUE/STATE) | no se resuelve la visibilidad de campos: error |
| Esquema de materiales | `OpenSees.mat` | no se importa ningún material |
| Esquema de condiciones | `OpenSees.cnd` | no se importan restricciones ni cargas |
| Tabla de unidades | `OpenSees.uni`, bloques `BEGIN TABLE` y `BEGIN SYSTEM(name)` | se bloquea: la unidad no se asume |
| Intérprete de Python | `Python.path` (ruta absoluta al ejecutable) | se usa el del proceso de importación |
| Nombre y ruta del proyecto | `SetProjectNameAndPath`, `GetProjectPath`, `GetProjectName` (`OpenSees.tcl`) | se toma del archivo `.gid` |
| Eje vertical | `GetVerticalAxis`/`SetVerticalAxis` | aviso explícito (2.9.5 añadió el prompt) |
| Dimensión y DOF por nudo | grupos de GiD `2DOF`, `3DOF`, `6DOF`, `3PDOF` vía `ReturnNodeGroupDOF` | error: sin grupo no hay partición de restricciones |
| Grupo activo de condiciones | `*set Group *GroupName *nodes` de cada escritor | el nudo no entra en `*loop nodes *OnlyInGroup` |

> ⚠️ VERIFICAR: el formato del directorio `.gid` (malla, grupos, condiciones asignadas) no está documentado en ninguno de los dos repositorios. Se comprueba abriendo un modelo de `wiki/examples/` con GiD en modo batch y comparando el `.dat` resultante, o leyendo `doc/GiD+OpenSees_Interface_User_Manual.pdf`. Mientras tanto el importador debe consumir una exportación de GiD, no leer el `.gid`.

## Fundamento y formulación

El *problem type* no serializa un modelo neutro: **genera texto**. Cada escritor de `bas/` es una plantilla en lenguaje Basic de GiD que recorre las entidades seleccionadas y emite comandos; existen en parejas, `<Objeto>.bas` para Tcl y `<Objeto>Py.bas` para OpenSeesPy. Convertir consiste en sustituir el intérprete Basic por un evaluador en Python y el texto por entidades del modelo.

Subconjunto de Basic observado en `bas/Model/Nodes.bas`:

```text
*set var cntcurrNodes=0
*set Group *GroupName *nodes
*if(ndime==3)
*loop nodes *OnlyInGroup
*set var dummy=tcl(AssignToGroupNodeList *NodesNum *currentDOF)
*set var cntcurrNodes=operation(cntcurrNodes+1)
*format "%6d%12g%12g%12g"
node *NodesNum *NodesCoord(1) *NodesCoord(2) *NodesCoord(3)
*end nodes
*elseif(ndime==2)
# ... *format "%6d%12g%12g" y node con dos coordenadas
*endif
```

`*set var` asigna; `*set Group <grupo> *nodes` fija el conjunto; `*if`/`*elseif`/`*endif` ramifican sobre `ndime` o `currentDOF`; `*loop <entidad> *OnlyInGroup` itera; `tcl(...)` llama a un ayudante de `bas/tcl/`; `*format` fija el ancho de cada campo; `*NodesNum`, `*NodesCoord(i)` y `*Cond(i,...)` acceden al modelo GiD; `*\` continúa la línea.

La misma idea sobre `MatProp`, en `bas/Materials/Uniaxial/Steel02Py.bas`:

```python
*if(strcmp(MatProp(Formulation),"Stress-Strain")==0)
ops.uniaxialMaterial("Steel02", *MaterialID, *MatProp(Yield_Stress_Fy,real), *MatProp(Initial_elastic_tangent_E0,real), *MatProp(Strain-hardening_ratio_b,real), *\
*MatProp(Parameter_R0,real), *MatProp(Parameter_cR1,real), *MatProp(Parameter_cR2,real), *\
*MatProp(Isotropic_hardening_parameter_a1,real), *MatProp(Isotropic_hardening_parameter_a2,real), *MatProp(Isotropic_hardening_parameter_a3,real), *MatProp(Isotropic_hardening_parameter_a4,real), *MatProp(Initial_stress,real))
*elseif(strcmp(MatProp(Formulation),"Force-Deformation")==0)
# ... rama con Force_Fy / Initial_stiffness_K
*else
# ... rama momento-rotación con Moment_My / Moment_per_rotation_unit
*endif
```

`MatProp(Formulation)` es un campo de selección del `.mat` y decide **cuál es el material** y qué parámetros son físicos: las tres ramas no son el mismo material con otros nombres, y colapsarlas pierde el significado de los campos. Salida generada del dataset *Plane Frame - Static and Modal Analysis* (`wiki/python_tests/datasets/`), que fija formato y orden:

```python
ops.model("basic", "-ndm", 2, "-ndf", 3)
ops.node(     1,            6,            0)      # coordenadas truncadas por *format
ops.fix(     1,   1,   1,   1)
ops.mass(    46,        5,        0,        0)
ops.geomTransf('Linear', 1)
ops.element('elasticBeamColumn',      1,    101, 102,       0.09,    3.3e+07,   0.000675   , 1, '-mass',        0)
ops.timeSeries('Linear', 200)
ops.pattern('Plain', 100, 200)
ops.load(   311,       20,        0,        0)
ops.wipeAnalysis()
ops.system('BandGeneral'); ops.numberer('RCM'); ops.constraints('Transformation')
```

**Partición de restricciones.** OpenSees no combina restricciones: varios `fix` sobre el mismo nudo no se acumulan. gidopensees lo resuelve agrupando cada nudo en `2DOF`, `3DOF`, `6DOF` o `3PDOF`; `ReturnNodeGroupDOF` (`bas/tcl/MultipleDOF.tcl`) devuelve 2, 3, 6, 30 o 0, y cada escritor emite `ops.fix` sólo cuando `nodeDOF == currentDOF`. Por eso un nudo de intersección de dos líneas con restricciones distintas, y una línea de intersección de dos superficies con restricciones distintas, deben tratarse por separado: el nudo pertenece a una sola partición y el modelo de Studio guarda **un** `Restraint6` por nudo.

**Unidades.** `OpenSees.uni` define por categoría un valor de referencia y sus equivalentes (`LENGTH : m {reference}, 1e+3 mm, 39.37007874015748031496062992126 in, 3.28084 ft`; `FORCE : N {reference}, 1e-3 kN, 0.2248... lbf, 0.0002248... kip`). El bloque `BEGIN SYSTEM(OPENSEES_SI_kN_and_m)` fija el sistema por defecto del problem type: `LENGTH m`, `FORCE kN`, `STRESS kPa`, `MASS ton`, que **no** es `UnitSystem.SI_M_N` (m, N, kg, s, Pa). La conversión es `valor_SI = valor_GiD × f_categoria`, con `f` derivada de la fila del `.uni`; el encabezado del archivo generado publica el sistema usado.

## Procedimiento

1. **Inventariar el problem type**: cargar `OpenSees.prb`, `OpenSees.mat` y `OpenSees.cnd`; indexar `(BOOK, MATERIAL|CONDITION) → campos`, los tipos de widget (`CB`, `UNITS`, `MAT`, `SCALAR`, `TUPLE`) y las reglas `DEPENDENCIES` (`RESTORE`, `HIDE`, `SET`).
2. **Fijar las unidades**: parsear `OpenSees.uni`, resolver el `SYSTEM` activo y construir `categoría → {unidad: factor}`. Sin esto no se convierte nada.
3. **Leer geometría y grupos**: nudos con `*NodesNum`/`*NodesCoord(i)` y su partición `2DOF`/`3DOF`/`6DOF`/`3PDOF`. Asignar `Node.id` propio (no el de GiD) y conservar la correspondencia.
4. **Materiales**: por cada `MATERIAL` del `.mat`, resolver la rama activa (`Formulation`) y mapear a la clase de `core/materials/`; si no existe, emitirlo al informe y no inventar parámetros.
5. **Secciones y elementos**: `Materials/nD/*` y `Sections/*` a `Section`; `Elements/*` a `Element` con su transformación geométrica (por defecto `Linear`; `-GJ` por defecto en secciones de fibra desde 2.9.5).
6. **Restricciones**: expandir `Point/Line/Surface_Restraints` a `Restraint6` por nudo con la partición; detectar y reportar conflictos. `EqualDOF`, `RigidDiaphragm` y `RigidLink` van a `mp_constraints`.
7. **Acciones**: `DeadLoad`/`Loads` a `NodalLoad`/`UniformElementLoad` dentro de un `PlainLoadPattern`; `Mass` a la masa nodal; `PlainPatternTimeseriesPath` y `MultipleSupportExcitationPattern` a `PathTimeSeries` con `UniformExcitationPattern` o `ImposedSupportMotionPattern`.
8. **Análisis**: `Analyze`, `SolutionAlgorithmsDynamic`, `StaticLoadControl`, `StaticDisplacementControl`, `StaticCyclicAnalysis` y `UniformGroundMotionRecord` a `StaticCase`, `ModalCase`, `PushoverCase`, `TransientCase` o `ResponseSpectrumCase` dentro de `Project.analyses`.
9. **Ordenar y validar**: nudos → restricciones → masas → transformaciones geométricas → elementos → series → patrones → análisis; comprobar `(ndm, ndf)` y cobertura de GDL antes de aceptar el modelo.
10. **Emitir el informe** y sólo entonces entregar el `Project` a `services/opensees_runner.py`.

## Implementación en la plataforma

Toda la lectura y la traducción son **Python puro**: viven en `core/`, sin Qt ni solver, y son utilizables desde un script o el CLI.

```python
# src/opensees_studio/core/interop/gid/problem_type.py   (core puro)
class GidProblemType(BaseModel):
    root: Path
    materials: dict[str, GidEntry]      # clave: nombre de MATERIAL en .mat
    conditions: dict[str, GidEntry]     # clave: nombre de CONDITION en .cnd
    systems: dict[str, dict[str, str]]  # BEGIN SYSTEM(name) de .uni

    @classmethod
    def load(cls, root: Path) -> "GidProblemType": ...
    def entry(self, book: str, name: str) -> GidEntry: ...

# core/interop/gid/units.py
def parse_uni(path: Path) -> UnitTable: ...
def factor(table: UnitTable, category: str, src: str, dst: str) -> float: ...

# core/interop/gid/basic.py
def evaluate(template: str, ctx: BasicContext, helpers: Mapping[str, Callable]) -> list[str]: ...

# core/interop/gid/conditions.py
def partition_by_dof(nodes: Mapping[int, GidNode],
                     conditions: Sequence[GidCondition]) -> dict[int, Restraint6]: ...

# core/interop/gid/writers.py
def convert_model(pt: GidProblemType, model: GidModel, *,
                  units: UnitSystem = UnitSystem.SI_M_N) -> tuple[Project, GidImportReport]: ...
```

| Ruta | Contenido | Capa |
|---|---|---|
| `core/interop/gid/` | `.prb/.mat/.cnd/.uni`, Basic, conversión a `Project` | core (sin Qt, sin solver) |
| `core/catalog/generated/` | 58 stubs de material/sección/elemento y 39 de condición, ya presentes | core (sólo esquema) |
| `core/quantities.py` | tipo con unidad para los campos `#UNITS#` (hoy `str` con `# TODO`) | core |
| `services/catalog_emitters.py` | puente catálogo→solver, nombre por nombre (`Elastic` es el único verificado) | services |
| `services/opensees_runner.py` | emisión al solver (`_emit_node`, `_emit_fix`, `_emit_material`, `_emit_section`, `_emit_element`, `_emit_pattern`) | services |
| `services/qt_workers.py` | trabajador de importación fuera del hilo de la GUI | services |
| `opensees_studio/gid_import.py` | CLI: `--problem-type DIR --model FILE --out FILE.osmodel` | raíz |

**Se reimplementa**: el evaluador del subconjunto Basic, la lectura de los cuatro archivos de esquema, la normalización de unidades, la partición de restricciones por DOF y la traducción a entidades de `Project`.

**Se descarta**: la generación de texto Tcl y el dialecto de `OpenSees.tcl` (`InitGIDProject`, `TransformAndClose`, `SetOpenSeesEXE`); los ejecutables `exe/OpenSeesPost.exe`, `TclToGiD.exe`, `RecordViewer.exe`, `CheckForUpdate.exe`; las plantillas binarias `geo/*.geo`; `notepad++/`; y `bas/` como generador de cadenas — se conserva su **semántica**, no su texto. La emisión al solver no se duplica: sigue en `services/opensees_runner.py`.

La importación de un modelo ajeno **nunca** corre en el hilo de la GUI: el diálogo vive en `views/`, el viewmodel lanza un trabajador de `services/qt_workers.py` y publica progreso.

## Datos normativos

No aplica: aquí no hay norma ni edición normativa en juego. El dato real de esta skill es la tabla de unidades, y vive en un archivo versionado del problem type (`OpenSees.uni`, bloques `BEGIN TABLE` y `BEGIN SYSTEM`), no en el código. Los esquemas de material y condición viven en `OpenSees.mat` y `OpenSees.cnd`, su forma intermedia en `tools/gidopensees_import/schemas.json` y el catálogo generado en `src/opensees_studio/core/catalog/generated/` (sólo esquema: no está cableado al `Project` ni al runner). La licencia se registra en la cabecera de cada archivo derivado, según `docs/adr/ADR-0001-gidopensees-schema-import.md`.

## Verificación y casos de prueba

| Caso | Comando o dato | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Contrato de la skill | `python3 skills/scripts/validate_skills.py --quiet` | 0 errores | exacto | `skills/scripts/` |
| Deriva del catálogo | `pytest tests/tools/test_codegen_drift.py -q` | regenera y compara byte a byte | exacto | `tests/tools/` |
| Analizador de esquema | `pytest tests/tools/test_parse_schemas.py -q` | `fixtures/minimal.mat` → `minimal_expected.json` | exacto | `tests/tools/fixtures/` |
| Unidades de longitud | `LENGTH : m {reference}, ..., 39.37007874015748031496062992126 in` | 39.3700787402 in = 1 m | 1e-12 rel | `OpenSees.uni` |
| Unidades de fuerza y masa | `FORCE : N {reference}, 1e-3 kN` y `MASS: kg {reference}, 1e-3 ton` | 1 kN = 1000 N; 1 ton = 1000 kg | 1e-12 rel | `OpenSees.uni` |
| Sistema por defecto | `BEGIN SYSTEM(OPENSEES_SI_kN_and_m)` | `m`, `kN`, `kPa`, `ton` → convertir a `SI_M_N` | exacto | `OpenSees.uni` |
| Nudos | bloque `ops.node(` del `.py` del dataset *Plane Frame* | mismos nudos y coordenadas | 1e-9 m | `wiki/python_tests/datasets/` |
| Restricciones | `ops.fix( 1, 1, 1, 1)` y `ops.fix(101, 1, 1, 1)` | `Node.restraint` de 1 y 101 = `(T,T,T,F,F,F)` con `ndf=3` | exacto | idem |
| Partición de DOF | nudo en dos condiciones con grupos `3DOF` y `6DOF` | un único `Restraint6` + aviso de conflicto | exacto | `bas/Boundary/Restraints.bas` |
| Orden de emisión | `.py` generado | node → fix → mass → geomTransf → element → series → pattern | exacto | dataset citado |
| Paridad Python/Tcl | `python -m unittest wiki.python_tests.test_outputs` en el clon | pasa en los datasets listados | — | `wiki/python_tests/` |
| Capas | `lint-imports` | sin violaciones; `core/` sin Qt ni solver | exacto | `pyproject.toml` |
| Licencia | cabecera de cada archivo derivado | GPL-3.0 atribuida a gidopensees | exacto | `LICENSE`, ADR-0001 |

> ⚠️ VERIFICAR: `wiki/python_tests/test_outputs.py` compara con `filecmp.dircmp(...).common_files` y afirma sobre el **último** archivo comparado; además los datasets tienen nombres asimétricos (`Mode_0.out` frente a `Mode_1.out` y `ModalReport.out`), que no entran en `common_files`. Se comprueba ejecutando el arnés y añadiendo una comparación numérica de los `.out` comunes tras correr ambos modelos: un "pass" no demuestra equivalencia.

## Errores frecuentes y trampas

1. **Unidades.** El `SYSTEM` por defecto es kN/kPa/ton; Studio trabaja en `SI_M_N` (m, N, kg, Pa). Sin conversión: fuerzas 1000×, tensiones 1000×, masas 1000×. `SPECIFIC_WEIGHT` tiene referencia `N/m^3` pero el sistema la fija en `kN/m^3`: categoría y sistema se consultan juntos.
2. **Precisión.** `*format "%6d%12g"` imprime unas 6 cifras significativas: la coordenada del archivo **no** es la del modelo. El float64 del `result_store` no recupera lo truncado en la generación.
3. **Identificadores.** `*NodesNum`, `*MaterialID` y `*ElementID` son etiquetas de GiD; `Entity.id` es `PositiveInt > 0` y `999999` está reservado. Reasignar ids sin mantener la correspondencia rompe las condiciones que referencian nudos.
4. **Restricciones no composables.** Dos `fix` sobre el mismo nudo: gana el último, en silencio. Nudo de intersección de dos líneas con restricciones distintas, y línea de intersección de dos superficies con restricciones distintas, se tratan por separado: la partición por grupos DOF evita el doble `fix`, pero obliga a aceptar **una** partición por nudo.
5. **Orden de comandos.** `fix` y `mass` antes de los elementos; `geomTransf` antes de los elementos que la usan; `timeSeries` antes del `pattern` que la referencia; `wipeAnalysis()` al reconfigurar el análisis.
6. **`(ndm, ndf)`.** Studio admite `(2,2), (2,3), (3,3), (3,6)`; gidopensees maneja además `3PDOF` (30) y condiciones `2DOF` dentro de un modelo 3D. Ese modelo se rechaza o se convierte con aviso, nunca en silencio.
7. **Campos ocultos.** Una rama `DEPENDENCIES` con `HIDE` deja un campo sin valor: no es un cero, y rellenarlo con 0 cambia el material.
8. **Versiones.** `Python.path` del clon apunta a un intérprete concreto (py39); el proyecto exige Python 3.12 y OpenSeesPy 3.8.0.0. El `-GJ` por defecto de las secciones de fibra y el mallado de fibras cambiaron en 2.9.5: un modelo anterior no reproduce su sección. 3.0.0-beta es una beta.
9. **Licencia.** gidopensees es GPL-3.0 y el proyecto AGPL-3.0: todo archivo derivado (stub generado, tabla copiada) lleva cabecera de atribución; el `LICENSE` de gidopensees no se copia al proyecto.
10. **Equivalencia mal medida.** Comparar la salida Tcl con la de Python por nombre de archivo no basta (ver el VERIFICAR anterior); la prueba buena ejecuta ambos modelos y compara desplazamientos y períodos.

## Interfaz de salida

- `GidImportReport` con el conteo por categoría (nudos, materiales, secciones, elementos, restricciones, cargas, casos), la tabla de unidades aplicada con su `SYSTEM`, la lista de objetos de `.mat`/`.cnd` no soportados con su prioridad de `docs/gap-analysis-gidopensees.md`, y los conflictos de restricción con el nudo afectado.
- Cada entidad importada conserva la etiqueta GiD de origen, para volver al modelo y para que la emisión al solver sea rastreable.
- El informe declara la edición `gidopensees 3.0.0-beta`, la ruta del problem type y, si se conoce, la revisión del repositorio de origen.
- Un modelo importado con objetos descartados se marca **preliminar** y no se presenta como equivalente al de GiD.
- El aviso de eje vertical y el de partición de DOF viajan con el resultado hasta el registro del análisis.

## Referencias

1. `OpenSees.prb`, `OpenSees.mat`, `OpenSees.cnd`, `OpenSees.uni`, `OpenSees.tcl`, `Python.path` — raíz del repositorio [gidopensees](https://github.com/rclab-auth/gidopensees).
2. `bas/Model/Nodes.bas`, `bas/Boundary/Restraints.bas`, `bas/Materials/Uniaxial/Steel02Py.bas`, `bas/Actions/*`, `bas/Analysis/*`.
3. `bas/tcl/MultipleDOF.tcl` (`ReturnNodeGroupDOF`), `bas/tcl/FindMaterialNumber.tcl`, `bas/tcl/UsedMaterials.tcl`, `bas/tcl/Regions.tcl`, `bas/tcl/RigidDiaphragm.tcl`.
4. `tcl/Units_Constants_Metric.tcl`, `tcl/GenData.tcl`, `tcl/Geometry_func.tcl`.
5. `wiki/python_tests/test_outputs.py` y `wiki/python_tests/datasets/` — arnés de paridad Python/Tcl y modelos de referencia.
6. `wiki/course/` y `doc/GiD+OpenSees_Interface_User_Manual.pdf` — documentación del problem type.
7. `README.md` de gidopensees, secciones *KNOWN ISSUES* y *VERSION HISTORY*.
8. `LICENSE` de gidopensees (GPL-3.0) y `LICENSE` de OpenSees Studio (AGPL-3.0).
9. `docs/adr/ADR-0001-gidopensees-schema-import.md` y `docs/gap-analysis-gidopensees.md` de este repositorio.
10. `tools/gidopensees_import/{parse_schemas.py,codegen.py,schema_model.py}` y `schemas.json`.

## Registro de verificación

- **Verificado** (2026-02-14, contra el clon en `/tmp/gidopensees`, revisión `74809b8`): los literales de `bas/Model/Nodes.bas`, `bas/Materials/Uniaxial/Steel02Py.bas` y `bas/Boundary/Restraints.bas`; la partición por `ReturnNodeGroupDOF` y los grupos `2DOF/3DOF/6DOF/3PDOF`; las filas `LENGTH`/`FORCE`/`MASS` de `OpenSees.uni` y el bloque `BEGIN SYSTEM(OPENSEES_SI_kN_and_m)`; el orden de emisión y las líneas `ops.model`/`ops.node`/`ops.fix`/`ops.mass`/`ops.geomTransf`/`ops.element`/`ops.pattern` del modelo generado del dataset *Plane Frame - Static and Modal Analysis*; la estructura de `wiki/python_tests/test_outputs.py`; los tamaños de `OpenSees.prb` (24040 B), `OpenSees.mat` (132581 B), `OpenSees.cnd` (38782 B), `OpenSees.uni` (7666 B), `OpenSees.tcl` (50246 B) y `LICENSE` (32471 B); y la portada de `README.md` (equipo AUTh, 3.0.0-beta del 30/11/2023, problemas conocidos).
- **Verificado en el proyecto propio**: `docs/gap-analysis-gidopensees.md` (columna «In Studio?» y brechas P1/P2 que cita el informe de importación), `docs/adr/ADR-0001-gidopensees-schema-import.md` (licencia y alcance de esquema), el árbol `src/opensees_studio/core/catalog/generated/` y las entidades `Project`, `Node`, `Restraint6`, `Entity.id`, `UnitSystem`, `AnalysisCase` y `services/result_store.py`.
- **Pendiente**: el formato del `.gid` y el modo batch de GiD; la semántica completa de `DEPENDENCIES`; el comportamiento borde de los ayudantes de `bas/tcl/`; y si algún nombre del catálogo generado llega al runtime aparte de `Elastic`. Lo cierra el mantenedor al importar el primer modelo real de `wiki/examples/`.
