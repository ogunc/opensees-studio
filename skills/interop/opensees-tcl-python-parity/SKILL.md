---
name: opensees-tcl-python-parity
description: >-
  Define y verifica la equivalencia entre la salida Tcl y la salida OpenSeesPy de
  un modelo estructural: tabla de correspondencia comando a comando con el prefijo
  ops., conversión de tipos desde las cadenas de Tcl, orden canónico de los
  comandos de modelado y comparación textual y numérica con tolerancia. Úsala al
  importar un script Tcl de OpenSees o de gidopensees, al duplicar un escritor
  <Objeto>.bas y <Objeto>Py.bas, al portar opstool.pre.tcl2py, al reproducir el
  arnés wiki/python_tests/test_outputs.py, o cuando dos salidas del mismo modelo
  difieren en un dígito, en el signo de un modo propio o en una restricción.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "gidopensees 3.0.0-beta y opstool 1.0.26"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, qa]
---

# Paridad Tcl ↔ OpenSeesPy

## Cuándo usar esta skill

- Hay que importar un `.tcl` de OpenSees (o de gidopensees) y producir el script OpenSeesPy equivalente sin cambiar la física del modelo.
- Se implementa o revisa un par de escritores `<Objeto>.bas` / `<Objeto>Py.bas`: toda diferencia entre ellos es una divergencia silenciosa.
- Se porta la lógica de `opstool.pre.tcl2py` (`_type_convert`, `_process_args`, `_get_cmds`) a un conversor propio.
- Se replica el arnés `wiki/python_tests/test_outputs.py` de gidopensees, que compara "Python outputs" contra "Tcl outputs" con `unittest` y `filecmp`.
- Dos corridas del mismo modelo, una por cada vía de emisión, dan números distintos.
- **No** usar para el árbol de datos de GiD (`.prb`, `.mat`, `.cnd`), para post-proceso ni para malla de secciones: eso es `platform/platform-architecture-and-services`.

## Alcance y límites

Cubre la equivalencia entre dos formas de escribir el mismo modelo OpenSees: léxica (tipos y formato), sintáctica (bloques y banderas), semántica (orden de comandos) y numérica (resultados con tolerancia), más la trazabilidad de versiones y unidades de la conversión.

Queda fuera la formulación de elementos finitos, la interfaz gráfica, el esquema de GiD y la visualización de resultados. La skill no decide cuál de las dos salidas es correcta: decide si son la misma.

Supuestos: modelo OpenSees clásico (`model basic`), Tcl sin expansión de macros propias de GiD, un archivo por modelo, e intérprete fijado por el proyecto (OpenSeesPy 3.8.0.0).

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| `.tcl` de origen o par `.bas`/`Py.bas` | no se convierte: un `.bas` de GiD no es Tcl, exige expandir antes el lenguaje Basic |
| `ndm`/`ndf`, que fija `model basic` | se leen del archivo; dos `model` en el mismo script son un error |
| Sistema de unidades del modelo | **error**; se lee de `OpenSees.uni` o del campo de unidades del proyecto, nunca se asume SI |
| Versión del intérprete y de OpenSeesPy | se registra en el informe; sin ella la paridad no es reproducible |
| Tabla de tags (nudos, materiales, secciones) | se deriva del flujo de comandos; en el proyecto los tags son `PositiveInt` y `999999` es centinela en vuelo |
| Tolerancias `rtol` y `atol` | las de esta skill, declaradas en el informe |

## Fundamento y formulación

Tres niveles de paridad, en orden creciente de coste y de valor:

1. **Textual**: mismo texto salvo normalización (espacios, `\r\n`, línea final). Es el criterio de gidopensees, `filecmp` sobre los archivos homónimos de "Python outputs" y "Tcl outputs".
2. **Semántico**: misma secuencia de `(etapa, nombre, tupla de argumentos ya tipados)`. Es el criterio robusto: `1e9` y `1000000000.0` son el mismo número; `1` y `"1"` no son el mismo tipo.
3. **Numérico**: mismos resultados de análisis. Con referencia \(x_r\) y candidato \(x_c\):

   \[
   |x_c - x_r| \le \mathrm{atol} + \mathrm{rtol}\,|x_r|
   \]

   con `rtol = 1e-6` y `atol = 1e-9` en las magnitudes del proyecto (SI coherente: m, N, kg, s, Pa). Un autovector tiene signo arbitrario: se compara tras `normalize_mode_sign` (`tie = 1e-9`, gana el GDL de índice menor) con MAC \(\ge 0.999\), y los autovalores repetidos exigen antes `orthogonalize_degenerate_modes`.

**Tabla de correspondencia.** El nombre del comando no cambia; cambia el contenedor, el prefijo `ops.` y los tipos. Los literales son el resultado de la coerción, no el texto Tcl.

| Tcl | OpenSeesPy (`ops.`) |
|---|---|
| `model basic -ndm 2 -ndf 3` | `ops.model("basic", "-ndm", 2, "-ndf", 3)` |
| `node 1 0.0 0.0` | `ops.node(1, 0.0, 0.0)` |
| `fix 1 1 1 0` | `ops.fix(1, 1, 1, 0)` |
| `mass 1 1.0 1.0 0.0` | `ops.mass(1, 1.0, 1.0, 0.0)` |
| `uniaxialMaterial Steel02 1 500e6 200e9 0.02 18 ...` | `ops.uniaxialMaterial("Steel02", 1, 500e6, 200e9, 0.02, 18, ...)` |
| `nDMaterial ElasticIsotropic 1 200e9 0.3 7850` | `ops.nDMaterial("ElasticIsotropic", 1, 200e9, 0.3, 7850)` |
| `section Elastic 1 200e9 0.01 1e-4` | `ops.section("Elastic", 1, 200e9, 0.01, 1e-4)` |
| `section Fiber 1 -GJ 1e9 { patch rect ... }` | `ops.section("Fiber", 1, "-GJ", 1e9)` + `ops.patch(...)` / `ops.fiber(...)` / `ops.layer(...)` |
| `element elasticBeamColumn 1 1 2 0.01 200e9 1e-4 1` | `ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200e9, 1e-4, 1)` |
| `geomTransf Linear 1 0 0 1` | `ops.geomTransf("Linear", 1, 0, 0, 1)` |
| `pattern Plain 1 1` | `ops.pattern("Plain", 1, 1)` |
| `timeSeries Linear 1` | `ops.timeSeries("Linear", 1)` |
| `load 1 100.0 0.0 0.0` | `ops.load(1, 100.0, 0.0, 0.0)` |
| `sp 1 1 0.05` | `ops.sp(1, 1, 0.05)` |
| `equalDOF 1 2 1 2` | `ops.equalDOF(1, 2, 1, 2)` |
| `rigidDiaphragm 3 1 2` | `ops.rigidDiaphragm(3, 1, 2)` |
| `rigidLink beam 1 2` | `ops.rigidLink("beam", 1, 2)` |
| `recorder Node -file d.out -time -node 2 -dof 1 disp` | `ops.recorder("Node", "-file", "d.out", "-time", "-node", 2, "-dof", 1, "disp")` |
| `constraints Transformation` | `ops.constraints("Transformation")` |
| `numberer RCM` | `ops.numberer("RCM")` |
| `system BandGeneral` | `ops.system("BandGeneral")` |
| `test NormDispIncr 1e-8 10` | `ops.test("NormDispIncr", 1e-8, 10)` |
| `algorithm Newton` | `ops.algorithm("Newton")` |
| `integrator LoadControl 0.1` | `ops.integrator("LoadControl", 0.1)` |
| `analysis Static` | `ops.analysis("Static")` |
| `analyze 10` | `ops.analyze(10)` |
| `eigen 3` | `ops.eigen(3)` |

**Tipos.** En Tcl todo argumento es cadena y el tipo correcto es una propiedad de la posición. El primer argumento de `node`, `fix`, `mass`, `uniaxialMaterial`, `nDMaterial`, `section`, `element`, `pattern`, `timeSeries`, `recorder`, `load`, `sp`, `equalDOF`, `rigidLink` y `geomTransf` es **tag entero**; el tipo (`"Steel02"`, `"basic"`, `"Linear"`, `"Fiber"`) y toda bandera (`-orient`, `-GJ`, `-transf`, `-mat`, `-dir`, `-file`, `-dof`, `-ndm`, `-ndf`, `-time`) son **cadena**; el resto de los valores numéricos son **flotante** aunque su forma textual sea entera (`18` es `R0` en `Steel02`, no un tag). Los indicadores `0/1` de `fix` son enteros.

**Orden canónico.** OpenSees resuelve tags y referencias en el momento de la llamada, así que reordenar comandos cambia el modelo:

```text
model → node → fix|mass|equalDOF|rigidDiaphragm|rigidLink → uniaxialMaterial
      → nDMaterial → geomTransf → section (+patch|fiber|layer) → element
      → timeSeries → pattern → load|sp → recorder
      → constraints → numberer → system → test → algorithm → integrator
      → analysis → analyze → eigen
```

Los nudos preceden a toda restricción; los materiales, a las secciones y elementos que los citan; `geomTransf`, al elemento que lo referencia en `-transf`; `timeSeries`, a `pattern`; `pattern`, a `load`/`sp`; los `recorder`, a `analyze`; el bloque de sistema, inmediatamente a `analysis`/`analyze`; `eigen`, al modelo completo y restringido.

**Bloques y variables.** Un bloque Tcl entre llaves se convierte en llamadas secuenciales al mismo nivel, tal como emite `services/opensees_runner.py`. gidopensees 3.0.0-beta emite además "material properties as variables in Python-based models": el script Python declara variables que el Tcl no tiene, así que la comparación línea a línea falla por diseño y hay que comparar el flujo semántico ya evaluado.

## Procedimiento

1. **Fijar la referencia**: copiar el `.tcl` y su salida Python publicada (en gidopensees, la pareja homónima de cada dataset de `wiki/examples/`); registrar SHA-256 de ambos, versión de OpenSeesPy y unidades.
2. **Tokenizar** respetando llaves anidadas, corchetes `[...]`, comentarios `#` y continuación de línea `\` (los escritores de gidopensees usan `*\`).
3. **Clasificar el tipo** de cada argumento con la regla de posición y bandera. Un token no clasificable es un error, no una cadena por defecto.
4. **Ordenar por etapa canónica**, con orden estable dentro de la etapa: nunca se reordena dentro de `element` ni de `pattern`. Si una referencia aparece antes de su definición, se reordena y se anota; si no se puede, se falla.
5. **Emitir** `ops.<comando>(...)`, con comillas dobles en las cadenas y sin alterar la forma numérica del token.
6. **Comparar semánticamente** las dos secuencias y listar todas las diferencias; ninguna se ignora.
7. **Comparar textualmente** solo si el paso 6 da cero diferencias y el formato está normalizado (criterio `filecmp` de gidopensees).
8. **Ejecutar** ambas versiones contra el mismo intérprete y comparar resultados con `rtol`/`atol`; los modos propios, tras normalizar signo y con MAC.
9. **Registrar** el informe de paridad y adjuntarlo al resultado: no se publica una conversión con diferencias semánticas abiertas.
10. **Añadir el caso al arnés** para que el dataset no vuelva a divergir.

## Implementación en la plataforma

Se reimplementa: tokenizador Tcl, tabla de correspondencia, orden canónico, coerción de tipos, comparador semántico y comparador numérico sobre el almacén de resultados. Se descarta: el problem type de GiD (`.prb`, `.mat`, `.cnd`, `.uni` y los `.bas`), los ejecutables `OpenSeesPost.exe` y `TclToGiD.exe`, el ODB zarr/netcdf4 de opstool con su `dtype` float32 por defecto, sus apps NiceGUI y el extra `[pre]` de malla de secciones.

| Ruta propuesta | Capa | Contenido |
|---|---|---|
| `core/interop/tcl_commands.py` | `core/` | tabla de correspondencia, `CANONICAL_ORDER`, coerción de tipos |
| `core/interop/tcl2py.py` | `core/` | tokenizador y conversión a texto OpenSeesPy |
| `services/tcl_parity.py` | `services/` | comparación semántica y numérica, informe |
| `services/result_store.py` | `services/` (existe) | referencia float64 HDF5 + `manifest.json` |
| `tests/unit/interop/` | — | tokenización, tipos y orden canónico |
| `tests/integration/test_tcl_python_parity.py` | — | paridad contra datasets reales, con tolerancia |

```python
# src/opensees_studio/core/interop/tcl_commands.py   (core puro: sin Qt, sin openseespy)
CANONICAL_ORDER: tuple[str, ...]

def stage(command: str) -> int:
    """Índice de etapa canónica; CommandOrderError si el comando no está en la tabla."""

def coerce(token: str, *, name: str, index: int, flag: str | None) -> str:
    """Literal Python del token Tcl: '1', '0.02' o '\"Steel02\"'."""

def python_call(name: str, args: list[str]) -> str:
    """'ops.node(1, 0.0, 0.0)'; no interpreta bloques."""

# src/opensees_studio/core/interop/tcl2py.py
@dataclass(frozen=True)
class Command:
    line: int
    name: str
    args: tuple[str, ...]
    raw: str

def tokenize(text: str) -> list[Command]: ...
def convert(text: str, *, header: bool = True) -> str: ...
def unconverted(text: str) -> list[Command]:
    """Comandos sin correspondencia conocida: se reportan, no se adivinan."""

# src/opensees_studio/services/tcl_parity.py   (puede importar el solver)
@dataclass(frozen=True)
class ParityReport:
    lexical: bool
    semantic: bool
    numeric: dict[str, float]      # campo de resultado -> error relativo máximo
    failures: tuple[str, ...]
    provenance: dict[str, str]     # hashes, versiones, unidades, tolerancias

def compare_streams(a: Sequence[Command], b: Sequence[Command]) -> ParityReport: ...
def compare_sources(tcl: Path, py: Path) -> ParityReport: ...
def compare_results(ref: Mapping[str, np.ndarray], cand: Mapping[str, np.ndarray],
                    *, rtol: float = 1e-6, atol: float = 1e-9) -> ParityReport: ...
def run_in_child(script: Path, out_dir: Path) -> Path:
    """Ejecuta el script en un proceso hijo con child_cli.analysis_cli_command()."""
```

Reglas de capa:

- `core/interop/` es puro: convierte texto y no importa Qt ni OpenSeesPy; se prueba sin solver.
- `services/tcl_parity.py` es el único que puede importar OpenSeesPy, y solo para ejecutar. La ejecución **nunca** ocurre en el hilo de la GUI: se lanza con el constructor único de argv (`child_cli.analysis_cli_command()`) y el hijo emite **una línea JSON por evento** (`log`, `progress`, `case_started`, `case_finished`, `error`), con `stdout` reservado al protocolo.
- La comparación numérica se hace sobre el almacén float64 (`result_store`), no sobre una copia float32.
- `services/opensees_script.py::export_script` usa `_CallRecorder` para grabar la secuencia exacta que `OpenSeesRunner.build` envía al solver: es la referencia canónica de la emisión del proyecto y la que debe reproducir el conversor.
- Los emisores ya cableados (`services/material_emitters.py`, `services/catalog_emitters.py`, con `ops.uniaxialMaterial(command, material.id, *args)`) fijan el nombre exacto del comando; el conversor no inventa sinónimos.

## Datos normativos

No aplica: no hay norma de diseño en juego. Los datos de referencia viven en la tabla de unidades `OpenSees.uni` del problem type (BEGIN TABLE con LENGTH/AREA/FORCE/STRESS/MASS/DENSITY/SPECIFIC_WEIGHT/TIME/FREQUENCY/ACCELERATION y factores como `1e+3 mm`), en el ayudante `tcl/Units_Constants_Metric.tcl` y en el sistema de unidades declarado en el modelo. Ningún factor de conversión se escribe dentro del código: se lee de esos archivos versionados.

## Verificación y casos de prueba

| Caso | Comando, dato o condición | Resultado esperado |
|---|---|---|
| Deriva del catálogo | `pytest tests/tools/test_codegen_drift.py -q` | `core/catalog/generated/` regenerado idéntico byte a byte |
| Tipos de tag | convertir `node 1 0.0 0.0` | `ops.node(1, 0.0, 0.0)`: tag entero, coordenadas flotantes |
| Tipos de bandera | `geomTransf Linear 1 0 0 1` y `section Fiber 1 -GJ 1e9` | `"-GJ"` cadena; `1e9` flotante y con su forma textual |
| Material contra tag | `uniaxialMaterial Steel02 1 ... 18 0.925 0.15` | `18` y `0.925` flotantes; `1` entero; `"Steel02"` cadena |
| Bloque de sección | `section Fiber 1 -GJ 1e9 { patch rect ... fiber ... }` | `ops.section(...)` y luego `ops.patch(...)`/`ops.fiber(...)` al mismo nivel |
| Orden canónico | `element` antes de su `uniaxialMaterial` | reordena por etapa; si no puede, error accionable |
| Restricciones superpuestas | dos `fix` sobre el mismo nudo (intersección de líneas, README de gidopensees) | el informe lista el nudo; no se combinan ni se descartan comandos |
| Paridad textual | datasets "Plane Frame - Static and Modal Analysis" y "Masonry Structure with Concrete Slab" | `filecmp.cmp(..., shallow=False)` sobre "Python outputs" vs "Tcl outputs" |
| Paridad semántica | `compare_streams` sobre el mismo modelo | cero diferencias de `(etapa, nombre, argumentos tipados)` |
| Paridad numérica | desplazamientos y reacciones vía `compare_results` | `rtol = 1e-6`, `atol = 1e-9` |
| Modos propios | caso con `eigen` en los dos scripts | períodos a 0.5 % relativo; MAC \(\ge 0.999\) tras `normalize_mode_sign` |
| Precisión | resultados leídos con `services/result_store.py` | float64 en HDF5; ninguna ruta intermedia a float32 |
| Unidades | modelo con `OpenSees.uni` en kip/in contra SI | sin conversión silenciosa: el informe declara la unidad de cada lado |
| Versión | OpenSeesPy distinto del fijado (3.8.0.0) | paridad marcada como no reproducible |

## Errores frecuentes y trampas

1. **Unidades.** Un lado en kip/in y otro en N/m da paridad textual perfecta y resultados con factor 1e3/1e6. `OpenSees.uni` no cubre todas las magnitudes y ningún factor debe quedar incrustado en el código.
2. **Cadenas que parecen números.** Convertir todo a `float` rompe los tags (`node 1` deja de ser entero) y banderas como `-orient 0 0 1`; convertir todo a `str` produce `ops.node("1", "0.0")`.
3. **Orden de comandos.** Mover `geomTransf` después de los elementos, o los `recorder` después de `analyze`, cambia el modelo o no graba nada.
4. **Restricciones que OpenSees no combina.** El README de gidopensees lo declara: los nudos de intersección de dos líneas con restricciones distintas, y las líneas de intersección de dos superficies con restricciones distintas, se tratan por separado. Un conversor que "fusiona" `fix` inventa un modelo.
5. **Divergencia entre los dos escritores.** gidopensees mantiene cada objeto por duplicado (`<Objeto>.bas` y `<Objeto>Py.bas`): corregir uno y no el otro es el fallo más frecuente del proyecto.
6. **Variables de material.** gidopensees 3.0.0-beta emite propiedades como variables en Python: comparar texto contra texto da falsos negativos.
7. **Identificadores.** Tags reutilizados o negativos, `999999` como centinela en vuelo, y dos materiales con el mismo tag en ramas `*if` distintas que solo se resuelven al evaluar.
8. **Licencias.** gidopensees es GPL-3.0 y opstool es GPL-3.0; el proyecto es AGPL-3.0. Reutilizar sus esquemas está registrado en `core/catalog/generated/__init__.py`; copiar código de opstool exige conservar los avisos GPL, y "OPSTOOL™" es una marca que no se reutiliza.
9. **Precisión.** El `dtype` por defecto de opstool es int32/float32; el proyecto escribe float64. Una comparación sobre datos float32 no puede exigir `atol = 1e-9`.
10. **Determinismo de autovalores.** Solo la **primera** llamada ARPACK de un proceso es reproducible: la segunda invierte signos y rota pares repetidos. Cada caso con autovalores corre en su propio proceso hijo.
11. **Formato numérico y comillas.** `1e9` contra `1000000000.0`, `\r\n`, comentarios y línea final hacen fallar `filecmp` sin diferencia real: por eso el criterio primario es semántico.
12. **Versiones.** opstool declara Python `>=3.10,<3.13`; el proyecto fija 3.12 con OpenSeesPy 3.8.0.0. Un `.py` generado contra otra versión puede usar comandos que el intérprete fijado no tiene.

## Interfaz de salida

- `ParityReport` serializable como una línea JSON más del protocolo del hijo (`{"type": "parity", ...}`), separada de la salida nativa del solver.
- Campos mínimos: `lexical`, `semantic`, `numeric` (error relativo máximo por campo), `failures` (comandos sin correspondencia, nudos con restricciones superpuestas, referencias reordenadas) y `provenance` (SHA-256 del `.tcl` y del `.py`, versión de OpenSeesPy, unidades, `rtol`, `atol`).
- Códigos de salida del hijo, coherentes con el proyecto: `0` todas las comparaciones corrieron (una diferencia de paridad es un resultado, no un fallo de ejecución), `2` error de análisis con línea `error`, `3` entrada inválida; otro código indica que el hijo murió.
- Avisos de unidad no declarada, comando sin correspondencia o cobertura de datasets incompleta viajan con el resultado hasta el informe.
- El `.py` generado lleva cabecera con procedencia: archivo de origen, hash, versión, herramientas y aviso de licencia.

## Referencias

1. gidopensees, <https://github.com/rclab-auth/gidopensees>, v3.0.0-beta (30/11/2023): `bas/Model/Nodes.bas`, `bas/Model/NodesPy.bas`, `bas/Materials/Uniaxial/Steel02.bas`, `bas/Materials/Uniaxial/Steel02Py.bas`, `bas/Sections/Fiber.bas`, `bas/Boundary/`, `bas/Analysis/`.
2. gidopensees: `wiki/python_tests/test_outputs.py` y `wiki/python_tests/datasets/` (arnés de paridad con `unittest` y `filecmp`); `wiki/examples/*.zip`.
3. gidopensees: `OpenSees.uni`, `tcl/Units_Constants_Metric.tcl`, `tcl/GenData.tcl`, `tcl/Geometry_func.tcl`, `bas/tcl/*.tcl`, `README.md`, `LICENSE` (GPL-3.0).
4. opstool 1.0.26, <https://github.com/yexiang92/opstool>: `opstool/pre/io` (`tcl2py`, `_type_convert`, `_process_args`, `_get_cmds`); `opstool/post` (`CreateODB`, `get_nodal_responses`, `get_element_responses`, `reset_unit_system`, `update_unit_system`); `opstool/utils` (`CONFIGS`, `OPS_ELE_CLASSTAG2TYPE`); `LICENCE.txt` (GPL-3.0).
5. Proyecto propio: `src/opensees_studio/services/opensees_runner.py`, `opensees_script.py`, `material_emitters.py`, `catalog_emitters.py`, `result_store.py`, `src/opensees_studio/run.py`, `child_cli.py`.
6. Proyecto propio: `docs/gap-analysis-gidopensees.md`, `docs/adr/ADR-0001-gidopensees-schema-import.md`, `tools/gidopensees_import/`, `tests/tools/test_codegen_drift.py`, `CLAUDE.md`, `skills/platform/platform-architecture-and-services/SKILL.md`.

## Registro de verificación

- **Verificado** contra los hechos y el repositorio: la duplicación `<Objeto>.bas`/`<Objeto>Py.bas`; el arnés `test_outputs.py` con `unittest` y `filecmp`; la existencia de `opstool.pre.tcl2py` con `_type_convert`, `_process_args` y `_get_cmds`; la tabla `OpenSees.uni`; el aviso de restricciones no combinables; las licencias GPL-3.0 y AGPL-3.0. Del proyecto: `OpenSeesRunner.build`, `export_script`, `_CallRecorder`, `catalog_emitters`, `result_store` float64 con `manifest.json`, el protocolo de una línea JSON por evento y `child_cli.analysis_cli_command()`.
- **Pendiente**:
  > ⚠️ VERIFICAR: el nombre exacto del archivo de `tcl2py` dentro de `opstool/pre/io` y las reglas concretas de `_type_convert`. Se comprueba leyendo `opstool/pre/io/` en la copia clonada (v1.0.26) y ejecutando `tcl2py` sobre un `.tcl` con tags, banderas y exponentes.
  > ⚠️ VERIFICAR: la cobertura real de la tabla de correspondencia frente a los escritores de gidopensees. Se comprueba recorriendo `bas/**/*.bas` y `bas/**/*Py.bas`, extrayendo cada comando emitido y contrastándolo con `core/interop/tcl_commands.py`.
  > ⚠️ VERIFICAR: si `OpenSees.uni` cubre STRESS/MASS/DENSITY con factores suficientes para un modelo completo. Se comprueba leyendo su BEGIN TABLE y comparándolo con los campos `#UNITS#` de `core/catalog/generated/`, hoy `str` con un TODO de tipo con unidad.
  > ⚠️ VERIFICAR: que todos los datasets de `wiki/python_tests/datasets/` traigan a la vez "Tcl outputs" y "Python outputs". Se comprueba listando esa carpeta y los `.zip` de `wiki/examples/`.
