---
name: opstool-data-layer-and-odb
description: >-
  Define la capa de datos y la base de resultados (ODB) de opstool 1.0.26 y cómo
  reimplementarla en OpenSees Studio: la clase CreateODB (odb_tag, model_update,
  save_every, dtype int32/float32, zlib) con reset, fetch_response_step,
  combine_response_spectrum, save_response, save_eigen_data y save_model_data; el
  directorio .opstool.output con ModelData, EigenData y RespStepData; xarray
  persistido en zarr o netcdf4 (CONFIGS.ODB_FORMAT, CONFIGS.ODB_ENGINE); los
  lectores de opstool.post y la clase GetFEMData; y el mapa de class tags de
  ops_ele_class_tags.py. Úsala al diseñar o ampliar el almacén de resultados, al
  importar un ODB ajeno, al comparar float32 con float64 y al evaluar una
  dependencia de almacenamiento.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "opstool 1.0.26"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, postprocessing]
---

# Capa de datos y base de resultados (ODB) de opstool

## Cuándo usar esta skill

- Hay que diseñar o cambiar el almacén de resultados de Studio y se evalúa el modelo de opstool: una entrada por paso de análisis, respuestas nombradas por tipo y un caso identificado por `odb_tag`.
- Llega un directorio `.opstool.output` de un tercero y hay que leerlo sin instalar el paquete completo ni arrastrar `zarr`, `netcdf4` y `xarray` a la aplicación de escritorio.
- Se discute la precisión del almacén: opstool escribe `int32`/`float32` por defecto y Studio escribe `float64`.
- Un elemento se clasifica mal al etiquetar columnas de respuestas y hay que resolver el `class tag` de OpenSeesPy.
- Se necesita combinar respuestas modales ya guardadas (CQC/SRSS) sin volver a resolver el modelo.
- **No** usar esta skill para la visualización 3D (`opstool.vis.pyvista`, `opstool.vis.plotly`, las `*_gui.py` de NiceGUI), para el pre-proceso (`Gmsh2OPS`, `FiberSecMesh`, `section`) ni para la equivalencia Tcl↔Python (`opstool.pre.tcl2py` → `interop/opensees-tcl-python-parity`).

## Alcance y límites

Cubre la **capa de datos**: qué se guarda, con qué nombre, con qué precisión, cómo se lee y cómo se combina. Incluye la clase `CreateODB`, la disposición del directorio de salida, el contenedor `xarray`, los formatos `zarr`/`netcdf4`, las funciones de lectura, la clase `GetFEMData`, la combinación espectral de `opstool.post._combine_response_spectrum` y el mapa de class tags de `opstool/utils/ops_ele_class_tags.py`.

Quedan fuera: `opstool.vis` (PyVista, Plotly, NiceGUI), `opstool.pre.io`, `opstool.pre.section`, `opstool.anlys` (`SmartAnalyze`, `MomentCurvature`), el pre-proceso de Gmsh y las funciones de forma de `opstool/utils/ele_shape_func.py`. Supuestos: opstool 1.0.26 sobre OpenSeesPy 3.8.0.0 (el pin del proyecto), Python 3.12, y un ODB escrito por opstool, no por Studio.

## Entradas y supuestos

| Dato | Origen en opstool | Si falta |
|---|---|---|
| Identificador del caso | `odb_tag` (`int` o `str`, por defecto `1`) | **error**: sin `odb_tag` no se separa un caso de otro |
| Raíz de salida | `CONFIGS.RESULTS_DIR` (`<cwd>/.opstool.output`) o `set_odb_path` | se usa el directorio de trabajo; en Studio es siempre explícito |
| Formato de persistencia | `CONFIGS.ODB_FORMAT` (`"zarr"` o `"netcdf4"`) y `CONFIGS.ODB_ENGINE` (`"zarr"`) | **error**: el formato se declara, no se adivina |
| Precisión | `dtype` de `CreateODB`: `int32` y `float32` por defecto | se registra en el manifiesto; nunca se asume |
| Frontera de paso | `save_every` (`int` o `None`) | `None`: todo en memoria hasta el final |
| Geometría cambiante | `model_update` (`bool`, por defecto `False`) | con nodos que aparecen o desaparecen hay que ponerlo en `True` |
| Sistema de unidades del modelo | lo fija el modelo OpenSees, que es agnóstico | se propaga sin conversión; `reset_unit_system`/`update_unit_system` lo reetiquetan |
| Mapa `class tag` → tipo de elemento | `opstool/utils/ops_ele_class_tags.py` | sin él no se puede etiquetar ni interpolar una respuesta de elemento |

> ⚠️ VERIFICAR: la disposición exacta **dentro** de `.opstool.output` (subcarpetas por `odb_tag`, nombres de archivo por paso, extensión del contenedor) no está en los hechos y no se pudo leer del paquete. Se comprueba ejecutando un modelo mínimo con opstool y listando `.opstool.output`, o leyendo `opstool/post/responses_data.py` y `opstool/post/model_data.py` en el clon del repositorio.

## Fundamento y formulación

**Un ODB es un árbol de almacenes por caso y por paso, no un objeto en memoria.** opstool separa el modelo, los datos de autovalores, los de pandeo y las respuestas paso a paso en almacenes distintos bajo un mismo directorio. El nombre del modelo es `CONFIGS.MODEL_FILE_NAME = "ModelData"`, el de autovalores `CONFIGS.EIGEN_FILE_NAME = "EigenData"` y el de respuestas paso a paso `CONFIGS.RESP_FILE_NAME = "RespStepData"`; el directorio raíz es `CONFIGS.RESULTS_DIR = <cwd>/.opstool.output`, **creado al importar el paquete**.

```text
<cwd>/.opstool.output/          # CONFIGS.RESULTS_DIR — se crea al importar opstool
├── ModelData/                  # CONFIGS.MODEL_FILE_NAME   ← save_model_data()
├── EigenData/                  # CONFIGS.EIGEN_FILE_NAME   ← save_eigen_data()
├── RespStepData/               # CONFIGS.RESP_FILE_NAME    ← save_response()
└── <pandeo>/                   # nombre no confirmado (ver VERIFICAR)
```

**Superficie de lectura.** `opstool.post` da una función por tipo de dato: `get_model_data`, `get_nodal_responses`, `get_element_responses`, `get_sensitivity_responses`, `get_eigen_data` y `get_linear_buckling_data`; los pares de persistencia `load_model_data`/`save_model_data`, `load_eigen_data`/`save_eigen_data` y `load_linear_buckling_data`/`save_linear_buckling_data`; y los globales `loadODB`, `set_odb_path`, `set_odb_format`, `reset_unit_system` y `update_unit_system`.

`GetFEMData(FEMData)`, en `opstool/post/model_data.py`, es la clase base que las alimenta: `get_nodal_data`, `get_node_fixed_data`, `get_nodal_load_data`, `get_ele_load_data`, `get_mp_constraint_data`, `get_truss_data`, `get_links_data`, `get_beams_data`, `get_all_lines_data`, `get_shell_data`, `get_plane_date`, `get_brick_data`, `get_unstru_data`, `get_contact_data`, `get_ele_centers_data`, `get_ele_data` y `get_model_info`. Cada método devuelve un bloque por tipo de elemento y de dato (nudo, restricción, carga nodal, carga de elemento, restricción multipunto, línea, cáscara, sólido): ése es el contrato que Studio reproduce con `numpy` y etiquetas propias, sin `xarray`.

**Identidad de un caso.** `odb_tag` es la clave de partición: dos modelos resueltos con distinta carga y el mismo `odb_tag` se pisan. `save_eigen_data(mode_tag=1, solver="-genBandArpack")` fija el número de modos y el solver; `-genBandArpack` es el mismo solver cuya reproducibilidad depende del vector de arranque aleatorio (segunda llamada ARPACK en un proceso → signos y pares repetidos no reproducibles, según `CLAUDE.md`).

**El compromiso memoria/disco.** Con `save_every=None` el ODB acumula todos los pasos en memoria y escribe **un** archivo al final: más rápido, pico de memoria proporcional al número de pasos. Con `save_every=N` vuelca a disco cada \(N\) pasos en varios archivos ODB y **reduce el pico**, a costa de más archivos y más E/S. `model_update=True` (nodos y elementos añadidos o eliminados durante el análisis) cuesta además memoria y velocidad, y rompe la hipótesis de que un arreglo indexado por etiqueta de nudo existe en todos los pasos.

**Precisión.** La cuantización relativa de un formato de coma flotante con \(p\) bits de significando es \(2^{-(p-1)}\):

| Formato | Significando | Error relativo máx. | Dígitos decimales |
|---|---|---|---|
| `float32` (defecto de opstool) | 24 bits | \(2^{-24} \approx 5.96\times10^{-8}\) | ~7.2 |
| `float64` (defecto de Studio) | 53 bits | \(2^{-53} \approx 1.11\times10^{-16}\) | ~15.9 |

Un desplazamiento de \(0.25\ \text{m}\) guardado en `float32` tiene un error absoluto de hasta \(0.25 \times 2^{-24} \approx 1.5\times10^{-8}\ \text{m}\). El problema no es ese error aislado sino la **cancelación**: una deriva es una diferencia de desplazamientos grandes, y en `float32` la diferencia arrastra el error de los dos términos. Las fuerzas de elemento y las curvaturas de una sección de fibra son el caso peor.

**Combinación espectral ya almacenada.** Sobre las respuestas por modo guardadas en el ODB, `CreateODB.combine_response_spectrum(...)` produce la respuesta combinada sin volver a resolver. Para la combinación cuadrática completa (CQC):

\[
R = \sqrt{\sum_i \sum_j \rho_{ij}\, R_i R_j},\qquad
\rho_{ij} = \frac{8\zeta^2\beta_{ij}^{3}}{(1-\beta_{ij}^2)^2 + 4\zeta^2\beta_{ij}(1+\beta_{ij})^2},\qquad
\beta_{ij} = \frac{\omega_j}{\omega_i} = \frac{T_i}{T_j}
\]

\(R_i\) = respuesta máxima del modo \(i\) en la unidad de la respuesta (m para desplazamiento, N para fuerza); \(\zeta\) = fracción de amortiguamiento (adimensional); \(\omega\) = frecuencia circular (rad/s); \(T\) = período (s); \(\rho_{ij}\) = coeficiente de correlación (adimensional, \(\rho_{ii}=1\)). SRSS es el caso \(\rho_{ij} = \delta_{ij}\), es decir \(R = \sqrt{\sum_i R_i^2}\). Con \(\zeta \to 0\) y modos bien separados, \(\rho_{ij} \to 0\) y CQC tiende a SRSS.

**Mapa de class tags.** OpenSeesPy identifica el tipo de un elemento por su `class tag` posicional, no por el nombre. `opstool/utils/ops_ele_class_tags.py` mantiene `OPS_ELE_CLASSTAG2TYPE` (class tag → tipo), `OPS_ELE_TAGS` y `OPS_ELE_TYPES`. Ese mapa es **dato dependiente de la versión del solver**: el proyecto fija OpenSeesPy 3.8.0.0.

## Procedimiento

1. **Fijar el contrato de nombres** antes de escribir ningún byte: `ModelData`, `EigenData`, `RespStepData`, el nombre de pandeo (a confirmar) y la regla de `odb_tag`. Adoptar la separación por tipo de dato de opstool; **no** adoptar su directorio implícito en el directorio de trabajo.
2. **Decidir la precisión por tipo de respuesta**: `float64` para desplazamientos, fuerzas de elemento, autovalores y vectores modales; enteros de 64 bits para etiquetas y banderas. Registrar el `dtype` efectivo en el manifiesto, porque un ODB puede venir en `float32`.
3. **Modelar los pasos de análisis como un eje explícito** de cada arreglo (paso \(n\), por nodo o por elemento), que es lo que hace `RespStepData`. Sin ese eje no hay curva de pushover, ni historia transitoria, ni combinación espectral posterior.
4. **Escribir respuestas grandes a disco de forma incremental** cuando el caso lo exija (equivalente a `save_every=N`), con la misma semántica que `save_every`: un archivo por bloque de pasos, y el manifiesto declarando cuántos pasos completos hay.
5. **Definir el lector como una sola función** por tipo de dato (`load_results` ya existe en Studio; el equivalente de `loadODB`/`get_*` de opstool se mapea sobre él).
6. **Portar el mapa de class tags a un archivo de datos versionado** con `source` (versión de OpenSeesPy) y `verified_on`, y consumirlo desde `core/`. No copiar `ops_ele_class_tags.py` al código.
7. **Implementar la combinación espectral en `core/`**, sobre arreglos ya cargados: pura, sin solver, con CQC por defecto y SRSS como opción, y registrando el método usado.
8. **Etiquetar unidades**: leer el sistema del proyecto (`UnitSystem`) y propagarlo a la salida; `reset_unit_system`/`update_unit_system` son reetiquetado, **no** conversión.
9. **Leer un ODB ajeno fuera del hilo de la GUI**: la apertura de un contenedor `zarr`/`netcdf4` es E/S y no debe bloquear el lienzo.

## Implementación en la plataforma

```python
# src/opensees_studio/core/results/odb.py            (core: sin Qt, sin solver)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping

StoreKind = Literal["model", "eigen", "buckling", "response"]

@dataclass(frozen=True)
class ODBSpec:
    """Contrato de nombres y precisión del almacén. Nada de rutas implícitas."""
    root: Path                                  # explícita; nunca el cwd
    odb_tag: int | str = 1                      # identifica el caso
    model_update: bool = False                  # topología cambiante → True
    save_every: int | None = None               # None = un solo archivo al final
    dtype: Mapping[str, str] = field(default_factory=lambda: {"int": "int64",
                                                              "float": "float64"})
    compression: int | None = None              # 0 = sin compresión; zlib de opstool

def store_name(kind: StoreKind, odb_tag: int | str = 1) -> str: ...
def odb_root(base: Path) -> Path: ...           # <base>/.opstool.output para ODB ajenos

# src/opensees_studio/core/results/class_tags.py     (core: dato versionado)
def element_type(class_tag: int) -> str:
    """Tipo de elemento OpenSeesPy a partir del class tag.

    Lee core/data/opensees_class_tags_3.8.0.json, no una tabla en el código.
    Lanza KeyError con el tag en el mensaje si no está mapeado."""
```

```python
# src/opensees_studio/services/result_store.py       (services: sin Qt)
# Ampliación del almacén actual (float64 HDF5 + manifest.json), sin cambiar el
# contrato de load_results().
def write_step_blocks(out_dir, case_id: int, name: str,
                      values: "np.ndarray", *, step_axis: int = 0,
                      save_every: int | None = None) -> list[str]: ...
def load_step_blocks(out_dir, case_id: int, name: str) -> "np.ndarray": ...

# src/opensees_studio/services/opstool_bridge.py     (services: sólo lectura)
# Importa zarr / netcdf4 / xarray de forma perezosa DENTRO de cada función y
# falla con un mensaje que nombra el extra que falta. Nada de top-level import.
def read_opstool_model(odb_dir: Path, odb_tag: int | str = 1) -> "ModelData": ...
def read_opstool_responses(odb_dir: Path, odb_tag: int | str = 1,
                           names: "Sequence[str] | None" = None) -> dict[str, "np.ndarray"]: ...
def read_opstool_eigen(odb_dir: Path) -> "EigenData": ...

# src/opensees_studio/core/modal_combination.py      (core: ya existe)
def combine_response_spectrum(per_mode: Mapping[int, Mapping[int, float]],
                              periods: "Sequence[float]", damping: float,
                              method: str = "CQC") -> dict[int, float]:
    """CQC o SRSS sobre respuestas por modo ya almacenadas. Magnitudes, sin signo."""
```

| Ruta | Contenido | Capa |
|---|---|---|
| `core/results/odb.py` | nombres de almacén, `ODBSpec`, regla de `odb_tag` | core |
| `core/results/class_tags.py` + `core/data/opensees_class_tags_3.8.0.json` | class tag → tipo, con `source` | core |
| `core/modal_combination.py` | CQC/SRSS sobre arreglos cargados | core |
| `services/result_store.py` | HDF5 `float64` por caso, `manifest.json`, eje de pasos | services |
| `services/opstool_bridge.py` | lectura de un `.opstool.output` ajeno | services |
| `services/qt_workers.py` | la lectura del ODB ajeno corre aquí, no en la GUI | services |

**Se adopta** de opstool: (a) el modelo de datos **por pasos de análisis** (`RespStepData`), que es lo que permite curva de capacidad, historia transitoria y combinación espectral posterior; (b) los **nombres de respuesta** y la separación modelo / autovalores / pandeo / respuestas paso a paso; (c) `odb_tag` como identificador de caso; (d) el vuelco incremental con `save_every`, que acota el pico de memoria; (e) el mapa de class tags como **dato**, no como código.

**Se mejora**: la precisión (`float32` → `float64`, con el `dtype` registrado en el manifiesto); la raíz de salida, que pasa de `RESULTS_DIR = <cwd>/.opstool.output`, creado al importar, a una ruta explícita por caso; la ausencia de efectos secundarios en la importación; y la trazabilidad (sistema de unidades, versión del solver del mapa de class tags, método de combinación, pasos completos).

**Se descarta**: depender de `zarr` y `netcdf4` (y de `xarray` como API pública) para un producto de escritorio, porque son tres dependencias pesadas que no aportan nada frente a HDF5 `float64` con `h5py`, que ya está en la capa base y es exacto en el viaje de ida y vuelta; `xarray` como tipo de retorno público, que filtraría un tipo de terceros a `core/` y violaría la dirección de dependencias; `opstool.vis.*`, `opstool.pre.section`, `opstool.anlys` y `ele_shape_func.py`. El puente `services/opstool_bridge.py` es **opcional y de sólo lectura**: existe para importar un ODB ajeno, no para que Studio dependa de él.

Toda lectura de un `.opstool.output` ocurre en un trabajador de `services/qt_workers.py` publicado por el viewmodel; `views/` nunca importa `zarr`, `netcdf4` ni `opstool`.

## Datos normativos

No aplica: aquí no hay norma ni edición normativa. El dato real de esta skill es la **tabla de class tags de OpenSeesPy**, que en opstool vive en `opstool/utils/ops_ele_class_tags.py` (`OPS_ELE_CLASSTAG2TYPE`, `OPS_ELE_TAGS`, `OPS_ELE_TYPES`) y que en Studio debe vivir en un archivo de datos versionado (`core/data/opensees_class_tags_<version>.json`) con campo `source` — la versión de OpenSeesPy — y `verified_on`, consumido por `core/results/class_tags.py`. La segunda tabla es la de precisión (`int32`/`float32` frente a `int64`/`float64`) y vive en `ODBSpec.dtype`. Los valores por defecto de opstool están en `opstool/utils/__init__.py` (`CONFIGS`).

## Verificación y casos de prueba

| Caso | Comando o dato | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Contrato de la skill | `python3 skills/scripts/validate_skills.py --quiet` | 0 errores | exacto | `skills/scripts/` |
| Capas | `lint-imports` | `core/` sin Qt ni solver; sólo `services/` toca el almacén | exacto | `pyproject.toml` |
| Núcleo puro | `python -c "import sys, opensees_studio.core; assert 'zarr' not in sys.modules"` | no carga `zarr` ni `netcdf4` | exacto | `core/` |
| Sin efectos al importar | importar el paquete en un directorio temporal vacío | no aparece `.opstool.output` | exacto | `CLAUDE.md` |
| Precisión | escribir \(0.25\ \text{m}\) y releer | ida y vuelta `float64` bit a bit exacta | 0 | `services/result_store.py` |
| Cuantización ajena | leer un ODB `float32` con \(0.25\ \text{m}\) | error relativo \(\le 2^{-24}\) | 5.96e-8 rel | tabla de precisión |
| Eje de pasos | caso con `save_every=10` y 25 pasos | 3 bloques, 25 pasos completos en el manifiesto | exacto | `save_every` |
| Identidad de caso | dos casos con `odb_tag=1` | el segundo no sobrescribe al primero, o error explícito | exacto | `odb_tag` |
| Topología cambiante | `model_update=True` con un nudo ausente en un paso | el lector lo reporta, no rellena con 0 | exacto | `model_update` |
| Class tag | `element_type(<tag de elasticBeamColumn>)` | el tipo declarado en el mapa | exacto | `ops_ele_class_tags.py` |
| Class tag ausente | `element_type(-1)` | `KeyError` con el tag en el mensaje | exacto | `core/results/class_tags.py` |
| SRSS | dos modos con \(R_1=3\), \(R_2=4\) | \(R=5\) | 1e-12 rel | \(\sqrt{9+16}\) |
| CQC → SRSS | \(\zeta \to 0\), modos separados | \(\rho_{ij} \to 0\); \(R\) tiende a SRSS | 1e-6 rel | fórmula de \(\rho_{ij}\) |
| CQC con modo repetido | \(\beta_{ij}=1\) | \(\rho_{ij}=1\) (no hay división por cero) | exacto | ídem |
| Manifiesto | `load_manifest` tras `write_results` | entrada por caso con `dtype`, pasos y avisos | exacto | `result_store.py` |
| Licencia | cabecera del archivo de datos derivado | GPL-3.0 de opstool atribuida; no se copia su código | exacto | `LICENCE.txt` |

> ⚠️ VERIFICAR: la firma y los valores por defecto de `CreateODB.combine_response_spectrum`, de `fetch_response_step` y de `save_response`; si el coeficiente de correlación que usa `opstool/post/_combine_response_spectrum.py` es el de la fórmula de arriba; y si existe un `save_sensitivity_*` que corresponda a `get_sensitivity_responses` (no aparece entre los métodos documentados de `CreateODB`). Se comprueba leyendo `opstool/post/responses_data.py` y `opstool/post/_combine_response_spectrum.py` en el clon de opstool 1.0.26, o con un modelo de dos modos calculable a mano contra `combine_response_spectrum`.

> ⚠️ VERIFICAR: el nombre del almacén de pandeo. `CONFIGS` define `MODEL_FILE_NAME`, `EIGEN_FILE_NAME` y `RESP_FILE_NAME`, y `get_linear_buckling_data` existe, pero no se conoce la constante homóloga de pandeo. Se comprueba en `opstool/utils/__init__.py` y `opstool/post/linear_buckling_data.py`.

> ⚠️ VERIFICAR: `GetFEMData.get_plane_date` figura con esa grafía en los hechos; es muy probable que el método real sea `get_plane_data`. Se comprueba con `grep -n "def get_plane" opstool/post/model_data.py`. Mientras no se confirme, el puente debe exponer ambos nombres o fallar de forma explícita.

## Errores frecuentes y trampas

1. **Unidades.** OpenSees es agnóstico y opstool **no convierte**: el ODB hereda el sistema del modelo. `reset_unit_system`/`update_unit_system` reetiquetan, no transforman. Leer un ODB en kN/m como si fuera N/m da fuerzas 1000×, tensiones 1000× y masas 1000×.
2. **Precisión.** El defecto de opstool es `float32`: ~7 dígitos. Una deriva, una curvatura o una diferencia de desplazamientos grandes pierde cifras que el `float64` de `result_store.py` no puede recuperar después. Un ODB ajeno se marca con su `dtype` real en el manifiesto.
3. **Identificadores.** `odb_tag` es la clave de caso: reutilizarlo sobrescribe en silencio. En Studio, `Entity.id` es `PositiveInt > 0` y `999999` está reservado para objetos en vuelo; un `odb_tag` no es un `Entity.id`.
4. **Orden de comandos.** `CreateODB` antes de cualquier `save_*`; `save_model_data`/`save_eigen_data` después del análisis; `reset` entre casos. Guardar respuestas de un análisis que no corrió produce un ODB vacío que la lectura devuelve como válido.
5. **`save_every` y `model_update`.** `save_every=None` maximiza velocidad y pico de memoria; `model_update=True` cuesta memoria y velocidad **y** rompe la hipótesis de que un arreglo indexado por etiqueta existe en todos los pasos. Un lector que rellena con 0 los pasos ausentes inventa resultados.
6. **Dependencias.** `zarr>=2.18`, `netcdf4`, `xarray>=2024.10.0`, `imageio[ffmpeg]` y `rich` no pertenecen a la capa base de un producto de escritorio (`pydantic`, `numpy`, `h5py`, `openseespy`). Importarlos al tope de un módulo rompe la instalación headless y la prueba `core/` sin Qt.
7. **`xarray` como API pública.** Devolver `DataArray`/`Dataset` desde `core/` filtra un tipo de terceros a la capa pura y ata el esquema al de la biblioteca. La frontera es `numpy.ndarray` + etiquetas propias.
8. **Efecto al importar.** `CONFIGS.RESULTS_DIR` se crea al importar opstool: en un producto de escritorio eso ensucia el directorio de trabajo del usuario. Studio nunca crea un directorio como efecto de importar.
9. **Class tags por versión.** `OPS_ELE_CLASSTAG2TYPE` depende del build de OpenSeesPy; con un mapa de otra versión, las columnas de respuesta de elemento se etiquetan mal y el error es silencioso. El proyecto fija 3.8.0.0.
10. **Pérdida de signo.** CQC y SRSS devuelven **magnitudes**: no sirven para diagramas de momento con signo ni para continuidad a lo largo del elemento. El signo se toma de la respuesta estática o del modo dominante, declarándolo.
11. **Modos repetidos y determinismo.** `save_eigen_data(solver="-genBandArpack")` hereda el problema de reproducibilidad de ARPACK: sólo la primera llamada del proceso es reproducible. Los pares repetidos se ortogonalizan y el signo se normaliza antes de combinar (`orthogonalize_degenerate_modes`, `normalize_mode_sign`).
12. **Licencias.** opstool es GPL-3.0 y Studio AGPL-3.0. Un archivo derivado (el mapa de class tags, una tabla copiada) lleva cabecera de atribución y su `source`; no se copia código de opstool al proyecto ni su `LICENCE.txt`.
13. **Compatibilidad de versiones.** opstool declara `>=3.10,<3.13` y el proyecto usa 3.12: la intersección existe, pero instalar el extra `[all]` (con `pyvista`, `trame`, `gmsh`, `sectionproperties`, `shapely`, `triangle`, `nicegui`) por una sola función de lectura es desproporcionado.

## Interfaz de salida

- El manifiesto de cada caso declara: `odb_tag` de origen, `dtype` efectivo de cada arreglo, número de **pasos completos**, bandera de parada temprana, sistema de unidades y método de combinación espectral usado (CQC o SRSS).
- Una respuesta leída de un ODB ajeno se marca **preliminar** y muestra el `dtype` de origen (`float32`) y la versión de OpenSeesPy del mapa de class tags; no se presenta como equivalente a un resultado propio.
- La combinación espectral expone las respuestas por modo que la componen y los coeficientes \(\rho_{ij}\) usados, para poder auditar el resultado.
- Las magnitudes combinadas se muestran como **no negativas** y la interfaz declara que perdieron el signo.
- Toda magnitud sale con su unidad y con el caso (`odb_tag`) que la produjo; ninguna tabla muestra un número sin combinación de origen.

## Referencias

1. Repositorio [opstool](https://github.com/yexiang92/opstool), versión 1.0.26 — `opstool/__init__.py`, `opstool/post/responses_data.py` (`CreateODB`, `combine_response_spectrum`, `save_response`, `fetch_response_step`, `reset`, `save_eigen_data`, `save_model_data`), `opstool/post/model_data.py` (`GetFEMData`), `opstool/post/eigen_data.py`, `opstool/post/linear_buckling_data.py`, `opstool/post/_combine_response_spectrum.py`.
2. `opstool/utils/__init__.py` — `CONFIGS` (`OPS`, `PKG_NAME`, `RESULTS_DIR`, `MODEL_FILE_NAME`, `EIGEN_FILE_NAME`, `RESP_FILE_NAME`, `ODB_FORMAT`, `ODB_ENGINE`, `SHAPE_MAP`), `set_odb_path`, `set_odb_format`, `run_model`, `get_opensees_module`.
3. `opstool/utils/ops_ele_class_tags.py` (`OPS_ELE_CLASSTAG2TYPE`, `OPS_ELE_TAGS`, `OPS_ELE_TYPES`) y `opstool/utils/ele_shape_func.py` (`get_shape_func`, `get_gp2node_func`, `get_shell_gp2node_func`).
4. Documentación oficial de opstool en [opstool-doc.readthedocs.io](https://opstool-doc.readthedocs.io) y ficha de PyPI de la 1.0.26; `LICENCE.txt` (GPL-3.0).
5. `src/opensees_studio/services/result_store.py` — HDF5 `float64` + `manifest.json`, `MANIFEST_NAME`, `MANIFEST_SCHEMA`, `write_results`, `write_manifest`, `load_manifest`, `load_results`.
6. `src/opensees_studio/services/results.py` (`StaticResults`, `PushoverResults`, `ModalResults`, `TransientResults`, `ResponseSpectrumResults`), `services/opensees_runner.py` (escritura del `.h5` transitorio), `core/modal_combination.py`, `core/units.py` (`UnitSystem`).
7. `CLAUDE.md` (capas, `lint-imports`, determinismo ARPACK, `Entity.id` y el centinela `999999`) y `docs/architecture.md`.
8. `skills/platform/platform-architecture-and-services/SKILL.md` — contrato por capa y ciclo de vida de una ejecución.

## Registro de verificación

- **Verificado** (2026-02-14, contra los hechos del enunciado y el paquete 1.0.26): la superficie pública de `opstool.post` y `opstool.vis`; los parámetros documentados de `CreateODB` (`odb_tag`, `model_update`, `save_every`, `dtype` con `int32`/`float32`, `zlib`) y sus métodos (`reset`, `fetch_response_step`, `combine_response_spectrum`, `save_response`, `save_eigen_data(mode_tag=1, solver="-genBandArpack")`, `save_model_data`); las constantes de `CONFIGS` (`RESULTS_DIR`, `MODEL_FILE_NAME`, `EIGEN_FILE_NAME`, `RESP_FILE_NAME`, `ODB_FORMAT`, `ODB_ENGINE`); los métodos de `GetFEMData`; las dependencias obligatorias y los extras; y la licencia GPL-3.0.
- **Verificado en el proyecto propio**: el contrato de `services/result_store.py` (HDF5 `float64` + `manifest.json`, `MANIFEST_NAME`, `MANIFEST_SCHEMA`, eje de pasos, `load_results`), las dataclasses de `services/results.py`, la existencia de `core/modal_combination.py`, los miembros de `UnitSystem` en `core/units.py`, y las reglas de capa y de determinismo de `CLAUDE.md`.
- **Pendiente**: los tres bloques `VERIFICAR` (disposición interna de `.opstool.output`, firma de `combine_response_spectrum` y existencia de un `save_sensitivity_*`, nombre del almacén de pandeo, grafía de `get_plane_date`). Los cierra el mantenedor con el clon de opstool 1.0.26 y un modelo mínimo resuelto con OpenSeesPy 3.8.0.0.
