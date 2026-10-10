---
name: gid-problem-type-schemas
description: >-
  Explica la anatomía del problem type de GiD de gidopensees (OpenSees.prb,
  OpenSees.mat, OpenSees.cnd, OpenSees.uni, OpenSees.tcl) y la gramática de sus
  BOOK (BOOK, MATERIAL, CONDITION, TITLE, QUESTION, VALUE, STATE, DEPENDENCIES,
  TKWIDGET, anotaciones #UNITS#), junto con el pipeline ya existente en el
  repositorio: parse_schemas.py → schemas.json → codegen.py →
  core/catalog/generated/, con su prueba de deriva byte a byte. Úsala al regenerar
  el catálogo, cuando falle tests/tools/test_codegen_drift.py, al cablear un
  material del catálogo al runner (CatalogMaterial, services/catalog_emitters.py),
  al decidir la unidad de un campo #UNITS# o al interpretar un BOOK del .mat o del
  .cnd.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "gidopensees 3.0.0-beta"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, data]
---

# Problem type de GiD: esquema de datos de gidopensees

## Cuándo usar esta skill

- Hay que regenerar el catálogo o entender qué produce cada paso (`parse_schemas.py` → `schemas.json` → `codegen.py` → `core/catalog/generated/`).
- Falla `tests/tools/test_codegen_drift.py`: el árbol comprometido no coincide byte a byte con una corrida fresca del generador.
- Surge una pregunta sobre un campo: de qué BOOK viene, qué `widget_type` tiene, por qué su tipo Python es `str`, qué unidad lleva su valor por defecto.
- Hay que **cablear** un material para que el runner lo emita (`CatalogMaterial`, `services/catalog_emitters.py`, `wired_names()`).
- Se interpreta un `.mat`/`.cnd` crudo (BOOK, DEPENDENCIES, TKWIDGET, `#UNITS#`).

**No usar** para la generación de código Tcl/Python de gidopensees (`bas/*.bas`, `bas/*Py.bas`, `tcl/*.tcl`), para ejecutar análisis ni para el post-proceso: el pipeline cubre **solo esquema** (ADR-0001 §1). La emisión al solver es de `services/opensees_runner.py`; el post-proceso ODB de contenedores `xarray`/`zarr`/`netcdf4` es de otra skill.

## Alcance y límites

Cubre el inventario de la raíz del problem type, la gramática de los BOOK tal como la consume `parse_schemas.py`, su IR en `schema_model.py`, el pipeline build-time y su contrato de determinismo, la brecha declarada de `#UNITS#` (ADR-0001 §2.7) con la tabla `OpenSees.uni`, y el puente catálogo → `Project` → runner.

No cubre: instalar GiD, los binarios `exe/` (`OpenSeesPost.exe`, `TclToGiD.exe`, `RecordViewer.exe`), las plantillas `geo/`, la ejecución de `TKWIDGET` (solo se conserva su nombre como metadato) ni la emisión OpenSeesPy de cada tipo. Supuestos: el repositorio gidopensees está clonado en local, GiD no está instalado, y `schemas.json` y `generated/` están comprometidos en git (ADR-0001 §2.2).

## Entradas y supuestos

| Entrada | Origen | Si falta |
|---|---|---|
| `OpenSees.mat` (132 KB), `OpenSees.cnd` (39 KB) | gidopensees 3.0.0-beta | no se regenera: `parse_schemas.py` sale con `error: file not found` |
| `tools/gidopensees_import/schemas.json` | salida comprometida del parser | única fuente de `codegen.py`; sin él no hay generación reproducible |
| `core/catalog/generated/` | salida comprometida del generador | no hay `CATALOG` y `CatalogMaterial` rechaza todo `gid_name` |
| `OpenSees.uni` (7,7 KB) | gidopensees | sin conversión: el catálogo queda en texto con unidad |
| `UnitSystem` del proyecto | `.osmodel` (`core/units.py`) | obligatorio: los parámetros se guardan en el sistema del proyecto |
| Etiqueta de gidopensees | `README` (3.0.0-beta, 30/11/2023) | no se puede fechar el esquema; registrarla antes de regenerar |

## Fundamento y formulación

### 1. Los archivos de la raíz

| Archivo | Papel |
|---|---|
| `OpenSees.prb` (24 KB) | «problem data»: árbol `BOOK`/`TITLE`/`QUESTION`/`VALUE`/`STATE` que GiD muestra |
| `OpenSees.mat` (132 KB) | materiales: 14 BOOK, 58 MATERIAL (`Standard_Uniaxial_Materials`, `Uniaxial_Steel_Materials`, `Uniaxial_Concrete_Materials`, `Combined_Materials`, `User_Materials`, `Multidimensional_(nD)_Materials`, `Section_Force-Deformation`, `Records`, `Beam-Column_Elements`, `Truss_Elements`, `Surface_Elements`, `Solid_Elements`, `AutoZL`, `AutoEDOF`) |
| `OpenSees.cnd` (39 KB) | condiciones: 6 BOOK, 39 CONDITION (`Restraints`, `Loads`, `Constraints`, `Mass/Damping`, `ZeroLength_Elements`, `Old_Conditions`) |
| `OpenSees.uni` (7,7 KB) | unidades: `BEGIN TABLE` con `LENGTH : m {reference}, 1e+3 mm, 39.37… in, 3.28084 ft`; también `AREA`, `FORCE` (N, kN, MN, lbf, kip), `STRESS`, `MASS`, `DENSITY`, `SPECIFIC_WEIGHT`, `TIME`, `FREQUENCY`, `ACCELERATION` |
| `OpenSees.tcl` (50 KB) | macros Tcl del espacio `OpenSees`: `InitGIDProject`, `ChangeData`, `GetProblemTypePath`, `SetProjectNameAndPath`, `SetOpenSeesEXE`/`GetOpenSeesEXE`, `SetPythonPath`/`GetPythonPath`, `IsPython`, `TransformZeroLengthData::reset/read`, ganchos `LoadGIDProject`, `SaveGIDProject`, `BeforeInitGIDPostProcess` |
| `OpenSees.sim`, `OpenSees.xml` (841 B) | configuración del problem type |
| `Python.path` (45 B) | intérprete de Python que usa la salida `*Py.bas` |
| `bas/`, `tcl/`, `geo/`, `post/`, `exe/`, `wiki/`, `doc/` | escritores, ayudantes Tcl, geometría, post-proceso, binarios, documentación |

Solo `.mat` y `.cnd` entran hoy al pipeline: `parse_schemas.py` no lee `.uni`, `.prb`, `.tcl`, `.sim`, `.xml` ni `Python.path`.

> ⚠️ VERIFICAR: la semántica de las líneas de `OpenSees.uni` (si el factor es «unidades por unidad de referencia» o su inverso) y los factores de `AREA`, `STRESS`, `MASS`, `TIME` y `ACCELERATION`. Se comprueba leyendo `OpenSees.uni` en el clon y contrastando un caso conocido (1 m = 1e+3 mm = 3.28084 ft). Mientras no se verifique, ninguna conversión se codifica en el motor.

### 2. Gramática de los BOOK

```
BOOK: <Nombre>                    # agrupa entradas; abre un BookSpec
MATERIAL: <Nombre>                # o CONDITION: <Nombre> en el .cnd
TITLE: <título de sección>        # contexto de los campos siguientes
QUESTION: <Campo>#CB#(a,b,c)      # widget: CB, UNITS, MAT, TUPLE o escalar
VALUE: <valor> #WIDTH#(12)        # valor por defecto y ancho opcional
HELP: <ayuda>   IMAGE: <icono>    STATE: HIDDEN | DISABLED
TKWIDGET: <Hook>
DEPENDENCIES: (trigger, ACCION, campo, destino), …
END MATERIAL                      # o END CONDITION
```

`parse_schemas.py` normaliza esto a `schema_model.py`: `CatalogSpec{mat_books, cnd_books}` → `BookSpec{name, source, entries}` → `EntrySpec{name, book, source_type, fields, condtype, condmeshtype}` → `FieldSpec{name, widget_type, options, default, width_hint, help_text, image, state, tkwidgets, dependencies, section_title}`. `widget_type` es `Literal["CB", "UNITS", "MAT", "SCALAR", "TUPLE"]` (una `QUESTION` sin marca ni paréntesis cae a `SCALAR`). La visibilidad se normaliza a `DependencyRule{trigger, actions}` con `DependencyAction{action: Literal["RESTORE", "HIDE", "SET"], field, target}`, donde `target` es `#CURRENT#` o un literal.

Conteos del `schemas.json` comprometido (`sha256:42032585df71`): 410 `CB`, 381 `UNITS`, 308 `SCALAR`, 72 `MAT`, 23 `TUPLE`; 113 campos con `DEPENDENCIES`, 270 con `TKWIDGET`; 104 `STATE: HIDDEN` y 25 `DISABLED`. Un `TKWIDGET` es un gancho de la interfaz de GiD (autocompletado `SteelUniaxMaterial::GenerateValues`, wiki `TK_MaterialWikiInfo`, probador `TK_MaterialTester`, barra de estado `TK_UpdateInfoBar`): se conserva como metadato, no se ejecuta.

### 3. `#UNITS#` y la unidad del proyecto

Un campo `UNITS` lleva número y unidad en un mismo texto (`'500 MPa'`, `'4000 kN/m'`, `'200 GPa'`, `'-20MPa'`). Con \(f_u\) = unidades \(u\) por unidad de referencia del `.uni`: \(v_{\text{ref}} = v_u / f_u\), y \(f_{\text{mm}} = 10^{3}\) mm/m.

La regla de la plataforma es la contraria a la de GiD: OpenSees es agnóstico de unidades y **el proyecto no convierte** (`core/units.py`). Los parámetros de `CatalogMaterial` se guardan en el `UnitSystem` del proyecto (`SI_M_N`, `SI_MM_N`, `US_FT_KIP`, `US_IN_KIP`); el texto del esquema solo **siembra** un valor por defecto en la interfaz. `core/quantities.py` lee el número y descarta la unidad (`parse_quantity("4000 kN/m") == 4000.0`) y nunca reescribe un valor tecleado. Por eso el catálogo no puede mezclar unidades de GiD con las del proyecto: la misma cifra `4000` es kN/m en el esquema y N/m en un proyecto `SI_M_N`, un factor 1000. La conversión es explícita por magnitud (área con el cuadrado del factor, inercia con la cuarta potencia).

### 4. El pipeline del repositorio

```bash
python -m tools.gidopensees_import.parse_schemas \
    --mat path/to/OpenSees.mat --cnd path/to/OpenSees.cnd \
    --out tools/gidopensees_import/schemas.json

python -m tools.gidopensees_import.codegen \
    --schemas tools/gidopensees_import/schemas.json \
    --out src/opensees_studio/core/catalog/generated/
```

`codegen.py` (`CODEGEN_VERSION = 2`) escribe un módulo por entrada (`_to_module_name`), una clase `<Nombre>Spec` (`_to_class_name`, con `_dedupe` para duplicados), `generated/__init__.py` con una `Union` por BOOK (`_to_book_var`), `generated/conditions/__init__.py` y `core/catalog/__init__.py` con `CATALOG: dict[str, type[BaseModel]]` (58 claves). Cada archivo lleva la cabecera de atribución GPL-3.0 → AGPL-3.0 (ADR-0001 §2.3) y un sello derivado del `sha256` de `schemas.json` más `CODEGEN_VERSION`, nunca del reloj (`_source_stamp`, con CRLF normalizado antes de hashear); `_ruff_format` formatea la salida.

El catálogo es **solo esquema**: los 58 stubs de material y 39 de condición no están cableados al `Project` ni al runner (ADR-0001 §2.7, `core/catalog/README.md`). El puente es estrecho: `core/catalog_material.py` (`CatalogMaterial`, `catalog_spec`, `catalog_names`, `from_schema_defaults`) mete un nombre en el `Project` y `services/catalog_emitters.py` (`CATALOG_EMITTERS`, `catalog_emitter`, `wired_names`, `emit_catalog_material`) lo convierte en comando. Un nombre sin emisor lanza `NotImplementedError` nombrando lo cableado; hoy el único verificado de punta a punta es `Elastic`, y `Viscous`, `Viscous_Damper` y `Elastic_Perfectly_Plastic_with_Gap` están deliberadamente sin cablear porque la medición contradijo el esquema (`docs/gap-analysis-gidopensees.md`).

## Procedimiento

1. **Fijar la versión**: anotar la etiqueta (3.0.0-beta) y el `sha256` de `schemas.json`; el sello de los generados depende de ambos.
2. **Parsear** con `--mat` y `--cnd`; comprobar `14 books / 58 materials` y `6 books / 39 conditions`. Otro número es actualización de esquema, no ruido.
3. **Inspeccionar la IR**, no el `.mat`: `FieldSpec.widget_type`, `FieldSpec.dependencies`, `FieldSpec.tkwidgets`, `EntrySpec.tkwidgets`.
4. **Resolver unidades primero**: para cada campo `UNITS`, decidir su magnitud (`length`, `force`, `stress`, `moment`, `stiffness`); si el texto es ambiguo o incoherente, marcarlo.
5. **Generar**; si cambió una plantilla, subir `CODEGEN_VERSION`.
6. **Probar la deriva**: `pytest tests/tools/test_codegen_drift.py` e `test_codegen_idempotent.py` (>90 archivos, dos corridas idénticas).
7. **Cablear de uno en uno** en `services/catalog_emitters.py`, confirmando el orden posicional contra el solver vivo, con prueba en `tests/integration/test_catalog_materials.py`.
8. **Cerrar unidades** (`UnitTag`/`_units.py`, ADR-0001 §2.7) antes de promover un tipo; hasta entonces sigue siendo `str` con el TODO.
9. **Comprometer juntos** `schemas.json`, `generated/` y `CATALOG`.

## Implementación en la plataforma

Se **reimplementa** (nada importa GiD):

| Ruta | Contrato |
|---|---|
| `tools/gidopensees_import/parse_schemas.py` | `parse_mat(Path) -> list[BookSpec]`, `parse_cnd(Path) -> list[BookSpec]`, `build_catalog(mat, cnd) -> CatalogSpec`; `ParseError` con archivo y línea |
| `tools/gidopensees_import/schema_model.py` | IR Pydantic: `CatalogSpec`, `BookSpec`, `EntrySpec`, `FieldSpec`, `DependencyRule`, `DependencyAction` |
| `tools/gidopensees_import/codegen.py` | `run_codegen(schemas_path: Path, out_dir: Path) -> None`; determinista |
| `src/opensees_studio/core/catalog/` | `CATALOG: dict[str, type[BaseModel]]`; sin Qt ni solver |
| `src/opensees_studio/core/catalog_material.py` | `CatalogMaterial(gid_name, parameters, options)`, `from_schema_defaults(gid_name, id, name="")` |
| `src/opensees_studio/core/quantities.py` | `parse_quantity`, `split_quantity`, `QuantityError` |
| `src/opensees_studio/services/catalog_emitters.py` | `emit_catalog_material(material, ops) -> None`; `wired_names()` |

Cierre propuesto de la brecha de unidades, en tres pasos:

```python
# tools/gidopensees_import/parse_uni.py   (build-time, fuera de src/)
def parse_uni(path: Path) -> dict[str, dict[str, float]]:   # familia -> unidad -> factor
    """Lee OpenSees.uni; el resultado se compromete como units.json."""

# src/opensees_studio/core/catalog/_units.py   (core puro)
class UnitTag:
    def __init__(self, quantity: str) -> None: ...           # "force", "length", "stress"

StressValue = Annotated[float, UnitTag("stress")]            # emitido por codegen

# src/opensees_studio/core/catalog_material.py
def convert_to(self, system: UnitSystem) -> dict[str, float]: ...
```

`codegen.py` gana `--units tools/gidopensees_import/units.json`, emite `Annotated[...]` en vez de `str  # TODO: unit-aware type` y sube `CODEGEN_VERSION`; el `json_schema_extra` existente (`x-gid-name`, `x-book`, `x-icon`, `x-tkwidgets`, `dependencies`) no cambia.

Se **descarta**: GiD y su parser propietario en tiempo de ejecución (ADR-0001 §3B, rechazado), la ejecución de `TKWIDGET`, los escritores `bas/*.bas` y `bas/*Py.bas`, los ayudantes `tcl/*.tcl`, las plantillas `geo/`, los binarios `exe/`, `OpenSeesPost.dpr` y el post-proceso ODB de `opstool` (`xarray` + `zarr`/`netcdf4`).

Capas: la importación de terceros vive en `tools/`, fuera del paquete instalable; `core/catalog/` no importa Qt ni `openseespy`; la lectura de un `.mat` desde la interfaz corre en proceso auxiliar (`services/qt_workers.py`), **nunca** en el hilo de la GUI, y el catálogo se importa de forma perezosa (`catalog_spec` importa dentro de la función) para no pagar 58 módulos al arrancar.

## Datos normativos

No aplica. Esta skill no reproduce coeficientes de norma: los datos son los esquemas del problem type y viven en `OpenSees.mat`, `OpenSees.cnd` y `OpenSees.uni`, con copia normalizada en `tools/gidopensees_import/schemas.json`. Los valores por defecto de un campo (`'500 MPa'`, `'B500C'`) son presets de GiD, no valores normativos. La trazabilidad norma/edición/artículo es de `codes/code-crosswalk-and-extension`; la atribución GPL-3.0 → AGPL-3.0 es de ADR-0001 §2.3.

## Verificación y casos de prueba

| Caso | Comando, dato o condición | Resultado esperado |
|---|---|---|
| Parser | `python -m tools.gidopensees_import.parse_schemas --mat OpenSees.mat --cnd OpenSees.cnd --out /tmp/s.json` | imprime `14 books, 58 materials` y `6 books, 39 conditions` |
| Deriva | `pytest tests/tools/test_codegen_drift.py -q` | pasa; árbol comprometido idéntico byte a byte a una corrida fresca |
| Idempotencia | `pytest tests/tools/test_codegen_idempotent.py -q` | dos corridas coinciden; `len(snapshot) > 90` |
| Sello | `_source_stamp(SCHEMAS)` | `from schemas.json sha256:42032585df71, codegen v2` |
| Catálogo | `python -c "from opensees_studio.core.catalog import CATALOG; print(len(CATALOG))"` | `58` |
| Condiciones | contar `generated/conditions/*.py` | 39 módulos más `__init__.py` |
| Atribución | `grep -rl "rclab-auth/gidopensees" src/opensees_studio/core/catalog/generated` | cubre todas las entradas generadas |
| Unidades | `parse_quantity("4000 kN/m")`, `parse_quantity("-20MPa")`, `split_quantity("0.05 m")` | `4000.0`, `-20.0`, `(0.05, "m")` |
| Sin emisor | `emit_catalog_material` con `CatalogMaterial(gid_name="Viscous", …)` | `NotImplementedError` que nombra los nombres cableados |
| Cableado | `pytest tests/integration/test_catalog_materials.py -q` | pasa para cada nombre de `wired_names()` |
| Capas | `lint-imports` | sin violaciones: `core/` no importa Qt ni el solver |
| Identidad | `spec.model_fields` vs. `FieldSpec.name` del JSON | difieren solo por `_to_snake`/`_dedupe`; `x-gid-name` conserva el original |

## Errores frecuentes y trampas

1. **Mezclar unidades de GiD con las del proyecto**: el esquema usa kN, MPa y GPa y el proyecto puede estar en `SI_M_N`; copiar `'4000 kN/m'` como `4000.0` introduce un factor 1000 sin aviso.
2. **Creer que un `#UNITS#` es dimensionalmente sano**: hay defaults incoherentes (`Deformation_epsP = '1m'` para una deformación) y `parse_quantity` devuelve el número descartando la unidad.
3. **Usar el nombre Python del campo como identidad**: `_to_snake` cambia mayúsculas y `_dedupe` añade sufijos `_1`; la identidad real es `json_schema_extra["x-gid-name"]` y renombrar rompe a los emisores.
4. **Emitir posicionalmente desde un `Spec`**: mezcla discriminadores de interfaz (`Formulation`, `Material`) con parámetros físicos y cambia de argumentos según la rama; produce **modelos equivocados en vez de errores**.
5. **Reintroducir los campos `STATE: HIDDEN`**: el generador los excluye (`visible = [f for f in … if state != "HIDDEN"]`); 104 campos existen en el `.mat` y no en el modelo, y sin sus `DEPENDENCIES` la interfaz ofrecería campos que GiD nunca muestra.
6. **Convertir `DEPENDENCIES` en validadores Pydantic**: son reglas de visibilidad (ADR-0001 §2.6), no de validez del dato.
7. **Suponer el orden de argumentos del solver**: no es el orden de GiD; `Viscous` es `tag C alpha` y una firma aceptada puede no aportar nada al modelo (caso medido en el gap analysis).
8. **Perder la atribución de licencia**: esquema GPL-3.0 en proyecto AGPL-3.0 es válido, pero la cabecera y `core/catalog/README.md` deben sobrevivir a toda regeneración.
9. **Editar `generated/` a mano**: se sobrescribe y la deriva falla; las correcciones van en `catalog/curated/`.
10. **Actualizar el esquema sin fijar la versión**: otra etiqueta de gidopensees mueve el `sha256` y cambia el sello de todos los archivos de golpe.
11. **Perder precisión por el texto**: `'200 GPa'` son 2e11 Pa con tres cifras significativas; ningún valor de esquema sirve para un análisis, solo como preset.
12. **Tratar el catálogo como implementación**: un stub no vuelve ✅ una fila del gap analysis; sin emisor probado contra el solver, el tipo no existe.

## Interfaz de salida

- `schemas.json` con `source_type`, `book`, `widget_type`, `options`, `default`, `state`, `tkwidgets` y `dependencies` por campo.
- Árbol `generated/` con `CATALOG`, una `Union` por BOOK y, en cada archivo, la cabecera de atribución y el sello `from schemas.json sha256:…, codegen vN`.
- Metadatos por clase: `x-gid-name`, `x-book`, `x-icon`, `x-tkwidgets`, `dependencies`.
- Para la interfaz: nombre de gidopensees, BOOK, unidad esperada del campo, si el tipo está en `wired_names()` y, si no, el mensaje de lo que falta.
- Aviso explícito mientras un campo siga siendo `str` con `# TODO: unit-aware type`: no tiene tipo con unidad y el usuario debe teclearlo en las unidades del proyecto.

## Referencias

1. gidopensees 3.0.0-beta — `https://github.com/rclab-auth/gidopensees` (GPL-3.0, Lab of R/C and Masonry Structures, AUTh): `OpenSees.mat`, `OpenSees.cnd`, `OpenSees.uni`, `OpenSees.prb`, `OpenSees.tcl`, `OpenSees.sim`, `OpenSees.xml`, `Python.path`, `bas/`, `tcl/`, `wiki/python_tests/test_outputs.py`.
2. `docs/adr/ADR-0001-gidopensees-schema-import.md` — §2.3 atribución, §2.6 DEPENDENCIES, §2.7 `#UNITS#` diferido, §2.8 plan de verificación.
3. `docs/gap-analysis-gidopensees.md` — cobertura y estado del puente del catálogo al runner.
4. `src/opensees_studio/core/catalog/README.md` — «schema descriptions only…. not yet wired into the OpenSees runtime».
5. `tools/gidopensees_import/{parse_schemas.py, codegen.py, schema_model.py, schemas.json}`.
6. `tests/tools/{test_parse_schemas.py, test_codegen_idempotent.py, test_codegen_drift.py}`; fixtures `minimal.mat`, `minimal_expected.json`.
7. `core/{units.py, quantities.py, catalog_material.py}`, `services/catalog_emitters.py`, `tests/unit/test_catalog_materials.py`, `tests/integration/test_catalog_materials.py`.

> ⚠️ VERIFICAR: la documentación oficial de GiD sobre el formato de problem type (`BOOK`, `QUESTION`, `VALUE`, `STATE`, `DEPENDENCIES`, `TKWIDGET`) no se consultó; la gramática se dedujo de `parse_schemas.py` y de `OpenSees.mat`/`OpenSees.cnd`. Se comprueba en el manual de GiD o su ayuda («Problem type files») antes de escribir un parser nuevo.

> ⚠️ VERIFICAR: `OpenSees.prb`, `OpenSees.xml`, `OpenSees.sim` y `Python.path` solo se inventariaron por tamaño y descripción; no se abrieron. Se comprueba leyéndolos en el clon para decidir si el árbol de datos del problema (`.prb`) aporta tipos que el catálogo deba cubrir.

## Registro de verificación

- **Verificado** (2026-02-14, código en `dc18c7e`, esquema `sha256:42032585df71`): inventario de la raíz, BOOK y conteos 58/39, gramática que consume `parse_schemas.py`, IR de `schema_model.py`, sello determinista de `codegen.py` (`CODEGEN_VERSION = 2`), prueba de deriva byte a byte, estado `str` + `# TODO: unit-aware type` de los campos `#UNITS#`, ausencia de cableado al `Project`/runner, y contratos de `CatalogMaterial`, `services/catalog_emitters.py`, `core/quantities.py` y `core/units.py`.
- **Pendiente**: los dos bloques `VERIFICAR` (factores de `OpenSees.uni` y documentación de GiD; contenido de `.prb`/`.xml`/`.sim`/`Python.path`). Los cierra quien clone gidopensees y añada `parse_uni.py`; hasta entonces el estado es `draft` y ninguna conversión de unidades se codifica.
