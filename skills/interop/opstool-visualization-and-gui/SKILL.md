---
name: opstool-visualization-and-gui
description: >-
  Traslada la capa de visualización de opstool al lienzo PyVista y a los gráficos
  pyqtgraph de OpenSees Studio: la API de opstool.vis.pyvista (plot_model,
  plot_eigen, plot_nodal_responses, plot_frame_responses, plot_truss_responses,
  plot_unstruct_responses, sus *_animation, set_plot_props, set_plot_colors,
  reset_plot_props), la jerarquía PlotResponseBase / PlotResponsePyvistaBase, los
  ayudantes _plot_points, _plot_lines, _plot_face, _plot_unstru y _plot_all_mesh,
  los glifos de _get_bc_points_cells y _plot_mp_constraint, y la interpolación de
  puntos de integración a nudos de opstool/utils/ele_shape_func.py. Úsala al
  implementar un contorno de resultados o una animación modal, al degradar un
  extra ausente con make_dependency_missing, o al decidir qué se descarta de la
  ruta NiceGUI/trame.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "opstool 1.0.26"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, ui]
---

# Visualización de opstool → lienzo PyVista y gráficos pyqtgraph

## Cuándo usar esta skill

- Hay que pintar sobre la malla un campo de resultados (desplazamiento, tensión, fuerza de elemento) y falta la ruta punto-de-integración → nudo.
- Se implementa una animación modal o de historia temporal en el lienzo 3D, o se exporta a vídeo.
- Se decide si se reutiliza la API de `opstool.vis.pyvista`, su jerarquía de clases por tipo de elemento, o solo su matemática de interpolación.
- Aparece un nombre de opstool sustituido por `make_dependency_missing(...)` y hay que saber qué extra falta y qué se degrada.
- No usar para equivalencia Tcl ↔ OpenSeesPy (→ `interop/opensees-tcl-python-parity`), para el árbol de datos de GiD (→ `interop/gid-problem-type-schemas`) ni para decidir en qué capa vive un módulo (→ `platform/platform-architecture-and-services`).

## Alcance y límites

Cubre la **capa de presentación** de opstool: superficie pública de `opstool.vis.pyvista`, superficie pública de `opstool.vis.plotly`, jerarquía de clases base por tipo de elemento, utilidades internas de dibujo, interpolación de puntos de integración a nudos y el mecanismo de degradación por extra ausente. Cubre el mapeo a `views/canvas3d/`, `views/plot_style.py` y `services/deformation.py` del proyecto.

Queda fuera la creación del ODB (`opstool.post.CreateODB`), la malla de secciones (`opstool.pre.section`), la lectura de mallas de Gmsh (`Gmsh2OPS`) y `opstool.pre.tcl2py`. No cubre formulación de elementos finitos ni ejecución del solver.

Supuestos: el modelo y los resultados ya están en el almacén float64 del proyecto (`services/result_store.py`: HDF5 + `manifest.json`); la geometría ya está en el lienzo por `views/canvas3d/model_renderer.py::ModelRenderer`; PyVista pertenece al extra `[gui]`, no a la base.

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| Resultados por paso (`StaticResults`, `ModalResults`, historia temporal) | no se dibuja: la vista pide el dato al servicio, nunca al solver |
| Geometría tipada (líneas, superficies, sólidos) y sus tags | error explícito; no se infiere del campo de resultados |
| Tipo de elemento por tag | se resuelve con la tabla propia equivalente a `OPS_ELE_CLASSTAG2TYPE`, no por heurística |
| Sistema de unidades del modelo | se declara en la etiqueta y la barra de color; nunca se asume SI |
| Modo de render (`RendererMode`) y factor de escala | escala automática por `linear_static_auto_scale`, editable por el usuario |
| Extra opcional instalado (`[pyvista]`, `[plotly]`) | se degrada con aviso accionable, no con traza de importación |

## Fundamento y formulación

```text
ODB / almacén float64 (xarray en opstool · HDF5 + manifest.json en el proyecto)
   │  get_nodal_responses_dataset / get_unstruct_responses_dataset
   ▼
Dataset por tipo de elemento (nodal, frame, truss, unstruct)
   │  interpolación punto de integración → nudo
   ▼
Malla PyVista (points + cells) ya construida por ModelRenderer
   │  warp por desplazamiento · escalar por campo · cmap · barra de color
   ▼
Actores VTK en el lienzo  ·  curvas pyqtgraph para diagramas 2D
```

1. **Interpolación nodal.** Dentro del elemento, el campo se evalúa en coordenadas naturales \(\boldsymbol{\xi}\):

   \[
   u(\boldsymbol{\xi}) = \sum_{i=1}^{n} N_i(\boldsymbol{\xi})\,u_i
   \]

   con \(N_i\) las funciones de forma de `opstool/utils/ele_shape_func.py`, \(u_i\) el valor nodal (unidad del campo) y \(\boldsymbol{\xi}\) adimensional. `get_shape_func` devuelve \(N\); `get_gp2node_func` y `get_shell_gp2node_func` devuelven la relación inversa nudo ← puntos de integración, que es la que permite pintar un contorno cuando el solver solo entrega valores en los puntos de Gauss.
2. **Consistencia de la reconstrucción.** El operador GP→nudo debe reproducir el campo constante: \(\sum_g N_i(\boldsymbol{\xi}_g) = 1\) para todo nudo \(i\). Sin partición de la unidad el contorno se desplaza aunque la deformada sea correcta.
3. **Escala de la deformada.** Con \(L_c\) la diagonal del modelo (m) y \(u_{\max}\) el desplazamiento máximo (m), el factor adimensional es \(s = f\,L_c / u_{\max}\), con \(f\) la fracción objetivo de la diagonal. Se dibuja \(s\,u\); el valor real y el factor aplicado se muestran juntos.
4. **Mapeo de color.** El escalar \(c\) se normaliza a \([0,1]\) sobre un rango declarado, y ese rango es fijo por caso y paso: recalcularlo por fotograma hace parpadear la animación.
5. **Degradación por extra.** `make_dependency_missing(...)` sustituye cada nombre público por un invocable que falla nombrando el extra a instalar (`[pyvista]`, `[plotly]`, `[pre]`, `[gmsh]`) en vez del `ImportError` crudo. Es un contrato de **mensaje**, no de cálculo.

Superficie pública de `opstool.vis.pyvista` (alias `pv`) y destino en el proyecto:

| Nombre de opstool | Qué produce | Destino propuesto |
|---|---|---|
| `plot_model` | malla, nudos, apoyos, cargas | `ModelRenderer.render` (ya existe) |
| `plot_eigen` / `plot_eigen_animation` | modos propios y su animación | `RendererMode` + `modal_to_deformation` |
| `plot_nodal_responses` / `..._animation` | contorno nodal y animación | `ContourRenderer` (nuevo) |
| `plot_frame_responses` / `..._animation` | diagramas y contorno de barras | `services/element_forces.py` + pyqtgraph |
| `plot_truss_responses` / `..._animation` | axial en celosías | ídem, sin momento |
| `plot_unstruct_responses` / `..._animation` | contorno en continuos 2D/3D | `ContourRenderer` (nuevo) |
| `get_nodal_responses_dataset` | `xarray.Dataset` nodal | `services/result_fields.py` |
| `get_unstruct_responses_dataset` | `xarray.Dataset` de malla | `services/result_fields.py` |
| `set_plot_props` / `set_plot_colors` / `reset_plot_props` | estado global de estilo | **no** global: estilo por vista (`views/plot_style.py`) |

Jerarquía de clases. En `opstool/vis` viven `PlotResponseBase` y, por tipo, `PlotNodalResponseBase`, `PlotFrameResponseBase`, `PlotTrussResponseBase` y `PlotUnstruResponseBase`. La variante PyVista añade `PlotResponsePyvistaBase` y, sobre ella, `PlotModelBase`, `PlotEigenBase`, `PlotBucklingBase` y las clases de respuesta `PlotNodalResponse`, `PlotFrameResponse`, `PlotTrussResponse`, `PlotUnstruResponse`. Los ayudantes internos de dibujo son `_plot_points`, `_plot_lines`, `_plot_face`, `_plot_unstru` y `_plot_all_mesh`, con variantes `_cmap` para colorear; `_get_bc_points_cells` construye los glifos de apoyo y `_plot_mp_constraint` los de restricción multi-punto. `opstool.vis.plotly` (alias `po`) repite los nombres de visualización y añade aplicaciones NiceGUI en los archivos `*_gui.py` (`vis_model_gui`, `vis_eigen_gui`, `vis_nodal_resp_gui`…).

## Procedimiento

1. **Fijar el contrato de campos**: por tipo de resultado, nombre, unidad, localización (nudo, punto de integración, centro de elemento) y componentes. Sin unidad declarada no se pinta.
2. **Resolver el tipo de elemento por tag** con una tabla propia equivalente a `OPS_ELE_CLASSTAG2TYPE`; un tag desconocido es un aviso, no un contorno vacío.
3. **Elegir la función de forma** con `get_shape_func`; para continuos, reconstruir con `get_gp2node_func` (sólidos) o `get_shell_gp2node_func` (láminas).
4. **Reordenar la conectividad** a la convención de VTK antes de crear la celda: TET10, HEX20 y HEX27 no comparten orden de nudos con OpenSees (opstool lo hace en `opstool/pre/io/_read_gmsh.py`).
5. **Construir el `PolyData`** sobre la malla existente, adjuntando el escalar como `point_data` o `cell_data` según dónde viva el valor interpolado.
6. **Aplicar warp y color** con rango fijo por caso; exponer el factor de escala.
7. **Animar** con un temporizador de la GUI sobre fotogramas ya calculados, o exportar con `services/animation_export.py`; nunca recalcular el campo dentro del callback.
8. **Registrar en la leyenda** caso, combinación, unidad y paso o modo.
9. **Verificar** contra la tabla de casos antes de publicar.

## Implementación en la plataforma

**Se reimplementa**: la interpolación punto de integración → nudo, el catálogo de campos por tipo de elemento, el contorno sobre el `PolyData` existente, la escala automática de deformada, el par mínimo/máximo y la tabla de color por vista, la animación y su exportación, y los glifos de apoyo y restricción.

**Se descarta**: las aplicaciones web NiceGUI de `*_gui.py`, la dependencia de `trame` (y con ella `trame-vtk`, `trame-vuetify`, `trame-components`, `ipywidgets`), la ruta `opstool.vis.plotly` completa y la salida HTML o de notebook, el ODB zarr/netcdf4 con su `dtype` int32/float32 por defecto, y el estilo global de `set_plot_props` / `set_plot_colors` / `reset_plot_props`.

| Ruta propuesta | Capa | Contenido |
|---|---|---|
| `core/results/field_map.py` | `core/` | catálogo de campos: nombre, unidad, localización, componentes |
| `core/vis/shape_functions.py` | `core/` | `get_shape_func`, `get_gp2node_func`, `get_shell_gp2node_func` (NumPy puro) |
| `core/vis/cell_order.py` | `core/` | conectividad TET10/HEX20/HEX27 a la convención VTK |
| `services/result_fields.py` | `services/` | campos listos para pintar, leídos del almacén float64 |
| `services/deformation.py` | `services/` (existe) | `static_to_deformation`, `modal_to_deformation`, `transient_to_deformation_at_step` |
| `services/element_forces.py` | `services/` (existe) | `extract_diagram_data` para las curvas 2D |
| `services/animation_export.py` | `services/` (existe) | `export_mode_shape_video`, `export_time_history_video` |
| `views/canvas3d/contour_renderer.py` | `views/` | actores del contorno, apoyos y restricciones |
| `views/plot_style.py` | `views/` (existe) | estilo y colores **por vista** (`style_plot`) |

```python
# src/opensees_studio/core/vis/shape_functions.py   (puro: sin Qt, sin openseespy)
import numpy as np

def get_shape_func(shape: str):
    """N(xi) para 'line2', 'tri3', 'quad4', 'tet4', 'tet10', 'hex8', 'hex20', 'hex27'."""

def get_gp2node_func(shape: str, gp_coords: np.ndarray) -> np.ndarray:
    """Matriz (n_nudos x n_gp); sus filas suman 1 (partición de la unidad)."""

def get_shell_gp2node_func(shape: str, gp_coords: np.ndarray) -> np.ndarray:
    """Igual, para láminas, con los puntos de integración en el plano medio."""

# src/opensees_studio/services/result_fields.py   (puede usar el solver; nunca Qt)
from dataclasses import dataclass

@dataclass(frozen=True)
class ResultField:
    name: str
    unit: str                      # "m", "N", "Pa", "rad"
    location: str                  # "node" | "gauss" | "element"
    components: tuple[str, ...]
    values: np.ndarray             # float64, forma (n, len(components))

def nodal_field(project, results, *, name: str, step: int) -> ResultField: ...
def element_field(project, results, *, name: str, step: int) -> ResultField:
    """Interpola de puntos de integración a nudos con get_gp2node_func."""

# src/opensees_studio/views/canvas3d/contour_renderer.py   (nunca importa openseespy)
class ContourRenderer:
    def __init__(self, plotter, renderer: "ModelRenderer") -> None: ...
    def show_field(self, field: ResultField, *, clim: tuple[float, float],
                   cmap: str, warp: float | None = None) -> None: ...
    def set_step(self, step: int) -> None: ...       # no recalcula el campo
    def clear(self) -> None: ...
```

Reglas de capa y de hilo:

- `core/vis/` es puro: NumPy y nada más; se prueba sin Qt y sin solver.
- `services/result_fields.py` lee el almacén float64 y es el único punto donde se toca el resultado del análisis.
- `views/` nunca importa `openseespy` ni llama al solver: pide el `ResultField` al viewmodel.
- La lectura del ODB y la interpolación no corren en el hilo de la GUI: van por el viewmodel y, si son lentas, por `services/qt_workers.py`, único módulo de `services/` autorizado a importar Qt.
- La importación de terceros (PyVista arrastra VTK) ocurre fuera del hilo de la GUI o en el arranque, nunca dentro de un repintado.

## Datos normativos

No aplica: no hay norma de diseño en juego. El dato real que gobierna la presentación vive en el modelo y sus resultados: la unidad declarada por el proyecto, los valores float64 de `services/result_store.py` (HDF5 + `manifest.json`) y el caso/combinación y el paso que produjeron cada fotograma. Ninguna tabla de colores ni límite de escala es un dato normativo; son preferencias de vista versionadas con el estilo.

## Verificación y casos de prueba

| Caso | Comando, dato o condición | Resultado esperado |
|---|---|---|
| Partición de la unidad | suma de filas de `get_gp2node_func("hex8", gp)` | cada fila suma 1 dentro de `1e-12` |
| Campo constante | reconstruir un campo constante 1.0 desde los GP | todo nudo da 1.0 ± 1e-12 |
| Campo lineal | elemento con valores lineales en los nudos | la reconstrucción devuelve el valor nodal ± 1e-12 |
| Conectividad | TET10, HEX20 y HEX27 contra la convención VTK | nudos y caras coinciden; sin celdas invertidas |
| Precisión | contorno leído de `services/result_store.py` | float64 en todo el camino; ningún intermedio float32 |
| Escala | `linear_static_auto_scale(project, results)` | deformada máxima = fracción objetivo de la diagonal |
| Rango de color | mismo caso, dos pasos distintos | `clim` idéntico: sin parpadeo entre fotogramas |
| Capas | `lint-imports` | ninguna vista importa `openseespy`; `core/` no importa Qt |
| Extra ausente | importar `contour_renderer` sin PyVista | mensaje accionable del extra `[gui]`, no `ImportError` crudo |
| Animación | `export_mode_shape_video` sobre un modo | mismo `clim` en todos los fotogramas y unidad en la etiqueta |
| Diagrama 2D | `extract_diagram_data` con momento máximo 0 | sin división por cero; escala no aplicada |
| Unidades | caso en kN/mm y caso SI | la etiqueta declara la unidad; ningún factor incrustado |

## Errores frecuentes y trampas

1. **Precisión.** El `dtype` por defecto de opstool es int32/float32 y su ODB se escribe en zarr o netcdf4; el proyecto es float64 sobre HDF5. Comparar un contorno float32 con `atol = 1e-9` da fallos falsos.
2. **Unidades.** opstool no convierte: si el ODB viene en kN/mm, el contorno miente igual que el número. La unidad se declara en la salida.
3. **Tag frente a índice.** Los tags del proyecto son `PositiveInt` (con `999999` como centinela en vuelo); VTK indexa en base 0. Confundirlos pinta el contorno en otro nudo.
4. **Orden de nudos de la celda.** TET10, HEX20 y HEX27 no comparten orden con OpenSees: sin reordenar, las caras se invierten y el contorno atraviesa el elemento.
5. **Estilo global.** `set_plot_props`, `set_plot_colors` y `reset_plot_props` son estado de módulo: dos lienzos se pisan. En el proyecto el estilo es por vista.
6. **Efecto de importación.** `opstool.utils.CONFIGS` crea `RESULTS_DIR` (`<cwd>/.opstool.output`) al importar; en una app de escritorio eso ensucia el directorio del usuario y no se replica.
7. **Trabajo pesado en el hilo de la GUI.** Importar VTK o interpolar dentro de un repintado o del temporizador congela la interfaz.
8. **Recalcular por fotograma.** Reinterpolar en cada fotograma cambia el rango de color y hace parpadear la animación.
9. **`point_data` contra `cell_data`.** Un valor de punto de integración asignado a nudos (o al revés) suaviza o escalona el contorno sin avisar.
10. **Apoyos y restricciones.** Los glifos de `_get_bc_points_cells` y `_plot_mp_constraint` representan el vínculo, no la deformada: dibujarlos tras el warp los deja flotando.
11. **Degradación silenciosa.** Un nombre sustituido por `make_dependency_missing(...)` sigue existiendo y es invocable: falla en tiempo de ejecución, no de importación. Hay que comprobar el estado antes de ofrecer la acción en el menú.
12. **Versiones y licencias.** opstool declara Python `>=3.10,<3.13`; el proyecto fija 3.12 con OpenSeesPy 3.8.0.0. opstool es GPL-3.0 y el proyecto AGPL-3.0: reutilizar código exige conservar avisos de copyright y licencia, y "OPSTOOL™" es una marca que no se reutiliza en la interfaz.

> ⚠️ VERIFICAR: los nombres y firmas exactos de los ayudantes de dibujo (`_plot_points`, `_plot_lines`, `_plot_face`, `_plot_unstru`, `_plot_all_mesh` y sus variantes `_cmap`, más `_get_bc_points_cells` y `_plot_mp_constraint`) y el archivo que los contiene — se comprueba con `grep -rn "_plot_all_mesh\|_cmap\|_get_bc_points_cells\|_plot_mp_constraint" opstool/vis` en la copia clonada (v1.0.26).
> ⚠️ VERIFICAR: la firma exacta de `get_shape_func`, `get_gp2node_func` y `get_shell_gp2node_func` (¿etiqueta del elemento, dimensiones o coordenadas de los GP?) — se comprueba leyendo `opstool/utils/ele_shape_func.py` y ejecutando `get_gp2node_func` sobre `hex8` y `quad4` verificando que las filas suman 1.
> ⚠️ VERIFICAR: el mensaje y la firma exactos de `make_dependency_missing(...)` y los extras que nombra — se comprueba leyendo `opstool/vis/__init__.py`, importando el paquete en un entorno sin PyVista y llamando a `plot_model` para ver el mensaje real.
> ⚠️ VERIFICAR: las variables y coordenadas que devuelven `get_nodal_responses_dataset` y `get_unstruct_responses_dataset` (nombres de `DataArray`, atributos de unidad) — se comprueba ejecutándolas sobre `examples/postprocessing` con un ODB generado e imprimiendo `ds.coords` y `ds.data_vars`.

## Interfaz de salida

- Toda vista de resultados declara caso y combinación, paso o modo, nombre del campo, unidad y rango de color efectivo.
- Un campo sin unidad declarada no se pinta: se muestra un aviso accionable.
- Los valores se leen del almacén float64 y se muestran sin redondeo intermedio.
- El factor de escala de la deformada es visible y editable, y el valor real acompaña al amplificado.
- La degradación por extra ausente nombra el extra a instalar, no muestra una traza.
- Los avisos de tag desconocido, campo no disponible o elemento sin resultado viajan con la vista hasta el informe.

## Referencias

1. opstool 1.0.26, <https://github.com/yexiang92/opstool> — `opstool/vis/__init__.py` y `opstool/vis/pyvista/`: `plot_model`, `plot_eigen`, `plot_eigen_animation`, `plot_nodal_responses`, `plot_frame_responses`, `plot_truss_responses`, `plot_unstruct_responses`, sus `*_animation`, `get_nodal_responses_dataset`, `get_unstruct_responses_dataset`, `set_plot_props`, `set_plot_colors`, `reset_plot_props`.
2. opstool 1.0.26 — `opstool/vis/plotly/` con las aplicaciones NiceGUI `*_gui.py` (`vis_model_gui`, `vis_eigen_gui`, `vis_nodal_resp_gui`).
3. opstool 1.0.26 — clases base `PlotResponseBase`, `PlotNodalResponseBase`, `PlotFrameResponseBase`, `PlotTrussResponseBase`, `PlotUnstruResponseBase`, `PlotResponsePyvistaBase`, `PlotModelBase`, `PlotEigenBase`, `PlotBucklingBase`, `PlotNodalResponse`, `PlotFrameResponse`, `PlotTrussResponse`, `PlotUnstruResponse`.
4. opstool 1.0.26 — `opstool/utils/ele_shape_func.py`, `opstool/utils/ops_ele_class_tags.py` (`OPS_ELE_CLASSTAG2TYPE`), `opstool/pre/io/_read_gmsh.py` (reordenación TET10/HEX20/HEX27), `opstool/utils/__init__.py` (`CONFIGS`, `RESULTS_DIR`, `ODB_FORMAT`, `ODB_ENGINE`), `LICENCE.txt` (GPL-3.0); documentación en <https://opstool-doc.readthedocs.io>.
5. Proyecto propio: `src/opensees_studio/services/deformation.py`, `element_forces.py`, `animation_export.py`, `result_store.py`, `results.py`, `qt_workers.py`; `src/opensees_studio/views/canvas3d/model_renderer.py`, `model_canvas.py`, `diagram_renderer.py`; `src/opensees_studio/views/plot_style.py`.
6. Proyecto propio: `CLAUDE.md`, `docs/architecture.md`, `docs/adr/ADR-0002-headless-gui-dep-split.md`, `skills/platform/platform-architecture-and-services/SKILL.md`, `skills/interop/opensees-tcl-python-parity/SKILL.md`.

## Registro de verificación

- **Verificado** contra los hechos y el repositorio: la lista completa de nombres públicos de `opstool.vis.pyvista`; `opstool.vis.plotly` y las apps NiceGUI en `*_gui.py`; la jerarquía de clases base y la variante PyVista con `PlotModelBase`, `PlotEigenBase` y `PlotBucklingBase`; los ayudantes `_plot_points`, `_plot_lines`, `_plot_face`, `_plot_unstru`, `_plot_all_mesh` con variantes `_cmap`, `_get_bc_points_cells` y `_plot_mp_constraint`; `ele_shape_func.py` con `get_shape_func`, `get_gp2node_func` y `get_shell_gp2node_func`; `make_dependency_missing`; `dtype` int32/float32 por defecto; `RESULTS_DIR = <cwd>/.opstool.output` creado al importar; extras `[plotly]` (`plotly` + `nicegui`) y `[pyvista]` (`pyvista` + `trame` + `ipywidgets` + `trame-vtk/vuetify/components`); Python `>=3.10,<3.13`; GPL-3.0 y OPSTOOL™. Del proyecto: `ModelRenderer.render` y `RendererMode`, `DeformationSource`, `static_to_deformation`, `modal_to_deformation`, `transient_to_deformation_at_step`, `linear_static_auto_scale`, `extract_diagram_data`, `export_mode_shape_video`, `export_time_history_video`, `style_plot`, `result_store` float64, `services/qt_workers.py` como único módulo de servicios con Qt y el extra `[gui]`.
- **Pendiente**: cerrar los cuatro `VERIFICAR` leyendo la copia clonada de opstool v1.0.26 y ejecutando sus funciones sobre `examples/postprocessing`; después, decidir el paso a `ready`.
