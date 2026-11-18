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
- Asignar materiales, secciones y patrones de carga desde diálogos.
- Correr análisis estáticos, modales, pushover, de espectro de respuesta y
  tiempo-historia, con progreso y cancelación (cada corrida va en un proceso
  aparte).
- Ver los resultados: deformada, modos, diagramas de esfuerzos, curvas pushover,
  historias en el tiempo, lazos de histéresis, tablas de pisos.
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
  basados en fuerza y en desplazamiento), barras, quads, cáscaras `ShellMITC4`,
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
  sentidos).
- **Diseño**: Design → Steel Frame Check verifica según **AISC 360-16** (LRFD o
  ASD) los miembros de perfiles W, M, S y HP —y canales, tees, ángulos de alas
  iguales, HSS rectangulares y circulares y tubos—: tracción, compresión (E3, E4,
  E7), flexión con pandeo lateral-torsional (F2, F3, F6, F7, F8, F9, F10), corte
  (G2 a G6) e interacción H1, sobre las combinaciones ya corridas; Design → Display Steel Ratios on Model
  pinta cada miembro según su razón D/C, y el reporte de cálculo imprime la
  verificación. Design → Storey Drift Check compara las
  derivas de piso con ASCE 7, NCh433 o Eurocódigo 8.
- **Importar y exportar**: dibujos DXF, modelos de
  [PORTICO](https://github.com/jpreyes/portico-core) (`.s3d`, escalados a las
  unidades que elijas), archivos de texto de SAP2000 (`.s2k` / `.$2k`, en ambos
  sentidos e incluidos los modificadores de propiedades por barra y los
  diafragmas rígidos, escritos desde el formato de tablas sin software de CSI;
  SAP2000 es
  marca de Computers and Structures, Inc.), scripts de OpenSeesPy, IFC y un
  reporte de cálculo HTML/PDF.

**La importación de S2K está en proceso:** las tablas que lee, las
aproximaciones y lo que no soporta están en
[docs/sap2000-import-status.md](docs/sap2000-import-status.md).

## Verificación

El [Manual de Verificación](docs/verification-manual.md) compara OpenSees Studio
con soluciones cerradas y publicadas —vigas Euler-Bernoulli y Timoshenko, 2D y
3D, reticulados, asentamientos, P-Δ, frecuencias, tiempo-historia, espectro, una
placa de cáscaras, el momento plástico de una sección de fibras y los ejemplos de
diseño de AISC— con su error relativo y su tolerancia. Se genera a partir de
corridas reales (`tools/verification_manual.py`), y la integración continua falla
si un caso se sale de su tolerancia o si el archivo quedó desactualizado.

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
