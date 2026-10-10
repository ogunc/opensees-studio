---
name: gui-cad-workflow-and-ux
description: >-
  Define el flujo de modelado gráfico tipo CAD/SAP2000: construcción por ejes y
  niveles, snapping y rechazo de clics fuera de la retícula, selección y
  resaltado, edición en tablas, replicación y extrusión de pisos, asignación de
  apoyos, cargas y restricciones, atajos, navegación 3D y vistas predefinidas,
  unidades visibles, prevención de estados inválidos, mensajes accionables,
  undo/redo coherente, accesibilidad, localización y rendimiento percibido.
  Úsala al implementar o auditar herramientas de dibujo, comandos de edición,
  atajos, paneles de selección y diálogos de asignación, y al decidir si una
  interacción vive en las vistas o en el núcleo. Señales que la disparan: clics
  fuera de la retícula, selección desalineada en pantallas HiDPI o undo que no
  restituye el estado exacto.
metadata:
  track: platform
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [ui, qa]
---

# Flujo de modelado gráfico y experiencia de usuario

## Cuándo usar esta skill

- Se añade o se revisa una herramienta de dibujo (nodo, barra, área, réplica de pisos) o el comportamiento del ratón en el lienzo 3D.
- El usuario reporta que **el clic selecciona el objeto equivocado** o que el snap no cae en la intersección: típico en pantallas HiDPI al 125–200 %.
- Hay que decidir dónde vive una interacción nueva: `views/`, `commands/`, `viewmodels/` o `core/`.
- Un `undo` no restituye el modelo exacto, o una acción compuesta deja el estado a medias.
- Se pide traducir la interfaz, añadir un atajo, una vista predefinida o un mensaje de error nuevo.
- Alguien propone «convertir unidades» o «consultar el solver» desde una vista.
- Un modelo grande (decenas de miles de nodos) se siente lento al orbitar, seleccionar o pasar el ratón.

**No usar** para: formulación de elementos (→ `core/fem-formulation-core`), costo de la factorización y presupuestos del motor (→ `core/performance-and-scaling`), contratos de capa y ciclo de la ejecución (→ `platform/platform-architecture-and-services`), ni combinaciones y códigos (→ `seismic/load-combinations-and-limit-states`).

## Alcance y límites

Cubre la interacción gráfica y su trazabilidad: retícula y niveles, snap y rechazo del clic, selección y resaltado, edición tabular existente, transformaciones (mover, replicar, espejo), asignación de apoyos, cargas y restricciones, atajos, vistas predefinidas, presentación de unidades, prevención de estados inválidos, mensajes de error, undo/redo, accesibilidad, localización y latencia percibida. No cubre: el cálculo, la persistencia ni el formato del archivo; la biblioteca de perfiles; el diseño normativo. No existe hoy una vista de hoja de cálculo de todo el modelo: la edición tabular son el editor de propiedades, los diálogos de definición y las tablas de resultados. Supuestos: un documento por ventana; modelo 3D de barras y áreas; lienzo VTK embebido en Qt; coordenadas en las unidades que declara `project.meta.units`.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Retícula con líneas en los tres ejes | sí para dibujar | bloquear el clic y ofrecer definirla; no inventar una |
| Plano de trabajo y su offset | sí en vistas Top/Front/Right | derivarlo de la vista activa; en isométrica, snap sin filtro |
| `project.meta.units` | sí | sin unidades no se muestra ni se acepta ningún número |
| Selección actual | no | conjunto vacío; las acciones dependientes se deshabilitan |
| Pila de undo con marca limpia | sí | sin `cleanChanged` no hay diálogo de cambios sin guardar |
| Presupuesto de latencia por interacción | no | se lee de `data/ui/budgets.json`; si no existe, solo se mide |
| Textos traducibles y formato numérico local | sí para publicar | ver el aviso de localización en «Datos normativos» |

## Fundamento y formulación

### 1. Retícula, niveles y plano de trabajo

La retícula es un conjunto de líneas por eje —$x_i$, $y_j$, $z_k$, todas en m— y sus intersecciones son los únicos puntos donde el dibujo crea un nodo: $\mathbf{p}_{ijk} = (x_i, y_j, z_k)$ en coordenadas locales del sistema, llevado a global por $\mathbf{P} = \mathbf{R}\,\mathbf{p} + \mathbf{t}$ (m), con $\mathbf{R}$ la matriz de rotación (adimensional) y $\mathbf{t}$ el origen desplazado (m). El plano de trabajo filtra las intersecciones por su coordenada perpendicular al plano:

$$|n_a - d| \le \varepsilon, \qquad \varepsilon = 10^{-6}\ \text{m}$$

con $n_a$ la coordenada sobre el eje normal ($a = 0,1,2$ para los planos YZ, XZ, XY) y $d$ el offset del nivel activo (m). Sin este filtro, dibujar en planta a $z = 0$ engancha a la retícula de $z = 3$ que queda detrás en pantalla.

### 2. Píxeles lógicos, píxeles de dispositivo y proyección

Qt entrega posiciones en **píxeles lógicos** con origen arriba-izquierda; VTK trabaja en **píxeles de dispositivo** con origen abajo-izquierda. Con $r = \texttt{devicePixelRatioF()} \ge 1$ (adimensional) y $H$ la altura del widget en px lógicos, y $\Pi$ la proyección a pantalla de la cámara:

$$x_{dev} = x_{log}\,r, \qquad y_{dev} = (H - y_{log})\,r, \qquad \mathbf{u} = \Pi(\mathbf{P})$$

Toda tolerancia se declara en px lógicos y se compara en px de dispositivo: $\tau_{dev} = \tau_{log}\,r$. Valores vigentes del proyecto: $\tau_{log} = 15$ px para el aviso de snap al pasar el ratón, $18$ px para el pick de nodos y barras, y movimiento $\le 3$ px ($9$ px²) entre pulsar y soltar para que el gesto cuente como clic y no como arrastre de cámara.

### 3. Snap con rechazo explícito

Sea $\mathcal{I}$ el conjunto de intersecciones ya filtradas por el plano de trabajo y $\{(\mathbf{P}_m, \mathbf{u}_m)\}$ sus pares mundo/pantalla. El clic en $\mathbf{u}_c$ elige $m^\star = \arg\min_m \|\mathbf{u}_m - \mathbf{u}_c\|^2$ y **se comete** solo si $\|\mathbf{u}_{m^\star} - \mathbf{u}_c\|^2 \le \tau_{dev}^2$. Si no, **se rechaza** y se informa por la barra de estado. Rechazar es obligatorio: un nodo en posición no reticulada rompe la lectura de los niveles y la reproducibilidad del modelo.

### 4. Prioridad de selección y distancia punto–segmento

El pick es lexicográfico, de objetivo pequeño a grande: **nodo → barra o área → intersección libre de la retícula**. Un nodo a 12 px gana a una barra a 4 px si ambos están dentro de su tolerancia. Para barras, la distancia es punto–segmento en pantalla, con $\mathbf{a}, \mathbf{b}$ los extremos proyectados (px) y $\mathbf{u}_c$ el clic (px):

$$t = \mathrm{clamp}\!\left(\frac{(\mathbf{u}_c-\mathbf{a})\cdot(\mathbf{b}-\mathbf{a})}{\|\mathbf{b}-\mathbf{a}\|^2},\,0,\,1\right), \qquad d^2 = \bigl\|\mathbf{u}_c - \bigl(\mathbf{a} + t\,(\mathbf{b}-\mathbf{a})\bigr)\bigr\|^2$$

con guarda de segmento degenerado $\|\mathbf{b}-\mathbf{a}\|^2 \to 1$ cuando vale cero (barra perpendicular a la pantalla), para no dividir por cero ni propagar `NaN`.

### 5. Replicación, extrusión de pisos y espejo

Copia lineal de $n$ réplicas con incremento $\Delta\mathbf{d}$ (m): $\mathbf{P}_k = \mathbf{P}_0 + k\,\Delta\mathbf{d}$, $k = 1,\dots,n$. La extrusión de un piso es el caso $\Delta\mathbf{d} = (0, 0, h)$ con $h$ la altura de entrepiso (m). La copia radial usa $\mathbf{P}_k = \mathbf{c} + \mathbf{R}_z(k\,\Delta\theta)\,(\mathbf{P}_0-\mathbf{c})$, con $\mathbf{c}$ el centro (m) y $\Delta\theta$ el ángulo (rad). El espejo respecto de un plano de normal unitaria $\hat{\mathbf{n}}$ a distancia $d_0$ (m):

$$\mathbf{P}' = \mathbf{P} - 2\,\bigl(\mathbf{P}\cdot\hat{\mathbf{n}} - d_0\bigr)\,\hat{\mathbf{n}}$$

La réplica **reutiliza** los ids existentes cuando el punto destino coincide (tolerancia $10^{-6}$ m) y crea ids nuevos cuando no. Si no lo hace, el modelo acumula nodos duplicados en la misma coordenada y el ensamblaje queda mal condicionado.

### 6. Undo/redo coherente

Cada mutación es un comando con $\mathrm{redo}: S_k \to S_{k+1}$ y $\mathrm{undo}: S_{k+1} \to S_k$. Invariantes exigibles:

- $\mathrm{undo}(\mathrm{redo}(S_k)) = S_k$ **con los mismos ids** y el mismo orden de listas. Una acción del usuario = una entrada en la pila: los $m$ comandos de un asistente se agrupan en una macro atómica (`beginMacro` / `endMacro`), de modo que un solo `Ctrl+Z` los deshaga todos.
- El indicador de cambios sin guardar es $\texttt{clean} \iff \text{posición actual} = \text{posición de guardado}$; no un booleano paralelo que se pueda desincronizar.
- La pila guarda deltas, no instantáneas: el costo en memoria es $\sum_i |\Delta_i|$ frente a $O(|S|)$ por instantánea. Con más de $10^4$ entidades conviene una instantánea cuando $|\Delta_i| > \kappa\,|S|$, con $\kappa \approx 0.1$ (adimensional).
- El comando **no** conserva una referencia fuerte al viewmodel: el ciclo comando ↔ pila ↔ viewmodel solo lo libera el recolector cíclico, y liberar muchos de golpe corrompe el montón.

### 7. Unidades visibles

El proyecto declara un sistema de unidades —SI (m, N, kg, s, Pa), SI (mm, N, t, s, MPa), US (ft, kip, slug, s, ksf), US (in, kip, kip·s²/in, s, ksi)— y ese sistema **etiqueta**, no convierte: OpenSees es agnóstico a las unidades y resuelve los números tal como se escribieron. Factores entre sistemas (adimensionales), con $L$ longitud, $F$ fuerza, $A$ área, $I$ inercia, $\sigma$ tensión y $M$ momento:

$$s = \frac{L_{origen}}{L_{destino}}, \qquad f = \frac{F_{origen}}{F_{destino}}, \qquad s_A = s^2, \quad s_I = s^4, \quad s_{\sigma} = \frac{f}{s^2}, \quad s_M = f\,s$$

La conversión solo se aplica cuando un dato llega en su propio sistema (un perfil de catálogo en US) y se muestra antes de insertar. La gravedad estándar es $g = 9.80665\ \text{m/s}^2$, equivalente a $32.1740485564\ \text{ft/s}^2$ y $386.0885826772\ \text{in/s}^2$; las constantes del programa deben coincidir con estas dentro de $5\times10^{-8}$ relativo.

### 8. Prevención de estados inválidos y mensajes accionables

Una acción se habilita si y solo si su precondición se cumple: $\text{habilitado} \iff P(\text{modelo}, \text{selección})$. La precondición se evalúa en un único punto del código y se refleja en el `setEnabled` de la acción de menú, el botón y el atajo (los tres comparten un `QAction`); queda prohibido habilitar por conveniencia y validar al pulsar. Con $A$ acciones y $Q$ precondiciones, la matriz acción × precondición es un artefacto de prueba con $A \times Q$ casos.

Un mensaje accionable responde tres preguntas: **qué** pasó, **por qué** (la regla o el dato que lo impide) y **qué hacer** (acción concreta con su ruta de menú). «Operación no válida» no es un mensaje; «No hay retícula visible: defina una en Definir → Sistema de coordenadas/Retículas… para poder dibujar» sí lo es.

### 9. Rendimiento percibido y accesibilidad

Costo aproximado de un repintado, lineal en el número de actores:

$$t_{paint} \approx c_n N + c_e E + c_s S + c_g G \quad (\text{ms})$$

con $N$ nodos, $E$ elementos, $S$ superficies y $G$ líneas de retícula visibles (adimensionales) y $c_\bullet$ el costo medido por actor (ms/entidad). Presupuestos de percepción: $t_{paint} \le 16.7$ ms para interacción fluida ($60$ Hz), $\le 100$ ms para que una acción parezca instantánea y $\le 1$ s antes de exigir indicador de progreso. La consulta espacial del pick debe ser sublineal ($O(\log N)$ con índice) frente al barrido $O(N+E)$ actual.

Accesibilidad: contraste de texto $C \ge 4.5{:}1$ (texto grande $\ge 3{:}1$), contraste de componentes no textuales $\ge 3{:}1$ y objetivo de puntero $\ge 24\times24$ px CSS (WCAG 2.2, SC 1.4.3, 1.4.11, 2.5.8):

$$C = \frac{L_{claro}+0.05}{L_{oscuro}+0.05}, \qquad L = 0.2126\,R + 0.7152\,G + 0.0722\,B$$

con cada canal sRGB linealizado ($c \le 0.04045 \Rightarrow c_{lin} = c/12.92$; si no, $c_{lin} = ((c+0.055)/1.055)^{2.4}$) y $L$ adimensional. La selección no puede codificarse solo por color: necesita además contorno, grosor o forma.

## Procedimiento

1. **Clasificar la interacción**: presentación pura → `views/`; cambio del modelo → `commands/`; estado de sesión (selección, herramienta activa) → `viewmodels/` o `views/canvas3d/`; cálculo → `core/` o `services/`.
2. **Declarar la precondición** antes de escribir la acción y enlazarla al `setEnabled`, sin duplicar la regla dentro del manejador.
3. **Convertir el clic** a píxeles de dispositivo con el DPR y el volteo de Y, y guardar la posición **antes** de ceder el evento a VTK.
4. **Filtrar por plano de trabajo**, buscar el objetivo por prioridad y comparar contra $\tau_{dev}$; si nada cae dentro, rechazar y explicar en la barra de estado.
5. **Construir el comando** con la geometría ya resuelta (nodos destino, sección y material por defecto) y ejecutarlo dentro de una macro si la acción es compuesta.
6. **Validar antes de empujar**: sin ids duplicados, sin referencias colgantes, sin restricciones contradictorias; un modelo inválido no llega a la pila.
7. **Etiquetar toda magnitud** con `core.units.labels_for(project.meta.units)`; nunca formatear números a mano dentro de una vista.
8. **Marcar los textos** con `self.tr()`, pasar los números por `QLocale` y verificar la accesibilidad de lo nuevo (foco, tabulación, contraste, nombre accesible, tamaño del objetivo), y **medir el repintado** con el modelo grande de prueba registrando la cifra en la tabla de casos.
9. **Escribir la prueba en la capa correcta**: lógica de snap y transformaciones sin VTK; interfaz con `qtbot`; comandos contra el `QUndoStack`.

## Implementación en la plataforma

```python
# views/canvas3d/model_canvas.py — nunca importa openseespy
def _to_device(self, qt_x: float, qt_y: float) -> tuple[float, float, float]: ...
def _nearest_grid_intersection_px(self, cx: float, cy: float, tol_px: float) -> tuple[float, float, float] | None: ...
def frame_element_at(self, qt_x: float, qt_y: float, tol_logical_px: float = 18.0) -> int | None: ...
# views/canvas3d/selection.py — estado de selección como QObject con señal
class SelectionState(QObject):
    def select_node(self, node_id: int, *, additive: bool = False) -> None: ...
    def set_selection(self, nodes: set[int], elements: set[int]) -> None: ...
# views/tools/base.py — protocolo de herramienta; el controlador enruta los picks
class CanvasTool(QObject):
    def on_node_picked(self, node_id: int) -> None: ...
    def on_empty_clicked(self, x: float, y: float, z: float) -> None: ...
# commands/transforms.py — toda mutación es reversible
class ReplicateCommand(ProjectCommand): ...   # copy_point: int | None = None
class MirrorCommand(ProjectCommand): ...
# core/units.py — núcleo puro: sin Qt, sin solver
def labels_for(units: UnitSystem) -> UnitLabels: ...
def length_scale(source: UnitSystem, target: UnitSystem) -> float: ...
```

Módulos y firmas de referencia (los existentes en el repositorio). `_to_device` devuelve $(x_{dev}, y_{dev}, r)$; `_nearest_grid_intersection_px` recibe píxeles **de dispositivo**.

Reglas de arquitectura:

- El núcleo de cálculo vive en `core/`: **sin Qt y sin OpenSeesPy**. Ninguna decisión de interfaz (colores, tolerancias de ratón, textos) entra ahí.
- El solver **solo** se usa desde `services/`, y el verificador de dependencias lo comprueba mecánicamente. **Una vista nunca llama al solver**: pide el dato al viewmodel, y el viewmodel al servicio.
- Toda mutación del modelo pasa por `ProjectCommand` sobre `vm.undo_stack`; las vistas no tocan `project.nodes` ni `project.elements` directamente.
- Los diálogos se ajustan a la pantalla disponible con `views/screen_fit.fit_to_available_screen` y colocan avisos y rechazos en su `MessageArea`, fuera del área con desplazamiento.
- Una excepción dentro de un slot no cierra la aplicación: la captura `views/error_reporting` y la publica en el dock de consola.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Contraste de texto 4.5:1 (grande 3:1) | WCAG 2.2, SC 1.4.3 | sí |
| Contraste no textual 3:1 | WCAG 2.2, SC 1.4.11 | sí |
| Objetivo de puntero 24×24 px CSS | WCAG 2.2, SC 2.5.8 | sí |
| Texto redimensionable al 200 % sin pérdida | WCAG 2.2, SC 1.4.4 | sí |
| $g = 9.80665\ \text{m/s}^2$ | ISO 80000-3 / CODATA | sí |
| 1 in = 0.0254 m; 1 ft = 0.3048 m | ISO 80000-3 (exactos por definición) | sí |
| 1 kip = 4448.2216152605 N | lbf = 0.45359237 kg × 9.80665 m/s² | sí |
| Umbrales de percepción 0.1 s / 1 s / 10 s | Nielsen, *Usability Engineering*, 1993 | sí (heurística, no norma) |

> ⚠️ VERIFICAR: no hay decisión registrada sobre el **nivel de conformidad** de accesibilidad objetivo (A / AA / AAA) ni sobre qué combinaciones de color del resaltado cumplen el contraste sobre el fondo del lienzo. Se comprueba midiendo los colores reales del renderizador contra el fondo. Mientras tanto el programa debe leer la paleta de `data/ui/palette.json` —con `source` y `verified_on`— y los casos de contraste deben fallar si un color no alcanza 3:1.

> ⚠️ VERIFICAR: el proyecto **no tiene catálogo de traducción** (cero `QTranslator` y cero `self.tr()` al 2026-02-14) ni una decisión sobre el mecanismo. Se comprueba en `pyproject.toml` y en `views/`: si se adopta Qt Linguist (`.ts` / `.qm`) o traducción en tiempo de ejecución, y con qué idiomas de partida. Hasta entonces, todo texto nuevo pasa por `self.tr()`, los formatos numéricos por `QLocale`, y las cadenas traducidas viven en un archivo de datos versionado, nunca incrustadas en la lógica.

> ⚠️ VERIFICAR: el comportamiento de `devicePixelRatioF()` con escalado fraccionario (125 %, 150 %, 175 %) no se ha comprobado en una pantalla real desde este repositorio, y no se fija la política de redondeo del factor de escala. Se comprueba ejecutando la aplicación con esos escalados y registrando $r$, el tamaño del widget y el error de pick en píxeles. El programa debe tomar $r$ del widget en cada evento (nunca cachearlo al construir la ventana) y las pruebas de conversión deben cubrir $r \in \{1.0,\ 1.25,\ 1.5,\ 1.75,\ 2.0\}$.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Conversión lógica→dispositivo | $r=1.5$, $H=800$, clic lógico $(400,300)$ | $(600,\ 750)$ px | $10^{-9}$ px |
| Snap acepta | intersección en pantalla $(300,100)$, clic $(306,108)$, $\tau_{dev}=15$ | mundo $(3,0,0)$ m | exacto |
| Snap rechaza | clic a 100 px de toda intersección, $\tau_{dev}=15$ | `None`; sin nodo nuevo | exacto |
| Filtro de plano | plano XY con offset $0$; intersección en $z=3$ m | ninguna dentro de $\tau$ | $10^{-6}$ m |
| Punto–segmento | $\mathbf{a}=(0,0)$, $\mathbf{b}=(100,0)$, clic $(50,3)$ | $d = 3$ px, $t = 0.5$ | $10^{-9}$ px |
| Prioridad de pick | nodo a 12 px y barra a 4 px, $\tau_{log}=18$ | gana el nodo | exacto |
| Clic frente a arrastre | recorrido de 4 px entre pulsar y soltar | no es clic (umbral 3 px) | exacto |
| Réplica lineal | $n=3$, $\Delta\mathbf{d}=(0,0,3)$ m desde $(0,0,0)$ | $z \in \{3,6,9\}$ m | $10^{-9}$ m |
| Espejo | plano $x=0$, $\mathbf{P}=(2,1,0)$ m | $(-2,1,0)$ m | $10^{-9}$ m |
| Undo/redo | 3 mutaciones, 3 undos, reserializar | idéntico al estado inicial | byte a byte |
| Macro | «Crear pórtico» con $m$ comandos | un solo undo restituye todo | exacto |
| Unidades: longitud | $10$ ft → m | $3.048$ m | $10^{-12}$ rel |
| Unidades: momento | $1$ kip·ft → N·m | $1355.8179483$ N·m | $10^{-9}$ rel |
| Unidades: inercia | $1$ in⁴ → m⁴ | $4.1623143\times10^{-7}$ m⁴ | $10^{-8}$ rel |
| Coherencia de $g$ | $9.80665/0.3048$ frente a la tabla en ft/s² | $32.17405$ | $5\times10^{-8}$ rel |
| Contraste | `#767676` sobre `#FFFFFF` | $4.54{:}1$ | $0.01$ |
| Repintado | $2\times10^4$ nodos, órbita continua | $t_{paint} \le 16.7$ ms | presupuesto |

## Errores frecuentes y trampas

1. **Mezclar píxeles lógicos y de dispositivo.** Con $r = 1.5$, un clic en $y_{log} = 400$ de un widget de $800$ px lógicos ocurre en $y_{dev} = 600$, no en $400$: 200 px de error, y crece con la altura. El pick siempre convierte con `_to_device`.
2. Olvidar el **volteo del eje Y** (Qt arriba-izquierda, VTK abajo-izquierda): el error es $2y_{log}r - H$ y selecciona el objeto especularmente opuesto.
3. Escalar la tolerancia a dispositivo pero comparar contra distancias lógicas (o al revés), o cachear $r$ al construir la ventana: el objetivo cambia de tamaño físico con el escalado y «deja de seleccionar» solo en el portátil HiDPI.
4. Capturar la posición del clic **después** de `super().mousePressEvent()`: la herramienta de VTK puede consumir el evento o mover la cámara y la posición ya no es la del usuario. Se guarda al principio de `mousePressEvent`.
5. No distinguir clic de arrastre: orbitar con el botón izquierdo crea un nodo por cada movimiento. El umbral es 3 px al cuadrado, es decir 9 px².
6. Hacer snap a la intersección más cercana sin filtrar por el plano de trabajo: el nodo nace en el nivel $z = 3$ cuando el usuario dibuja en planta a $z = 0$, y el error no se ve hasta el análisis.
7. Con la retícula vacía, rechazar todos los clics sin explicar por qué: la aplicación parece rota en vez de vacía. Hay que detectarlo y ofrecer definirla.
8. Guardar en el comando una **referencia fuerte** al viewmodel: el ciclo comando ↔ pila ↔ viewmodel se libera solo por recolector cíclico y liberar muchos de golpe corrompe el montón.
9. Revalidar Pydantic en cada evento de ratón: la interactividad se hunde en modelos medianos. Los comandos mutan en sitio y la validación completa se hace antes de guardar o resolver.
10. Creer que cambiar de unidades convierte el modelo: OpenSees es agnóstico y solo se reetiquetan los números. Convertir de verdad exige reescalar valores y geometría con las potencias correctas (área al cuadrado, inercia a la cuarta).
11. Un `redo` que reasigna ids nuevos: el segundo `undo` restituye un modelo distinto y las cargas o los apoyos quedan apuntando a entidades inexistentes.
12. Habilitar acciones sin precondición («Asignar apoyo» con la selección vacía) y validar al pulsar: el estado inválido se vuelve alcanzable y el error llega tarde, cuando ya no hay nada que deshacer.
13. Concatenar cadenas traducidas (`"Piso " + str(i)`) o formatear con `f"{v:.3f}"`: produce textos intraducibles y separadores decimales incorrectos. Usar `self.tr()` con marcadores y `QLocale`.
14. Codificar la selección solo con otro color: no se distingue con daltonismo ni con contraste bajo. Hace falta además contorno, grosor o forma.
15. Reconstruir todo el modelo en cada `mouseMoveEvent` (aviso de snap, tooltip de elemento): en modelos grandes el hover se vuelve el cuello de botella. El actor de aviso debe ser independiente del modelo y la búsqueda, usar índice espacial.

## Interfaz de salida

- **Barra de estado**: unidades activas siempre visibles en el selector permanente, más el recuento de selección ($n$ nodos, $m$ elementos) y el mensaje de la última operación.
- **Mensajes**: qué falló, la regla o el dato que lo impide y la acción concreta con su ruta de menú. Los rechazos de snap no son modales: van a la barra de estado y al registro.
- **Pila de undo**: cada entrada con texto legible y traducible («Replicar 3 copias») y la marca de limpio enlazada al diálogo de cambios sin guardar.
- **Tablas y diálogos**: encabezado con la unidad de cada columna, edición con el mismo validador que el lienzo y las mismas precondiciones.
- **Avisos de datos no confirmados**: los bloques de verificación pendiente de esta skill viajan con el resultado hasta el informe, igual que los de los módulos normativos.
- **Trazabilidad de la interacción**: el registro de consola conserva el punto de mundo creado, la intersección de retícula de origen y el comando aplicado.

## Referencias

1. Qt Group, *Qt 6 / PySide6 Reference* — `QMouseEvent`, `QWidget.devicePixelRatioF()`, `QAction` y `QKeySequence`, `QUndoStack` / `QUndoCommand`, `QLocale`, `QAccessible`. Edición 6.x vigente.
2. Kitware, *VTK User's Guide* y documentación de `vtkPropPicker` y de las coordenadas de display. Edición vigente.
3. W3C, *Web Content Accessibility Guidelines (WCAG) 2.2*, W3C Recommendation, 5 de octubre de 2023 — SC 1.4.3, 1.4.4, 1.4.11 y 2.5.8.
4. J. Nielsen, *Usability Engineering*, Morgan Kaufmann, 1993 — umbrales de respuesta percibida (0.1 s, 1 s, 10 s).
5. ISO 80000-3, *Quantities and units — Part 3: Space and time*, edición vigente; NIST SP 811 para los factores de conversión.
6. Computers and Structures Inc., *SAP2000* y *ETABS*, documentación de interfaz — convenciones de modelado por retícula, niveles y edición tabular que esta skill replica. Es documentación de producto, no norma.
7. `docs/architecture.md`, `CLAUDE.md` y `docs/adr/ADR-0002-headless-gui-dep-split.md` del repositorio — capas, ejecución del análisis y trampas conocidas.
8. ISO 9241-110, *Ergonomics of human-system interaction — Part 110: Interaction principles*, edición 2020.

## Registro de verificación

- **Verificado (2026-02-14)** contra el código del repositorio: la conversión lógica→dispositivo, las tolerancias de 15 px y 18 px y el umbral de 3 px para distinguir clic de arrastre corresponden a `views/canvas3d/model_canvas.py`; el filtro de plano de trabajo usa `atol = 1e-6`; la prioridad nodo → barra → intersección está en `_handle_click`; la réplica y el espejo existen en `commands/transforms.py`; el estado de selección es `SelectionState` con señal `selectionChanged`; `core/units.py` define cuatro sistemas y documenta que la aplicación no convierte; existen `views/error_reporting.py` y `views/screen_fit.py`. Los valores de WCAG 2.2 (4.5:1, 3:1, 24×24 px CSS) y los factores de unidad (0.0254 m, 0.3048 m, 4448.2216152605 N por kip) son exactos por definición.
- **Pendiente**: los tres bloques de verificación pendiente —nivel de conformidad y paleta, mecanismo e idiomas de traducción, y comportamiento con escalado fraccionario—; el presupuesto de latencia (`data/ui/budgets.json`), que aún no existe; y el índice espacial del pick, hoy un barrido lineal.
- **Responsable de cerrar**: responsable de interfaz del proyecto, con una sesión de prueba en pantalla HiDPI de escalado fraccionario y una revisión de contraste sobre la paleta real.
