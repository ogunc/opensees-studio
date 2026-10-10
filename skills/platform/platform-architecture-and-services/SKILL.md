---
name: platform-architecture-and-services
description: >-
  Define la arquitectura del programa de análisis estructural: patrón MVVM con
  capa de servicios, dirección única de dependencias, contrato de cada capa
  (core sin Qt ni solver, services con solver, viewmodels, views, commands),
  ejecución del análisis en subproceso con snapshots y resultados en HDF5,
  escritura atómica, sistema de unidades y puntos de extensión para módulos de
  código y diseño. Úsala al crear un módulo nuevo, al decidir dónde vive una
  funcionalidad y al revisar que una contribución no rompe la arquitectura.
metadata:
  track: platform
  jurisdiction: agnostic
  edition: "n/a"
  status: ready
  verified_on: "2026-02-14"
  scope: [architecture, ui, qa]
---

# Arquitectura de la plataforma

## Cuándo usar esta skill

- Vas a añadir una funcionalidad y no sabes en qué capa vive.
- Un módulo nuevo "necesita" Qt o el solver en un lugar donde no debería.
- Hay que ejecutar análisis largos, cancelarlos y recuperar resultados.
- Hay que decidir cómo se guardan coeficientes normativos, resultados y unidades.

## Alcance y límites

Cubre la estructura del código, los contratos entre capas y el ciclo de vida de
una ejecución. No cubre la formulación de elementos finitos
(→ `core/fem-formulation-core`) ni la interfaz de usuario
(→ `platform/gui-cad-workflow-and-ux`).

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| Capa y punto de extensión de la funcionalidad | consultar la tabla «Puntos de extensión» de esta skill |
| Formato de archivo de proyecto e instantánea | leer `services/persistence` antes de tocar el esquema |
| Constructor del comando del proceso hijo | **nunca** duplicarlo: hay uno solo y se reutiliza |
| Convención de unidades del modelo | el proyecto la declara; no se asume |
| Versión de esquema soportada | se lee del propio archivo; una más nueva se rechaza |

## Fundamento y formulación

1. **Dirección única de dependencias**:
   `views → commands → viewmodels → services → core`.
   Se verifica mecánicamente; una violación es un fallo de integración continua,
   no una discusión de estilo.
2. **El núcleo es puro**. `core/` no importa Qt ni el solver. Es utilizable desde
   un script, un notebook, un servidor o un proceso hijo.
3. **Nadie fuera de `services/` importa el solver.** Las vistas nunca lo hacen.
4. **El análisis no corre en el proceso de la interfaz.** La GUI se mantiene
   responsiva y una caída del solver no se lleva la sesión del usuario.
5. **El modelo se puede serializar completo** antes de resolver: el archivo de
   entrada del análisis es la fuente de verdad de un resultado.
6. **Todo dato normativo es un dato**, versionado con cita (ver
   `codes/code-crosswalk-and-extension`).

## Contrato por capa

| Capa | Puede importar | Prohibido | Responsabilidad |
|---|---|---|---|
| `core/` | stdlib, Pydantic, NumPy | Qt, solver | Modelos, validación, formulación, códigos normativos, combinaciones |
| `services/` | `core/` + solver + HDF5 | Qt (salvo el módulo de workers) | Ejecución, persistencia, propiedades de sección, espectros, resultados |
| `viewmodels/` | `core/`, `services/`, Qt (signals) | widgets | Adaptadores, estado de la sesión, undo/redo |
| `views/` | `viewmodels/`, `commands/`, Qt, PyVista | solver | Widgets, diálogos, lienzo 3D |
| `commands/` | modelos de `core/` | referencias fuertes al viewmodel | Mutaciones reversibles |

Reglas derivadas:

- Un módulo de código normativo nuevo va en `core/codes/` y **solo** devuelve
  objetos de datos.
- Un cálculo que necesite el solver va en `services/` y expone una función pura
  respecto de la interfaz.
- Una vista que necesite un dato del solver lo pide a un servicio a través del
  viewmodel.

## Ciclo de vida de una ejecución

1. El viewmodel construye la **instantánea** del modelo (`.osmodel`) y la escribe
   con escritura atómica junto al proyecto.
2. Lanza el proceso hijo con la línea de comandos construida por un **único**
   constructor de argv (nunca `sys.executable -m ...` codificado a mano: un
   binario empaquetado se re-entra a sí mismo con otra bandera).
3. El hijo emite **una línea JSON por evento** en `stdout` (`log`, `progress`,
   `case_started`, `case_finished`, `error`), con descarga por línea; la salida
   nativa del solver se redirige fuera del protocolo.
4. Los resultados se escriben en un almacén (HDF5 float64 + `manifest.json`),
   sin pérdida, reconstruibles.
5. Códigos de salida: `0` todas las combinaciones corrieron (una parada temprana
   es un resultado válido), `2` error de análisis con línea `error`, `3` proyecto
   o referencia inválida; cualquier otro valor indica que el hijo murió.
6. La instantánea sirve de **recuperación ante caída**: si es más nueva que el
   proyecto, se ofrece restaurar o descartar.

Consecuencias para módulos normativos y de diseño:

- Un chequeo normativo **no** corre en la GUI: se calcula en el proceso de
  análisis (o en `core/`, sobre los resultados ya cargados) y se presenta.
- Los resultados deben guardar con qué edición normativa y con qué combinación se
  obtuvieron.

## Determinismo

- Los algoritmos con componente aleatoria (vector de inicio de métodos
  iterativos de autovalores) no son reproducibles en la segunda llamada del mismo
  proceso: se resuelve **reenviando** esa combinación a un proceso hijo nuevo.
- Los modos con autovalores repetidos se ortogonalizan y se normaliza el signo
  antes de mostrarse o combinarse.
- Toda combinación modal registra el método de combinación usado (por defecto, el
  que exige el código para esa estructura).

## Unidades y signos

- SI coherente internamente; la capa de presentación convierte.
- Las bibliotecas de perfiles vienen en sus unidades de publicación: la conversión
  de geometría es explícita (área con el cuadrado del factor, inercia con la
  cuarta potencia) y se muestra al usuario antes de insertar.
- Un elemento de biblioteca aporta **geometría**; el material lo elige el usuario.
- Convenciones de signo de diagramas: continuidad a lo largo del elemento, sin
  saltos artificiales en el extremo.

## Persistencia

- Una sola función escribe proyectos e instantáneas, y lo hace **atómicamente**:
  un guardado nunca trunca el archivo que el usuario ya tenía.
- El archivo declara su versión de esquema; una versión más nueva que la soportada
  se **rechaza**, no se reinterpreta hacia abajo.
- Un campo nuevo con valor por defecto no aparece en el archivo: los proyectos
  antiguos quedan byte a byte idénticos.
- Los coeficientes normativos no viven dentro del proyecto: el proyecto guarda
  `code_id` + edición, y los datos se cargan del catálogo versionado.

## Puntos de extensión

| Extensión | Dónde | Qué exponer |
|---|---|---|
| Elemento nuevo | `core/` (modelo) + `services/` (emisión al solver) | validación, GDL, matriz, ejemplo verificado |
| Material nuevo | `core/` + formulario en `views/` | parámetros, modelo constitutivo, ensayo de verificación |
| Tipo de análisis nuevo | `core/` + `services/` + `run.py` | entradas, salidas, ¿usa autovalores? |
| Código normativo nuevo | `core/codes/` + `data/` | `SeismicCode`, JSON con cita, tests |
| Chequeo de diseño nuevo | `core/design/` | función pura + referencia normativa + test |
| Métrica o diagrama nuevo | `services/` + `views/` | dato reconstruible desde el almacén de resultados |

## Procedimiento

Para decidir dónde vive una funcionalidad nueva y cómo se entrega:

1. **Clasificar el dato**: ¿es modelo, cálculo, presentación o mutación? Modelo y
   validación → `core/`; cálculo que necesita el solver → `services/`; estado de
   sesión → `viewmodels/`; presentación → `views/`; cambio reversible del modelo →
   `commands/`.
2. **Buscar el punto de extensión** en la tabla anterior y seguir su columna
   «Qué exponer».
3. **Definir el contrato** antes de escribir la implementación: entradas, salidas,
   unidades, errores.
4. **Escribir la prueba en la capa correcta**: unitaria sin Qt ni solver para
   `core/`; de interfaz para `views/`; de integración con solver real para
   `services/`.
5. **Comprobar los invariantes**: dirección de dependencias, núcleo puro,
   serialización idéntica de proyectos antiguos, protocolo del proceso hijo.
6. **Documentar** la decisión en `docs/adr/` si cambia un contrato entre capas.

## Implementación en la plataforma

Mapa de módulos de referencia del proyecto:

| Ruta | Contenido |
|---|---|
| `core/` | modelos Pydantic (`Project`, `Node`, `Element`, `Material`, `Section`, `Load`, `Analysis`), validación, combinaciones, códigos |
| `services/` | ejecución del solver, persistencia, propiedades de sección, espectros, almacén de resultados, animación |
| `viewmodels/` | `ProjectViewModel`, ejecución del análisis, pila de undo, catálogos |
| `views/` | ventana principal, diálogos, tablas, lienzo 3D |
| `commands/` | un comando por mutación del modelo |
| `run.py` | interfaz de línea de comandos del análisis (proceso hijo) |
| `child_cli.py` | único constructor del argv del proceso hijo |

## Datos normativos

No aplica. Los coeficientes normativos no viven en la plataforma sino en archivos
de datos versionados consumidos por los módulos de `core/codes/` y
`core/design/`; el contrato está en `codes/code-crosswalk-and-extension`.

## Verificación y casos de prueba

| Caso | Comprobación |
|---|---|
| Capas | el verificador de dependencias pasa (sin violaciones) |
| Núcleo puro | importar `core/` no carga Qt ni el solver |
| Vista sin solver | ninguna vista importa el solver |
| Ejecución | matar el proceso hijo deja la GUI viva y la instantánea recuperable |
| Protocolo | el hijo emite JSON válido línea a línea, aun con salida nativa del solver |
| Persistencia | guardado atómico: un fallo a mitad no corrompe el archivo previo |
| Compatibilidad | un proyecto antiguo se abre y se guarda idéntico |
| Determinismo | dos corridas de la misma combinación dan el mismo resultado |

## Errores frecuentes y trampas

1. Llamar al solver desde la interfaz "solo para una comprobación rápida".
2. Construir el comando del proceso hijo a mano en dos sitios distintos.
3. Guardar coeficientes normativos dentro del modelo: impide reutilizar el motor.
4. Escribir el proyecto con apertura directa en vez de la función atómica.
5. Actualizar el esquema del archivo hacia abajo en silencio.
6. Cachear resultados sin registrar la instantánea que los produjo.
7. Mostrar números sin su unidad ni su combinación de origen.
8. Introducir ciclos de referencia fuerte entre comandos y viewmodels (corrompe la
   memoria al liberar muchos comandos).
9. Bloquear el hilo de la interfaz esperando el resultado de un análisis.

## Interfaz de salida

- Cada resultado sabe: proyecto + instantánea, combinación, edición normativa,
  unidades y fecha.
- Cada comprobación de cumplimiento expone: valor demandante, capacidad, relación
  demanda/capacidad, artículo aplicable y veredicto.
- Los avisos de datos no verificados viajan con el resultado hasta el informe.

## Referencias

1. `docs/architecture.md` — documento largo de arquitectura del proyecto.
2. `docs/adr/ADR-0002-headless-gui-dep-split.md` — separación de dependencias.
3. `CLAUDE.md` — convenciones y trampas conocidas del repositorio.
4. `tests/` — organización en unitarias, de interfaz e integración.

## Registro de verificación

- **Verificado**: los contratos de capa, el ciclo de vida de la ejecución, el
  protocolo del proceso hijo y las reglas de persistencia corresponden al diseño
  documentado del proyecto.
- **Pendiente**: nada bloqueante. Actualizar si cambia el esquema de resultados o
  el mecanismo de spawn.
