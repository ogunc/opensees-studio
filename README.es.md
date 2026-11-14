<p align="center">
  <img src="docs/logo.svg" alt="OpenSees Studio" width="640">
</p>

<p align="center">
  Una interfaz de escritorio moderna, al estilo de SAP2000, para
  <a href="https://openseespydoc.readthedocs.io/">OpenSeesPy</a> —
  hecha para ingenieros estructurales y sísmicos que quieren un entorno visual
  de modelación sin salir del ecosistema OpenSees.
</p>

<p align="center">
  <em>Estado: pre-alfa. En desarrollo activo. Las APIs y el formato de archivo cambiarán.</em>
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>Español</strong> ·
  <a href="docs/tutorials/README.es.md">Tutoriales</a> ·
  <a href="docs/verification-manual.md">Manual de Verificación</a>
</p>

---

![Ventana principal de OpenSees Studio](docs/screenshots/main_window.png)

> Este es un resumen en español. El [README en inglés](README.md) es la
> referencia completa: lista cada función, opción de menú y detalle de formato.

## Por qué

OpenSees es el solver de elementos finitos no lineal de referencia en ingeniería
sísmica, pero su interfaz nativa son scripts de Tcl/Python. OpenSees Studio le
agrega una interfaz visual para:

- Dibujar nodos, marcos, apoyos y cargas con clics sobre una grilla con snap.
- OSNAP sobre barras: punto medio, pie de perpendicular y punto más cercano,
  activables desde la barra de iconos de la izquierda, con marcador de color.
- Introducir cargas distribuidas, puntuales y trapezoidales en **X/Y/Z global**;
  cada barra las convierte a sus ejes locales, con una casilla **Ejes locales**
  para entrar directamente wx/wy/wz.
- Ver → Mostrar ejes locales dibuja la tríada x/y/z roja/verde/azul al lado del
  punto medio de cada barra, con los mismos ejes que usa el análisis.
- Medir la distancia entre dos nudos (Tools → Measure Distance, F7); el valor
  se copia al portapapeles.
- Asignar materiales, secciones y patrones de carga desde diálogos.
- Correr análisis estáticos, modales, pushover, de espectro de respuesta y
  tiempo-historia, con progreso y cancelación (cada corrida va en un proceso
  aparte).
- Ver los resultados: deformada, modos, diagramas de esfuerzos, curvas pushover,
  historias en el tiempo, lazos de histéresis, tablas de pisos.
- Con un diagrama de fuerzas o la deformada en pantalla, el clic derecho sobre
  un miembro abre sus diagramas de axial, cortante V2/V3, torsión, momento
  M2/M3, deformación absoluta/relativa y cargas aplicadas en una cuadrícula
  3 x 3, con los valores extremos etiquetados, selectores de resultados y
  unidades, y un cursor de distancia que informa el valor en cualquier sección.
- Correr muchos archivos en lote (**File → Run Batch…**, o
  `python -m opensees_studio.batch carpeta/ --jobs 4`): cada proyecto guarda
  sus resultados al lado y, al abrirlo después, se pueden ver sin volver a
  calcular. Se escribe un resumen `batch_summary.json` / `.csv`.
- Guardar el modelo en un único archivo JSON `.osmodel` que vuelve a cargarse
  idéntico (comparable en Git, programable desde Python).

Detrás de la interfaz, el mismo modelo `core` (Pydantic) se usa completo desde un
script o un notebook de Jupyter: la interfaz es una forma de usarlo, no la única.

## Qué funciona hoy (resumen)

- **Modelación**: grillas cartesianas y cilíndricas, nodos, masas añadidas y
  resortes de apoyo, marcos (elásticos,
  basados en fuerza y en desplazamiento), barras, quads, cáscaras (`ShellMITC4`,
  `ShellDKGQ` con rigidez de giro en el plano, la no lineal geométrica
  `ShellNLDKGQ` y los triángulos `ShellDKGT`/`ShellNLDKGT`; Assign → Area → Shell
  Formulation cambia entre ellas),
  elementos de longitud cero, restricciones, equalDOF, diafragmas rígidos, rigid
  links, aisladores (elastoméricos y de fricción), liberaciones, brazos rígidos,
  modificadores y puntos de inserción al estilo SAP2000.
- **Secciones no prismáticas**: una rama definida a partir de secciones
  elásticas con longitudes absolutas o relativas y variación lineal, parabólica o
  cúbica; al asignarla, cada miembro se subdivide en piezas elásticas (mínimo 12,
  por defecto 12) y la plantilla se puede editar después, refrescando las piezas
  ya construidas (su número de piezas se conserva, así que elige la subdivisión
  antes de asignar).
- **Materiales y secciones**: Steel01/02, Concrete01/02/04, Hysteretic y la
  biblioteca de materiales de OpenSees; secciones de fibras con editor; la
  biblioteca de perfiles AISC v16; el **asistente de secciones de hormigón
  armado** (Define → Concrete Section Wizard: rectangular, circular, T o L, barras
  φ o #, núcleo confinado según Mander, hormigón `Concrete02` o el cíclico
  `ConcreteCM` de Chang-Mander, sección de fibras y sección elástica con
  inercia fisurada ACI); **muros de hormigón armado** (Assign → Frame → RC Wall:
  macroelementos MVLEM en modelos 2D); el **diseñador de secciones** (Define → Section
  Designer: cualquier sección dibujada con comandos —`rect`, `circle`, `poly`,
  `ishape`, `tube`, `pipe`, `hole`…— o importada de un DXF, con sus propiedades
  y la constante de torsión de Saint-Venant calculada numéricamente, como sección
  elástica o de fibras); el Material Tester para ver la respuesta cíclica de un
  material.
- **Cargas y análisis**: patrones nodales, distribuidos, trapezoidales, puntuales,
  de superficie y de losa a vigas; peso propio; fuente de masa; casos estáticos,
  modales (deterministas), pushover, espectro de respuesta (CQC/SRSS) y
  tiempo-historia con registros PEER y escalamiento a espectro objetivo;
  combinaciones de carga; cargas de temperatura en marcos (ΔT uniforme y
  gradientes, Assign → Frame → Temperature Load); líneas de influencia y cargas móviles (un caso
  *InfluenceLine* recorre una carga unitaria por una cadena de miembros, y
  Display → Influence Line pasa un vehículo, p. ej. el camión HL-93, en ambos
  sentidos); construcción por etapas (un caso *Staged construction* construye
  grupos etapa a etapa, retira puntales y encofrados y aplica las cargas de cada
  etapa sobre el estado deformado de las anteriores; los nudos nuevos se
  construyen en su posición de diseño o siguiendo la estructura deformada; con
  la opción *time-dependent* el tiempo es la edad del hormigón en días y hay
  fluencia y retracción según el fib Model Code 2010, con el material
  `TDConcreteMC10` de Define → Concrete Creep & Shrinkage); cables de
  postensado (Assign → Frame → Tendon) como cargas equivalentes, con trazado
  parabólico y pérdidas por fricción, curvatura parásita y diferidas; resortes
  de suelo en pilotes (Assign → Frame → Pile Soil Springs: p-y de Matlock en
  arcilla y API en arena, t-z y q-z de punta, a partir del diámetro y los
  estratos).
- **Idioma de la interfaz**: Options → Language (en español: Opciones → Idioma)
  cambia menús, diálogos y botones entre inglés y español; las páginas de ayuda
  siguen en inglés.
- **Diseño de hormigón armado**: Design → Concrete Frame Check verifica según
  **ACI 318-19** todo miembro cuya sección sea de fibras de hormigón y barras
  (las del asistente de secciones, también si el análisis usa su gemela
  elástica fisurada): interacción P-M por compatibilidad de deformaciones con φ
  según la deformación neta de tracción, flexión biaxial (Bresler), corte con
  los estribos indicados, umbral de torsión, cuantía mínima y εt ≥ 0.004 en
  vigas, con los ratios pintados sobre el modelo.
- **Placas base y uniones apernadas**: Design → Base Plates verifica la placa y
  los pernos de anclaje de cada base de columna sobre las cargas de diseño (AISC
  Design Guide 1, ACI 318-19 capítulo 17): bases articuladas concéntricas,
  empotradas con su momento, voladizos según el tipo de columna (perfil I, HSS,
  tubo) y dimensionado del espesor de la placa. Design → Connections by Joint
  clasifica cada extremo de miembro (viga a ala o alma de columna, viga a viga
  maestra, diagonal, empalme, base), propone la conexión y verifica las placas de
  corte de los extremos simples (Manual AISC parte 10). Design → Base Plate & Anchors y
  Design → Bolted Connection (efecto palanca y grupos de pernos excéntricos)
  siguen como calculadoras que pueden leer las demandas de la reacción de un
  apoyo.
- **Bases de diseño y Método de Análisis Directo**: Design → Design Basis
  (AISC) fija el método (LRFD/ASD), el diseño por estabilidad (AISC 360
  capítulo C o apéndice 7), el sistema lateral de cada dirección con R, Ω0 y Cd
  de la tabla 12.2-1 de ASCE 7, y el acero de cada familia de perfiles (A36,
  A572 Gr. 50, A992, A588, A500 Gr. B/C, A1085, A53, con los valores de la
  tabla 2-4 del Manual AISC). Design → Direct Analysis Method convierte cada
  combinación LRFD de ASCE 7-16 en un caso de segundo orden: P-Delta en todos
  los marcos, rigidez ×0,8 (C2.3, τb = 1 con 0,001 α Yi) y las cargas ficticias
  `0,002 α Yi` de la gravedad factorizada de esa combinación; luego informa
  Δ2/Δ1 por piso (C2.2b(d)), y la verificación de acero lee esos casos con K = 1.
  Design → Built-Up Shapes define perfiles I soldados y vigas de alma llena a
  partir de sus placas (límites de ala con kc, F4/F5, corte del alma con
  rigidizadores). Design → Member Classification muestra los miembros físicos (elementos
  colineales de una misma sección), su rol y las longitudes no arriostradas Lx,
  Ly y Lb según sus puntos de arriostramiento; la verificación usa esas
  longitudes, así un miembro mallado conserva las reales.
- **Diseño**: Design → Steel Frame Check verifica según **AISC 360-16** (LRFD o
  ASD) los miembros de perfiles W, M, S y HP —y canales, tees, ángulos de alas
  iguales, HSS rectangulares y circulares y tubos—: tracción (D2), compresión
  (E3, E4, E7), flexión (F2–F10), corte (G2–G6) e interacción H1, sobre las
  combinaciones ya corridas, en 25 estaciones, con `Cb` del diagrama y ajustes
  por miembro de K, Lb, Cb, área neta y retraso; una **amplificación opcional
  B1 de P-δ** (AISC 360-16 C2.1b) cubre la curvatura que un análisis de primer
  orden deja fuera. Un **sistema sísmico** (AISC 341-22) añade la comprobación
  de esbeltez de la Tabla D1.1 con `Ry` y `Ca`, las juntas de SMF (E3.4a,
  panel zone J10.6 y placas de continuidad E3.6f), el diseño por capacidad
  F2.3 y los límites F2.5b de SCBF, y la cobertura F1.4/F1.5/F1.6 de OCBF.
  Diálogos separados editan las **conexiones RBS de AISC 358-22** (5.7 y
  conexión de alma 5.5), las **placas de unión de SCBF** (Whitmore, fluencia,
  pandeo, demandas F2.6c y soldadura), los **empalmes de columna de SCBF**
  (F2.6d) y los **chequeos de conexión del Capítulo J de AISC 360** (J2–J10).
  Assign → Frame → Local Axes gira la sección de un miembro 3D alrededor de su
  eje; la exportación e importación IFC conservan el giro. Design → Display
  Steel Ratios pinta cada miembro según su razón; Design →
  Generate Notional Loads genera el patrón `0.002 α Yi` de AISC 360 C2-1
  (α = 1,0 LRFD y 1,6 ASD); Design → Storey Drift Check compara las derivas
  amplificadas con ASCE 7, NCh433 o Eurocódigo 8. El reporte y la memoria de
  cálculo imprimen los chequeos de miembros, juntas, conexiones, placas,
  empalmes y Capítulo J. Los ajustes se guardan con el proyecto.
- **Importar y exportar**: dibujos DXF, modelos de
  [PORTICO](https://github.com/jpreyes/portico-core) (`.s3d`, escalados a las
  unidades que elijas), archivos de texto de SAP2000 (`.s2k` / `.$2k`, en ambos
  sentidos e incluidos los modificadores de propiedades por barra y los
  diafragmas rígidos, escritos desde el formato de tablas sin software de CSI;
  SAP2000 es
  marca de Computers and Structures, Inc.), scripts de OpenSeesPy, archivos
  Tcl de OpenSees (`.tcl`, incluidos los ejemplos del repositorio oficial;
  se interpretan variables, `expr`, `foreach`, `if`, `proc`, `source` y `for`,
  nunca se ejecutan), IFC y un reporte de cálculo HTML/PDF.

El giro de ejes locales se escribe en la exportación S2K; la importación S2K lo
aproxima a la orientación de sección más cercana (IFC lo conserva exacto).

**La importación de S2K está en proceso:** las tablas que lee, las
aproximaciones y lo que no soporta están en
[docs/sap2000-import-status.md](docs/sap2000-import-status.md).

## Verificación

El [Manual de Verificación](docs/verification-manual.md) compara OpenSees Studio
con soluciones cerradas y publicadas —vigas Euler-Bernoulli y Timoshenko, 2D y
3D, reticulados, asentamientos, P-Δ, frecuencias, tiempo-historia, espectro, una
placa de cáscaras (también con `ShellDKGQ`/`ShellDKGT`), la cubierta de
Scordelis-Lo, una columna construida piso a piso, la fluencia y retracción de una
columna a 10 000 días, un voladizo curvado en un cuarto de círculo por un momento
en la punta (grandes rotaciones), una viga y una columna de ACI 318-19, el momento plástico de una sección de fibras y los ejemplos de
diseño de AISC— con su error relativo y su tolerancia. Se genera a partir de
corridas reales (`tools/verification_manual.py`), y la integración continua falla
si un caso se sale de su tolerancia o si el archivo quedó desactualizado.

**Ningún cambio de resultados pasa en silencio.** Cada caso de cada proyecto de
`examples/` queda fijado por una huella (desplazamiento máximo por grado de
libertad, suma de reacciones, fuerza máxima en elementos, normas, períodos,
número de pasos) en `tests/data/results_snapshots.json`, y la integración
continua falla si alguno se mueve más de 1e-5 relativo. Una corrección que
cambia números a propósito se fija con
`python tools/results_snapshot.py --write --reason "..."`, que registra el antes
y el después en [docs/results-changes.md](docs/results-changes.md), y las notas
de versión lo anuncian en **Results changed**.

## Tutoriales

Recorridos paso a paso, en español e inglés: [docs/tutorials](docs/tutorials/README.es.md).

1. Diseño de un marco de acero según AISC 360-16.
2. Un edificio con losas rígidas: modos, espectro de respuesta y derivas.
3. Traer un modelo de PORTICO a OpenSees Studio.

## Instalación (sin Python)

Los paquetes de escritorio están en los
[releases](https://github.com/ogunc/opensees-studio/releases): descarga el archivo
de tu sistema, descomprímelo donde quieras y ejecuta `OpenSeesStudio` (o
`OpenSeesStudio.exe`). Trae su propio Python, Qt y VTK. El solver OpenSees tiene
su propia licencia y no viene incluido: instálalo una vez desde **Options →
Solver**, que descarga OpenSeesPy de PyPI después de que aceptes su licencia.

Sí viene incluido un segundo motor, **[PyNite](https://github.com/JWock82/PyNite)**
(licencia MIT): elígelo en **Options → Solver → Engine** para resolver casos
estáticos lineales y P-Delta de pórticos y cerchas elásticos sin descargar nada.
Da los mismos resultados que OpenSeesPy en esos modelos y rechaza, con un
mensaje, lo que no modela (materiales no lineales, shells, aisladores, casos
modales y transitorios…), que entonces necesita OpenSeesPy.

Descomprime la carpeta completa, no sólo el ejecutable. La primera vez el sistema
puede bloquearlo porque los binarios no están firmados: en macOS, clic derecho →
Abrir; en Windows, "Más información" → "Ejecutar de todas formas".

El paquete de Linux funciona en Ubuntu 22.04 o posterior, Linux Mint 21 o
posterior, Debian 12 y LMDE 6 (glibc 2.35 o más nueva), en x86-64.

## Instalación (desarrollo)

```bash
git clone https://github.com/ogunc/opensees-studio.git
cd opensees-studio

python -m venv .venv
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # Linux / macOS

pip install -e ".[gui,dev]"         # interfaz + herramientas + solver
```

Para usar el modelo sin interfaz (scripts, notebooks, servidores):
`pip install -e .` (sin solver) o `pip install -e ".[opensees]"` (con solver).

Se requiere **Python 3.12**: las ruedas de OpenSeesPy 3.8.0.0 lo exigen, y en
Windows `opensees.pyd` está enlazado contra `python312.dll`.

## Pruebas

```bash
pytest tests/unit          # lógica pura, milisegundos
pytest tests/gui           # pruebas con el event loop de Qt (pytest-qt)
pytest tests/integration   # corridas reales de OpenSeesPy
```

## Rendimiento y modelos grandes

El programa incluye un monitor de rendimiento opcional. Arranca con `--profile`
(o `OPENSEES_STUDIO_PERF=1`) y abre **Help → Performance monitor** para ver
los tiempos por etapa del importador S2K, la E/S de proyectos, el proceso de
análisis, el renderizador y los comandos deshacibles, además de bloqueos de la
interfaz y un `cProfile` de una acción. `--perf-json informe.json` guarda el
mismo informe al salir.

Para mediciones repetibles con modelos grandes sintéticos:

```bash
python tools/perf_bench.py --size large --profile
python tools/perf_bench.py --size xlarge --solver --cprofile
```

Consulta [`docs/performance-profiling.md`](docs/performance-profiling.md) para
los nombres de etapa, el formato JSON y cómo interpretar el informe.

## Marcadores relativos a la pantalla

Los nodos, apoyos, flechas de carga, reacciones y marcadores de masa se dimensionan
como un porcentaje de la altura del viewport, no como una fracción del modelo.
Mantienen su tamaño en pantalla al hacer zoom, y **Display → Display Options**
permite ajustar cada porcentaje; el tamaño del texto es un valor separado en
píxeles. Las masas nodales se dibujan como rombos morados cuando esa opción está
activa. Los tamaños y las visibilidades viajan con el proyecto.

Los releases de extremo se dibujan como puntos de color sobre las barras: violeta
para torsión, naranja para M2, rojo para M3 y amarillo para fijación parcial.
**View → Visibility → Releases** los muestra u oculta independientemente de las
barras de offset rígido de **Frame Assignments**.

## Mostrar, ocultar y aislar

**View > Hide Selected** (Ctrl+H) oculta la selección actual en el viewport
activo. **View > Isolate Selected** (Ctrl+Shift+I) muestra solo los elementos
seleccionados y sus nudos, o solo los nudos seleccionados; también está en el
menú contextual. **View > Show All Objects** restaura todo lo oculto y quita la
vista de línea de grilla. El cuadro de selección nunca toma objetos ocultos en
ese viewport: solo selecciona lo que realmente se dibuja.

## Chequeo de estabilidad

**Analyze → Check Model** (y la revisión que hace Run antes de correr) nombra
cada mecanismo por separado —la estructura o un grupo de nudos que se desliza o
gira como cuerpo rígido, un nudo que rota libremente, barras alineadas, un marco
que se desplaza lateralmente— con los nudos y elementos involucrados y qué hacer
(qué apoyo falta, qué liberación quitar, dónde arriostrar). **Show the motion**
anima el mecanismo elegido sobre el modelo.

**Analyze → Check Model Stability** captura la rigidez inicial como una matriz
dispersa CSR mediante `PythonSparse` de OpenSees; un modelo pequeño usa una
referencia densa y uno grande una búsqueda espectral dispersa desplazada tras
escalado diagonal. El informe separa mecanismos de rigidez negativa y mal
condicionamiento, indica cuándo la comprobación es parcial o no soportada y
lista los nodos y DOF que se mueven. Las componentes conexas sin apoyo ni resorte al
suelo se comprueban con una traslación de cuerpo rígido y se informan como mecanismos
parciales sin esperar al eigensolver disperso. El último valor del puntero CSR define
las entradas almacenadas aunque OpenSees informe un `nnz` mayor, y se aceptan buffers
enteros de 32 o 64 bits. El proceso hijo informa las fases, el menú
Analyze puede cancelarlo y la GUI aplica un límite blando de 300 s. Es un
chequeo del estado inicial, no un factor de pandeo ni una garantía para una
historia no lineal. Hay familias reproducibles con
`python tools/stability_bench.py --family frame --size 12` (o
`--family truss --mechanism`).

## Licencia

AGPL-3.0. Ver [LICENSE](LICENSE). OpenSeesPy es un programa aparte con su propia
licencia.
