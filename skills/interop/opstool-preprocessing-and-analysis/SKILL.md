---
name: opstool-preprocessing-and-analysis
description: >-
  Reutiliza el pre-proceso y los asistentes de análisis de opstool 1.0.26 en
  OpenSees Studio: la clase ModelMass (masa nodal y masa desde líneas,
  superficies, ladrillos y sólidos), las transformaciones de carga
  transform_beam_point_load, transform_beam_uniform_load,
  transform_surface_uniform_load, create_gravity_load, gen_grav_load y
  apply_load_distribution, UnitSystem con get_mck, find_void_nodes y
  remove_void_nodes, el mallado de secciones de fibra FiberSecMesh/SecMesh, la
  lectura de mallas Gmsh con Gmsh2OPS y los asistentes SmartAnalyze y
  MomentCurvature. Úsala al generar masas o cargas de gravedad desde la
  geometría, al mallar una sección de fibra, al importar un .msh o al plantear
  momento-curvatura o un análisis no lineal que no converge con el control por
  carga.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "opstool 1.0.26"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, analysis]
---

# Pre-proceso y asistentes de análisis de opstool

## Cuándo usar esta skill

- Hay que generar masa nodal desde la geometría (líneas, superficies, ladrillos, sólidos) porque el modelo no la declara.
- Hay que convertir densidades y espesores en masa o en carga de gravedad (`create_gravity_load`, `gen_grav_load`).
- Hay que repartir una carga de viga o de superficie en cargas nodales equivalentes (`transform_beam_point_load`, `transform_beam_uniform_load`, `transform_surface_uniform_load`, `apply_load_distribution`).
- Hay que mallar una sección de fibra a partir de un rectángulo, un círculo, un polígono o un DXF (`FiberSecMesh`, alias `SecMesh`).
- Llega una malla de Gmsh (`.msh`) y hay que meterla en el modelo (`Gmsh2OPS`), sobre todo con TET10, HEX20 o HEX27.
- Un análisis no lineal no converge con control por carga y hace falta una estrategia adaptativa (`SmartAnalyze`), o se pide una curva momento-curvatura de una sección (`MomentCurvature`).
- **No** usar esta skill para el post-proceso ODB (`CreateODB`, `loadODB`, xarray, zarr, netcdf4) ni para la visualización (`opstool.vis.pyvista`, `opstool.vis.plotly`, las apps NiceGUI `*_gui.py`): son flujos distintos. Para convertir un `.tcl` a OpenSeesPy, → `interop/opensees-tcl-python-parity`. Para el diseño del catálogo de materiales y secciones, → `core/fem-materials-and-sections`.

## Alcance y límites

Cubre los asistentes de **pre-proceso** de `opstool.pre` (masa, cargas, unidades, huecos, malla de sección, lectura de Gmsh) y los de **análisis** de `opstool.anlys` (`SmartAnalyze`, `MomentCurvature`).

Queda fuera `opstool.post`, `opstool.vis`, `opstool.utils.ops_ele_class_tags` y `opstool.utils.ele_shape_func` (eso es post-proceso), el conversor `tcl2py` y las dependencias opcionales de visualización. Supuestos: edición `opstool 1.0.26`, Python 3.12 (opstool declara `>=3.10,<3.13`), sistema de unidades coherente declarado en el proyecto.

## Entradas y supuestos

| Dato | Origen | Si falta |
|---|---|---|
| Geometría (longitudes de línea, áreas de superficie, volúmenes) | elementos de `core/geometry/elements.py` (`TrussElement`, `ElasticBeamColumn`, `QuadElement`, `ShellMITC4Element`, …) y `core/sections/` | no se puede integrar masa: error, nunca un volumen supuesto |
| Densidad `rho` (kg/m³) y espesor `d` (m) | material y sección del proyecto | error explícito: una densidad por defecto produce una masa plausible y falsa |
| `node_tag` / `ele_tags` | identificadores del modelo | error: las etiquetas no se inventan |
| Sistema de unidades y valor de `g` | `core/units.py::UnitSystem` | se bloquea; `factor` no se asume |
| Definición de la sección de fibra (contorno, materiales, número de fibras) | diálogo de sección / `FiberSection` | no se malla |
| Archivo `.msh` de Gmsh | ruta del usuario | error de lectura, sin malla parcial |
| Parámetros del material para momento-curvatura (axial, `eps`, `n_incr`) | usuario | error |
| `direction` y `factor` de la gravedad | usuario | valor documentado por defecto, siempre mostrado |

## Fundamento y formulación

**1. Masa desde la geometría (`ModelMass`).** La masa se integra sobre la entidad con la densidad del material:

| Origen | Fórmula | Unidad |
|---|---|---|
| Nudo (`add_node_mass`) | \(m = m_{dado}\) | kg |
| Línea (`add_mass_from_line`) | \(m = \rho\,A\,L\) | kg (A en m², L en m) |
| Superficie (`add_mass_from_surf`) | \(m = \rho\,A_s\,d\) | kg (d = espesor, m) |
| Ladrillo / sólido (`add_mass_from_brick`, `add_mass_from_solid`) | \(m = \rho\,V\) | kg (V en m³) |

La masa de cada entidad se reparte entre sus nudos; `total_mass` y `nodal_mass` son propiedades derivadas, `get_total_mass` y `get_node_mass(node_tags)` las consultan, `generate_ops_node_mass` emite `ops.mass(tag, m, m, m, 0, 0, 0)` y `reset` vacía el acumulador. La carga de gravedad es

\[ W_i = factor \cdot m_i \]

con `factor` una **aceleración**, no una fuerza: el valor por defecto documentado es `factor = -9.81` (m/s²) y el signo fija el sentido en la `direction` pedida (`generate_ops_gravity_load(direction, factor=-9.81, exclude_nodes=None)`).

**2. Transformaciones de carga.** `transform_beam_point_load` convierte una carga puntual sobre una viga en cargas nodales; `transform_beam_uniform_load`, una carga repartida (consistente o concentrada en los extremos); `transform_surface_uniform_load`, una presión sobre un elemento de superficie en fuerzas nodales por área tributaria; `apply_load_distribution` aplica el reparto y `create_gravity_load` / `gen_grav_load` construyen el patrón de gravedad a partir de las masas. El reparto es lineal y **conserva la resultante**: \(\sum F_i = qL\).

**3. Unidades.** `UnitSystem` de `opstool.pre` y `get_mck` (matrices de masa, amortiguamiento y rigidez del modelo, según su nombre: ver «Datos normativos») trabajan en el sistema declarado; no hay conversión automática. En OpenSees Studio el sistema es `core/units.py::UnitSystem` (`SI_M_N`, `SI_MM_N`, `US_FT_KIP`, `US_IN_KIP`) y `g = 9.80665 m/s²` en `SI_M_N`.

**4. Malla de sección (`FiberSecMesh`, alias `SecMesh`).** El contorno se descompone en parches (`create_circle_patch`, `create_polygon_patch`, `create_patch_from_dxf`), se desplaza el contorno (`offset`, `poly_offset`, `line_offset`), se asigna material por parche (`set_patch_material`) y se emiten los comandos `fiber`, `layer`, `patch` y `section`. El resultado es la misma descomposición que hoy calcula `services/section_properties.py::expand_fibres`: filas `(y, z, area)` sobre las que `compute_section_props` obtiene \(A\), centroide, \(I_y\), \(I_z\). `plot_fiber_sec_cmds` y `vis_fiber_sec_real` son sólo dibujo.

**5. Gmsh (`Gmsh2OPS`).** El lector reordena los nudos de TET10, HEX20 y HEX27 (`opstool/pre/_read_gmsh.py`) porque la numeración de Gmsh no coincide con la de OpenSees; sin ese reordenamiento la conectividad queda permutada y la matriz de rigidez del elemento es incorrecta aunque el modelo "corra".

**6. Análisis.** `SmartAnalyze` adapta el paso de carga y el algoritmo cuando la iteración no converge; `MomentCurvature` (`opstool/anlys/_sec_analysis.py`) integra la respuesta de una sección de fibra y devuelve la curva \(M(\varphi)\).

## Procedimiento

1. **Declarar unidades y `g`.** Leer `UnitSystem` del proyecto y fijar `factor` de gravedad en consecuencia; mostrarlo al usuario antes de generar nada.
2. **Construir la masa.** Recorrer las entidades seleccionadas y llamar a `add_mass_from_line`, `add_mass_from_surf`, `add_mass_from_brick`, `add_mass_from_solid` o `add_node_mass`; acumular sin duplicar entidades.
3. **Revisar el total.** Comparar `get_total_mass` contra un cálculo a mano \(\sum \rho V\); una diferencia del orden del número de nudos significa doble conteo.
4. **Emitir masa y gravedad.** `generate_ops_node_mass` para `ops.mass`; `create_gravity_load` + `gen_grav_load` (o `generate_ops_gravity_load`) para el patrón, con `exclude_nodes` para los apoyos.
5. **Repartir cargas de viga y superficie** con `transform_beam_point_load`, `transform_beam_uniform_load` o `transform_surface_uniform_load`, y verificar que la resultante se conserva.
6. **Limpiar huecos.** `find_void_nodes` detecta nudos sin elemento; `remove_void_nodes` los elimina. Si se eliminan, renumerar y comprobar que ninguna carga ni restricción apunta a un id borrado.
7. **Mallar la sección.** Con el extra `[pre]` disponible, `FiberSecMesh`/`SecMesh`: contorno → parches → `set_patch_material` → `section`; sin el extra, degradar con `make_dependency_missing` y **no** inventar una malla.
8. **Importar Gmsh.** `Gmsh2OPS` con el reordenamiento de TET10/HEX20/HEX27; informar cuántos elementos se reordenaron.
9. **Análisis.** Para momento-curvatura, `MomentCurvature` sobre la sección mallada. Para no linealidad rebelde, `SmartAnalyze` con pasos adaptativos; registrar cada cambio de estrategia.
10. **Entregar al proyecto** sólo entidades de `core/`; la emisión al solver sigue siendo de `services/opensees_runner.py`.

## Implementación en la plataforma

Toda la aritmética vive en `core/` (Python puro, Pydantic, NumPy); lo que necesita el solver o dependencias de geometría pesadas vive en `services/`.

| Ruta propuesta | Contenido | Capa |
|---|---|---|
| `src/opensees_studio/core/model_mass.py` | `ModelMass`: `reset`, `add_node_mass`, `add_mass_from_line`, `add_mass_from_surf`, `add_mass_from_brick`, `add_mass_from_solid`, `get_total_mass`, `total_mass`, `nodal_mass`, `get_node_mass`, `generate_ops_node_mass` | core |
| `src/opensees_studio/core/loads/gravity.py` | `create_gravity_load`, `gen_grav_load`, `generate_ops_gravity_load`, `apply_load_distribution`, `find_void_nodes`, `remove_void_nodes` | core |
| `src/opensees_studio/core/loads/transform.py` | `transform_beam_point_load`, `transform_beam_uniform_load`, `transform_surface_uniform_load` → `NodalLoad` de `core/loads/__init__.py` | core |
| `src/opensees_studio/services/section_properties.py` | malla de fibra: `mesh_fiber_section(spec, ...) -> np.ndarray`, reutilizando `expand_fibres` y `compute_section_props`/`SectionProps` | services |
| `src/opensees_studio/services/gmsh_import.py` | `read_msh(path) -> GmshModel` con el reordenamiento TET10/HEX20/HEX27 | services |
| `src/opensees_studio/services/analysis_strategies.py` | `smart_analyze(...)`, `moment_curvature(section, axial, n_incr) -> MomentCurvatureCurve` | services |
| `src/opensees_studio/core/analysis/__init__.py` | `MomentCurvatureCase(Entity)` como tipo de caso nuevo | core |
| `src/opensees_studio/services/qt_workers.py` | trabajador que corre la importación de Gmsh y el mallado fuera del hilo de la GUI | services |
| `src/opensees_studio/run.py` | registrar `MomentCurvatureCase` en el despacho de casos | raíz |

Firmas mínimas:

```python
# core/model_mass.py   (core puro: sin Qt, sin solver)
class ModelMass(BaseModel):
    def reset(self) -> None: ...
    def add_node_mass(self, node_tag: int, mass: float) -> None: ...
    def add_mass_from_line(self, ele_tags: Sequence[int], rho: float) -> None: ...
    def add_mass_from_surf(self, ele_tags: Sequence[int], rho: float, d: float) -> None: ...
    def add_mass_from_brick(self, ele_tags: Sequence[int], rho: float) -> None: ...
    def add_mass_from_solid(self, ele_tags: Sequence[int], rho: float) -> None: ...
    def get_node_mass(self, node_tags: Sequence[int]) -> dict[int, float]: ...
    def generate_ops_node_mass(self) -> list[tuple[int, tuple[float, ...]]]: ...

# core/loads/gravity.py
def create_gravity_load(model: Project, mass: ModelMass, direction: str, *,
                        factor: float, exclude_nodes: Sequence[int] = ()) -> PlainLoadPattern: ...

# services/section_properties.py
def mesh_fiber_section(contour: Sequence[tuple[float, float]], *, n_fib: int,
                       holes: Sequence[Sequence[tuple[float, float]]] = ()) -> np.ndarray: ...
```

**Se reimplementa**: las fórmulas de integración de masa, el reparto de cargas equivalentes, la detección de huecos, el reordenamiento de nudos de Gmsh y las dos estrategias de análisis (pasos adaptativos y momento-curvatura), traducidas a las entidades de `core/` y a los resultados de `services/result_store.py`.

**Se descarta**: la instalación de `opstool` como dependencia (arrastra `matplotlib`, `scipy`, `pandas`, `xarray`, `netcdf4`, `zarr`, `imageio[ffmpeg]`, `tqdm`, `rich` y, con extras, `plotly`, `nicegui`, `pyvista`, `trame`, `gmsh`, `sectionproperties`, `shapely`, `triangle`); el ODB en zarr/netcdf4 y `opstool.post` completo; `opstool.vis` y las apps NiceGUI; `tcl2py`; el módulo global `CONFIGS.OPS`. Se conservan las fórmulas y los nombres como referencia, no el código (licencia GPL-3.0, ver «Errores frecuentes»).

La importación de mallas y el mallado de sección **nunca** corren en el hilo de la GUI: el diálogo vive en `views/`, el viewmodel lanza un trabajador de `services/qt_workers.py` y publica progreso.

## Datos normativos

No aplica: aquí no hay norma ni edición normativa. El dato real de esta skill son la densidad de cada material, el espesor de cada sección y el valor de \(g\), y viven en los archivos de datos versionados del proyecto — `core/defaults.py`, el catálogo de materiales (`core/catalog/`, `core/catalog_material.py`) y `core/units.py` — consumidos por `core/`, nunca incrustados en la lógica. El contrato de esos archivos está en `codes/code-crosswalk-and-extension`.

> ⚠️ VERIFICAR: la firma exacta de `add_mass_from_line`, `add_mass_from_surf`, `add_mass_from_brick`, `add_mass_from_solid`, `generate_ops_node_mass` y `generate_ops_gravity_load`, y si la masa se **acumula** o se **reemplaza** en cada llamada. Se comprueba leyendo el módulo de `ModelMass` en el paquete instalado (`python -c "import opstool, inspect; print(inspect.getsource(opstool.pre.ModelMass))"`) sobre `opstool==1.0.26`.

> ⚠️ VERIFICAR: la firma y el contrato de `transform_beam_point_load`, `transform_beam_uniform_load`, `transform_surface_uniform_load`, `apply_load_distribution`, `create_gravity_load` y `gen_grav_load` (¿devuelven cargas nodales o emiten comandos al modelo activo?), y qué devuelve exactamente `get_mck`. Se comprueba con `inspect.getsource` sobre `opstool.pre` y con los ejemplos de `examples/preprocessing/` del repositorio clonado.

> ⚠️ VERIFICAR: los parámetros de `SmartAnalyze` (tolerancias, incrementos mínimos/máximos, algoritmos alternativos) y los de `MomentCurvature` (axial, `eps`, `n_incr`, unidad de curvatura). Se comprueban en `opstool/anlys/_sec_analysis.py` y en `opstool-doc.readthedocs.io`.

> ⚠️ VERIFICAR: la tabla de reordenamiento exacta de TET10, HEX20 y HEX27 (`opstool/pre/_read_gmsh.py`) y el algoritmo de mallado de `FiberSecMesh`. Se comprueban contra la documentación de Gmsh (orden de nudos por tipo de elemento) y contra `sectionproperties`; mientras tanto, el importador debe validar la conectividad con una prueba de rigidez, no confiar en el orden.

## Verificación y casos de prueba

| Caso | Comando o dato | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Contrato de la skill | `python3 skills/scripts/validate_skills.py --quiet` | 0 errores | exacto | `skills/scripts/` |
| Capas | `lint-imports` | sin violaciones; `core/` sin Qt ni solver | exacto | `pyproject.toml` |
| Masa de línea | \(L=6\) m, \(A=0.09\) m², \(\rho=7850\) kg/m³ | `get_total_mass` = 4239 kg | 1e-9 rel | cálculo a mano |
| Masa de superficie | \(A_s=12\) m², \(d=0.2\) m, \(\rho=2500\) kg/m³ | 6000 kg | 1e-9 rel | cálculo a mano |
| Gravedad | `generate_ops_gravity_load('Z', -9.80665)` sobre el caso anterior | \(W = -58839.9\) N; \(\sum W = m g\) | 1e-9 rel | cálculo a mano |
| Reparto de carga | `transform_beam_uniform_load` con \(q=10\) kN/m, \(L=6\) m | \(\sum F_i = 60\) kN; momento de empotramiento \(qL^2/12 = 30\) kN·m | 1e-6 rel | estática |
| Presión en superficie | `transform_surface_uniform_load` con \(p=5\) kPa, \(A=12\) m² | \(\sum F_i = 60\) kN | 1e-6 rel | estática |
| Nudos huecos | modelo con un nudo sin elemento | `find_void_nodes` lo lista; `remove_void_nodes` lo borra y renumera | exacto | `core/` |
| Propiedades de sección | rectángulo \(b=0.3\), \(h=0.5\) mallado | \(A=0.15\) m², \(I_y\), \(I_z\) analíticos | 1e-6 rel | `services/section_properties.py` |
| Reordenamiento Gmsh | TET10/HEX20/HEX27 del `.msh` de prueba | misma matriz de rigidez que el elemento de referencia | 1e-9 rel | Gmsh + `_read_gmsh.py` |
| Momento-curvatura | sección de fibra con \(M_y\) conocido | meseta de \(M\) al alcanzar \(M_y\) | 1 % rel | `MomentCurvature` |
| Convergencia | caso que diverge con control por carga | `SmartAnalyze` termina y registra cada cambio de paso | — | `opstool/anlys/` |
| Doble conteo | `add_mass_from_surf` + `add_node_mass` sobre el mismo nudo | aviso de masa duplicada | exacto | esta skill |

## Errores frecuentes y trampas

1. **`factor` es una aceleración, no una fuerza.** `generate_ops_gravity_load(direction, factor=-9.81)` inyecta `m · factor`; con el modelo en mm/ton el valor correcto es `-9810`, no `-9.81`. Un modelo en mm con `-9.81` pesa 1000 veces menos y "converge" sin avisar.
2. **Signo y dirección.** `direction` y el signo de `factor` se multiplican: dos negaciones dan una carga hacia arriba. La convención de `grav` de OpenSees (aceleración, no fuerza) es la misma trampa.
3. **Importar `opstool` desde `core/` o desde la GUI.** `CONFIGS.OPS` importa `openseespy.opensees` al cargar el paquete y `RESULTS_DIR = <cwd>/.opstool.output` **se crea al importar**. Un `import opstool` en `core/` rompe `lint-imports` y deja un directorio de salida en el cwd del usuario.
4. **Precisión.** El ODB de opstool usa `int32` y `float32` por defecto (`dtype`); el almacén del proyecto es HDF5 `float64` + `manifest.json`. Los resultados **no** se guardan en el ODB: se reemiten con `services/result_store.py`.
5. **Identificadores.** Las etiquetas de opstool son enteros de OpenSees; `Entity.id` es `PositiveInt > 0` y `999999` está reservado para objetos temporales. `remove_void_nodes` renumera: hay que reescribir cargas, restricciones y masas que apuntaban a los ids borrados.
6. **Doble conteo de masa.** `add_mass_from_*` acumula por llamada; llamar dos veces sobre la misma entidad duplica la masa. La comprobación es `get_total_mass` contra \(\sum \rho V\).
7. **Extra `[pre]` ausente.** `FiberSecMesh` y `create_patch_from_dxf` dependen de `sectionproperties`, `shapely` y `triangle`; sin ellas el nombre se sustituye por `make_dependency_missing(...)`. Llamarlo igual lanza o devuelve un marcador: la malla no existe. Hay que detectar la degradación, no asumir sección mallada.
8. **Orden de nudos de Gmsh.** TET10, HEX20 y HEX27 llegan permutados; sin el reordenamiento de `_read_gmsh.py` el modelo corre y da resultados equivocados. Nunca se acepta una malla sin la prueba de rigidez.
9. **Unidades del sistema.** opstool no convierte: `UnitSystem` del proyecto (`SI_M_N`, `SI_MM_N`, `US_FT_KIP`, `US_IN_KIP`) y el `UnitSystem` de opstool son objetos distintos. Mezclar la densidad de un material de catálogo (kg/m³) con un modelo en mm da masas 1e9 veces mayores.
10. **Compatibilidad de versiones.** opstool declara `>=3.10,<3.13`; el proyecto exige Python 3.12 exactamente (3.13 no carga `opensees.pyd`). Cualquier integración que arrastre una versión distinta de Python rompe la carga del solver.
11. **Licencia.** opstool es GPL-3.0 y OpenSees Studio es AGPL-3.0. Copiar código de opstool al proyecto crea una obra derivada: se reimplementan fórmulas y contratos con atribución, no se vendoriza el paquete ni se copian módulos.
12. **Orden de comandos.** `ops.mass` y las series de tiempo antes del `pattern` que las usa; `geomTransf` antes de los elementos; `wipeAnalysis()` al reconfigurar. Una carga de gravedad emitida antes de las masas genera un patrón vacío.

## Interfaz de salida

- **Informe de masa**: masa total por dirección, masa nodal por nudo, lista de entidades contribuyentes y aviso de posible doble conteo.
- **Informe de gravedad**: `direction`, `factor` con su unidad, \(g\) usado y nudos excluidos; nunca un `factor` sin unidad.
- **Informe de malla de sección**: número de fibras, \(A\), centroide, \(I_y\), \(I_z\), nombre del material por parche y advertencia si se usó una malla degradada.
- **Informe de importación Gmsh**: nudos y elementos por tipo, cuántos se reordenaron y qué elementos no se reconocieron.
- **Curva momento-curvatura**: pares \((\varphi, M)\) con unidades y la sección que los produjo, guardados como resultado reconstruible.
- **Registro de estrategia de análisis**: cada cambio de paso o de algoritmo de `SmartAnalyze`, con su criterio de convergencia.

## Referencias

1. [opstool](https://github.com/yexiang92/opstool) — `opstool/pre/` (`ModelMass`, transformaciones de carga, `UnitSystem`, `get_mck`, `find_void_nodes`, `remove_void_nodes`, `FiberSecMesh`/`SecMesh`, `Gmsh2OPS`), `opstool/pre/_read_gmsh.py` (reordenamiento TET10/HEX20/HEX27), `opstool/anlys/_sec_analysis.py` (`MomentCurvature`), `opstool/utils/` (`CONFIGS`, `set_odb_path`, `make_dependency_missing`).
2. [Documentación de opstool](https://opstool-doc.readthedocs.io) y `examples/preprocessing/`, `examples/sec-mesh/` del repositorio.
3. `opstool` en PyPI, versión 1.0.26; `pyproject.toml` con los extras `[pre]` (`sectionproperties`, `shapely`, `triangle`), `[pyvista]`, `[plotly]`, `[gmsh]`.
4. `LICENCE.txt` de opstool — GNU GPL v3. `LICENSE` de OpenSees Studio — GNU AGPL v3.
5. `src/opensees_studio/core/units.py` (`UnitSystem`, `UnitLabels`), `core/geometry/node.py` (`Node.mass`, `Restraint6`), `core/loads/__init__.py` (`NodalLoad`, `UniformElementLoad`, `PlainLoadPattern`), `core/sections/__init__.py` (`FiberSection`, `RectangularPatch`, `CircularPatch`, `StraightLayer`), `core/analysis/__init__.py` (`StaticCase`, `ModalCase`, `PushoverCase`).
6. `src/opensees_studio/services/section_properties.py` (`expand_fibres`, `compute_section_props`, `SectionProps`), `services/result_store.py` (HDF5 `float64` + `manifest.json`), `services/opensees_runner.py`, `services/qt_workers.py`.
7. `skills/platform/platform-architecture-and-services/SKILL.md` — capas y ejecución fuera del hilo de la GUI. `skills/codes/code-crosswalk-and-extension/SKILL.md` — datos versionados.
8. `CLAUDE.md` y `docs/architecture.md` — convenciones y trampas del repositorio.

## Registro de verificación

- **Verificado** (2026-02-14, contra los hechos del proyecto y la documentación de opstool 1.0.26): la lista de API pública de `opstool.pre` (`ModelMass` y sus métodos, las transformaciones de carga, `UnitSystem`, `get_mck`, `find_void_nodes`, `remove_void_nodes`, `FiberSecMesh`/`SecMesh` y sus funciones, `Gmsh2OPS`, `tcl2py`); la de `opstool.anlys` (`SmartAnalyze`, `MomentCurvature` en `_sec_analysis.py`, 1128 líneas); la dependencia del extra `[pre]` y la degradación por `make_dependency_missing`; el reordenamiento de nudos de TET10/HEX20/HEX27 en `opstool/pre/_read_gmsh.py`; `CONFIGS` (`PKG_NAME`, `RESULTS_DIR`, `ODB_FORMAT`, `ODB_ENGINE`); el rango de Python `>=3.10,<3.13`; la licencia GPL-3.0. Del proyecto propio: `core/units.py` (`UnitSystem`, `SI_M_N`, `SI_MM_N`, `US_FT_KIP`, `US_IN_KIP`), `core/geometry/node.py` (`mass`, `restraint`), `core/loads/__init__.py` (`NodalLoad`, `UniformElementLoad`, `PlainLoadPattern`), `core/sections/__init__.py` (`FiberSection`, `RectangularPatch`, `CircularPatch`, `StraightLayer`), `core/analysis/__init__.py` (`StaticCase`, `ModalCase`, `TransientCase`, `PushoverCase`, `ResponseSpectrumCase`), `services/section_properties.py` (`expand_fibres`, `compute_section_props`, `SectionProps`) y `services/result_store.py`.
- **Pendiente**: cerrar los cuatro bloques `VERIFICAR` (firmas exactas de `ModelMass` y de las transformaciones de carga, parámetros de `SmartAnalyze` y `MomentCurvature`, tablas de reordenamiento de Gmsh) contra el paquete `opstool==1.0.26` instalado y el repositorio clonado. Lo cierra el mantenedor al implementar `core/model_mass.py` y `services/section_properties.py`; hasta entonces la skill queda en `draft`.
