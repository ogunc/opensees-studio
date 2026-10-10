---
name: results-reporting-and-compliance-audit
description: >-
  Define el post-proceso y la entrega de resultados: diagramas de esfuerzos
  continuos entre elementos, envolventes por combinación con su combinación
  gobernante, tablas filtrables, mapas de color de escala robusta ante nulos o
  cero, y exportación de resultados y de la memoria de cálculo. Fija la
  estructura del informe —procedencia de las entradas, hipótesis, normas y
  ediciones, resultados por combinación, matriz de cumplimiento demanda/capacidad
  con el artículo aplicable, conclusiones y limitaciones— y la auditoría
  automática con comprobaciones, tolerancia y evidencia. Úsala al generar un
  informe, cuando un diagrama presenta saltos en los nudos, cuando la escala de
  color se satura por un valor nulo, o cuando un dato normativo sin verificar
  obliga a marcar la entrega como preliminar.
metadata:
  track: platform
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [qa, ui]
---

# Post-proceso, informes y auditoría de cumplimiento

## Cuándo usar esta skill

- Hay que implementar o auditar el panel de resultados: tablas, diagramas, mapas de color y exportación.
- Un diagrama de momentos o cortantes presenta un **diente de sierra** en los nudos, o el valor dibujado no coincide con la tabla.
- Hay que construir una **envolvente** y responder qué combinación gobierna cada barra, estación y componente.
- El mapa de color sale uniforme, transparente o saturado porque un valor es nulo, cero o no finito.
- Hay que emitir la memoria de cálculo y la matriz de cumplimiento demanda/capacidad con el artículo aplicable.
- Un dato normativo no está verificado y la entrega debe salir marcada como **preliminar**, con trazabilidad hasta el archivo de datos y su cita.

**No usar** para la formulación de elementos finitos (→ `core/fem-formulation-core`), para generar el juego de combinaciones (→ `seismic/load-combinations-and-limit-states`), para la capacidad de los elementos (→ `design/concrete-aci318`, `design/steel-aisc360-341`) ni para decidir en qué capa vive un módulo nuevo (→ `platform/platform-architecture-and-services`).

## Alcance y límites

Cubre el post-proceso de resultados ya calculados: continuidad y estaciones de los diagramas, envolventes con trazabilidad, tablas y filtros, escalas de color, exportación, estructura del informe, auditoría automática de cumplimiento y marcado de preliminares.

No cubre el cálculo de la demanda ni de la capacidad —los consume ya calculados y solo los presenta y audita—, ni la persistencia de resultados (→ `platform/platform-architecture-and-services`), ni los valores de los coeficientes normativos, que viven en archivos de datos versionados (→ `codes/code-crosswalk-and-extension`).

Supuestos: los resultados existen en el almacén (`manifest.json` + HDF5 float64); las combinaciones ya están resueltas como casos; el proyecto declara su sistema de unidades. Unidades internas SI coherentes (N, m, kg, s, Pa); $g = 9.80665\ \text{m/s}^2$; las aceleraciones espectrales se publican en g solo cuando el código las publica así, declarándolo.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| `manifest.json` del almacén de resultados | sí | bloquear: no se post-procesa lo que no se resolvió |
| Instantánea (`.osmodel`) que produjo cada caso | sí | bloquear: sin ella el número no es reproducible |
| Sistema de unidades del proyecto | sí | bloquear: un número sin unidad no se reporta |
| `code_id` + edición de cada norma aplicada | sí para la matriz | la matriz sale **bloqueada**, no vacía |
| Registro de comprobaciones (`checks`) del código | sí para la matriz | no se emite veredicto |
| Archivo de datos de cada coeficiente, con `source` y `verified_on` | sí | el veredicto se marca **preliminar** |
| Geometría, ejes locales y cargas distribuidas del elemento | sí para diagramas | sin geometría se omite el elemento; sin carga repartida el diagrama se marca lineal |

Un dato faltante **nunca** se sustituye por un valor típico: se propaga como `null` más un aviso, y si afecta a un veredicto, el veredicto es `bloqueado`.

## Fundamento y formulación

### 1. Continuidad entre elementos

El solver publica `localForce` por elemento. En 3D son 12 componentes (N y N·m), en el orden $[N_i, V_{y,i}, V_{z,i}, T_i, M_{y,i}, M_{z,i}, N_j, V_{y,j}, V_{z,j}, T_j, M_{y,j}, M_{z,j}]$; en 2D son 6, $[N_i, V_{y,i}, M_{z,i}, N_j, V_{y,j}, M_{z,j}]$; un elemento de celosía solo publica la componente axial.

El valor **dibujado** no es el valor crudo en el extremo $j$: la convención del solver orienta las fuerzas del extremo $j$ en sentido opuesto a las del extremo $i$, y dibujarlas sin cambio produce el salto artificial en el nudo.

$$d_i^{(e,c)} = f_k^{(e,c)}(i), \qquad d_j^{(e,c)} = -\,f_k^{(e,c)}(j)$$

$d$: valor dibujado (N o N·m); $f_k$: componente $k$ cruda del `localForce`; $e$: elemento; $i, j$: nudos extremos; $c$: combinación. La continuidad se comprueba con el residuo de equilibrio nodal, no comparando escalares de elementos con ejes locales distintos:

$$\mathbf{r}_n = \sum_{e \ni n} \mathbf{R}_e^{\top} \mathbf{f}_e^{(n)} - \mathbf{P}_n, \qquad \|\mathbf{r}_n\|_\infty \le \varepsilon_r \max\!\big(1, \|\mathbf{P}_n\|_\infty\big)$$

$\mathbf{R}_e$: rotación del elemento (adimensional); $\mathbf{P}_n$: carga aplicada en el nudo (N o N·m); $\varepsilon_r = 10^{-6}$ (relativo). Un residuo mayor es error de extracción, no de discretización.

### 2. Estaciones: el extremo no es el máximo

`localForce` solo publica los dos extremos. Con carga uniforme $w$ (N/m) perpendicular al eje, en un elemento de longitud $L$ (m) y abscisa $x$ (m):

$$M(x) = M(0) + V(0)\,x - \frac{w\,x^2}{2}, \qquad M_{\max} = M(0) + \frac{V(0)^2}{2\,w}\ \ \text{en}\ \ x^* = \frac{V(0)}{w}$$

válido solo si $0 < x^* < L$; si no, el máximo está en un extremo. $M$: momento (N·m); $V$: cortante (N); $w$: carga repartida (N/m), con el signo de la convención local declarada. Interpolar linealmente entre extremos **subestima** la envolvente en vigas con carga repartida.

### 3. Envolvente por combinación

Para un conjunto de combinaciones $C$, una componente y una estación fija:

$$E^{+} = \max_{c \in C} v_c, \qquad E^{-} = \min_{c \in C} v_c, \qquad c^{*} = \arg\max_{c \in C} \big|v_c\big|$$

$v_c$: valor de la componente en la combinación $c$ (N o N·m); $c^{*}$: combinación gobernante. Reglas que la fórmula no impone y el código sí:

- La envolvente es por **estación, componente y elemento**. Tomar $E^{+}$ en $i$ y $E^{-}$ en $j$ de combinaciones distintas produce un par $(i,j)$ físicamente inexistente.
- Las acciones revertibles (viento, sismo) aportan dos ramas de signo; $C$ debe contenerlas ya generadas.
- La relación demanda/capacidad **no** se envuelve sobre las demandas: cuando la capacidad depende del axil (interacción), el máximo de $D/C$ no ocurre en la combinación del máximo de $D$. Se calcula $D/C$ por combinación y se envuelve el resultado.

### 4. Escala de color robusta

Sea $V = \{v_1,\dots,v_N\}$ el campo a colorear (N, N·m, m o rad). Los valores no finitos ($\texttt{NaN}$, $\pm\infty$) se excluyen del rango, se cuentan y se reportan con el gráfico. Con $V_f$ el subconjunto finito y $q_p$ su percentil $p$:

$$s = \max\big(|q_{p}|, |q_{1-p}|\big), \qquad \text{escala} = [-s,\ +s], \qquad p = 0.02$$

La escala es **simétrica respecto de cero** en campos con signo, de modo que el cero cae siempre en el color neutro. Guardas obligatorias:

- $V_f = \varnothing$: color plano y leyenda «sin datos»; nunca se divide por el rango.
- $s = 0$ o $s < \epsilon\,v_{ref}$ (rango degenerado): color plano y leyenda «sin variación», con $\epsilon = 10^{-12}$ y $v_{ref} = 1$ en las unidades del campo.
- El recorte por percentil se declara en la leyenda (rango efectivo y número de valores fuera de escala); un recorte silencioso es un resultado falso.

### 5. Cifras y veredictos

Se conserva el `float64` completo; el redondeo es **solo de presentación** y la exportación escribe la forma decimal más corta que reconstruye el mismo `double`. El veredicto se calcula sobre el valor sin redondear:

$$D/C = \frac{D}{C}, \qquad \text{cumple} \iff D/C \le 1.0$$

$D$: demanda (N, N·m o adimensional); $C$: capacidad en la misma unidad. La banda $D/C \in (1.0,\ 1.0+\tau]$, con $\tau = 0.005$ (adimensional), se reporta como «cumple (banda numérica)» y **nunca** como «cumple»: $\tau$ es tolerancia de implementación, no margen normativo, y viaja declarada en el informe.

### 6. Preliminares y trazabilidad

Estado de cada veredicto: `verificado`, `preliminar` o `bloqueado`. Se degrada a `preliminar` si algún dato normativo consumido carece de `source`, carece de `verified_on` o tiene `verified: false`; y a `bloqueado` si el dato falta. El estado se propaga a la cabecera del informe, a cada tabla, a cada gráfico (marca de agua) y a cada archivo exportado. Cadena de trazabilidad de todo número reportado:

$$\text{número} \to (c^{*}, \text{caso}) \to \text{instantánea (huella)} \to (\text{elemento/nudo}, \text{componente}, \text{estación}, \text{paso}) \to (\text{archivo de datos}, \text{clave}, \text{cita}, \text{verified\_on})$$

### 7. Estructura del informe

1. **Datos de entrada y procedencia**: proyecto, instantánea y su huella, unidades, fecha, autor, versión del programa.
2. **Hipótesis**: linealidad, diafragma, longitud de rigidez, masa, amortiguamiento, y qué se despreció.
3. **Normas y ediciones aplicadas**: `code_id`, edición y estado de verificación de cada archivo de datos consumido.
4. **Resultados por combinación**: tablas filtrables por caso y envolvente con la combinación gobernante.
5. **Matriz de cumplimiento**: comprobación, demanda, capacidad, $D/C$, artículo, tolerancia, veredicto y evidencia.
6. **Conclusiones y limitaciones**: solo lo que la evidencia sostiene, más los avisos activos y los datos sin verificar.

## Procedimiento

1. Cargar `manifest.json` y reconstruir cada caso; propagar al informe la parada temprana y cualquier paso no convergido.
2. Resolver la instantánea y cotejar su huella con la del resultado; si no coincide, abortar el informe.
3. Extraer los diagramas por componente y elemento con la inversión del extremo $j$; muestrear estaciones de vano si hay carga repartida.
4. Calcular el residuo de equilibrio nodal por combinación; si supera $\varepsilon_r$, marcar el caso como inconsistente y excluirlo de la envolvente.
5. Construir la envolvente por estación, componente y elemento, registrando $c^{*}$ en cada punto.
6. Resolver el rango robusto de cada campo escalar y decidir la escala (simétrica, recortada, plana o sin datos) **antes** de dibujar.
7. Ejecutar el registro de comprobaciones combinación por combinación, sin redondear, y asignar veredicto y artículo.
8. Envolver $D/C$ y conservar la combinación gobernante de cada comprobación.
9. Degradar a `preliminar` o `bloqueado` según el estado de los datos normativos consumidos.
10. Renderizar el informe, adjuntar la evidencia (tabla, gráfico, cita) y escribir todo con la escritura atómica del proyecto.
11. Reabrir el informe generado y verificar que cada número resuelve a su cadena de trazabilidad; si no, fallar la generación.

## Implementación en la plataforma

```python
# core/reporting/envelope.py      (core puro: sin Qt, sin openseespy)
def envelope_series(values: dict[int, "np.ndarray"],   # combination_id -> valores por estación (N, N·m)
                    stations: "np.ndarray") -> "EnvelopeResult":
    """E+, E- y combinación gobernante por estación; nunca cruza pares (i, j)."""

def span_maximum(m_i: float, v_i: float, w: float, length: float) -> tuple[float, float]:
    """(M_max, x*) para carga uniforme w (N/m); x* recortado a [0, L]."""

# core/reporting/color_scale.py
def robust_range(values: "np.ndarray", *, percentile: float = 0.02,
                 symmetric: bool = True) -> "ColorRange":
    """Rango finito y recortado; expone n_no_finitos y n_fuera_de_escala."""

# core/reporting/compliance.py
def evaluate(registry: "CheckRegistry", results: "CaseSet",
             combination_id: int) -> list["CheckResult"]:
    """CheckResult: demand, capacity, ratio, verdict, article, data_files, verified."""
# services/report_builder.py       (puede importar core y el almacén de resultados)
def build_report(manifest: Path, project: Project, registry: "CheckRegistry") -> "ReportDocument": ...

def export_report(report: "ReportDocument", out_dir: Path,
                  formats: Sequence[str]) -> list[Path]:
    """HTML/CSV/JSON con cabecera de estado y huella de la instantánea."""
```

Reglas de arquitectura:

- El núcleo de cálculo vive en `core/`: sin Qt, sin OpenSeesPy, sobre `numpy`. Envolvente, escala y comprobaciones son funciones puras, verificables sin GUI ni solver.
- El solver solo se usa desde `services/`: `services/report_builder.py` consume el almacén HDF5 y produce un `ReportDocument` de datos; no conoce Qt.
- `views/docks/results_panel.py` solo presenta: su `ResultTableModel` redondea para mostrar y nunca decide un veredicto.
- `views/canvas3d/diagram_renderer.py` conserva la guarda existente `if data.abs_max <= 0.0: return`; la escala llega resuelta desde `core/reporting/color_scale.py` y no se recalcula en la vista.
- Las marcas de agua de preliminares se derivan de `ReportDocument.verification_state`; la vista no las infiere.
- Todo archivo se escribe con la escritura atómica de `services/persistence`, igual que proyectos e instantáneas.

## Datos normativos

Esta skill no publica ningún coeficiente (`jurisdiction: agnostic`, `edition: "n/a"`): consume datos normativos ajenos y exige su contrato.

| Dato consumido | Origen | Contrato |
|---|---|---|
| Tolerancia de veredicto $\tau$ | decisión de implementación | no es normativa; se declara en el informe |
| Factores $\phi$, $\Omega$, límites de deriva | skills de `codes/` y `design/` | se citan; aquí no se recalculan |
| Coeficientes de combinación | `seismic/load-combinations-and-limit-states` | llegan generados con su cita |
| Capacidades de sección | `data/` versionado + skill de diseño | `source`, `edition`, `table`, `verified_on` |

> ⚠️ VERIFICAR: la sección exacta de ASCE 7-22 que enumera el contenido de los documentos de construcción (base de diseño estructural) no se pudo confirmar contra el estándar impreso. Se comprueba en ASCE 7-22, capítulo 1. Mientras tanto el programa **no** cita un número de sección: lee la cita de `data/<code>/<edition>/report_requirements.json`, con campos `source` y `verified_on`.

> ⚠️ VERIFICAR: los requisitos de contenido, firma y sellado de la memoria de cálculo son competencia de la autoridad local y no son uniformes entre jurisdicciones. Se comprueban en la normativa de la autoridad que aprueba el proyecto. El programa lee la lista de requisitos del archivo de datos versionado y no incrusta ninguno en el código.

> ⚠️ VERIFICAR: el número de cifras significativas obligatorio en los documentos de construcción no se pudo confirmar para ninguna edición. Se comprueba en el capítulo de documentos de construcción del código aplicable. Hasta entonces el programa publica el valor completo (round-trip) y la cifra mostrada es una preferencia de interfaz configurable.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Continuidad entre elementos | $M_{z,j} = -50000$ N·m crudo; $d_j^{(A)} = d_i^{(B)} = +50000$ N·m | dibujado $+50000$ N·m; sin salto en el nudo | 1e-9 rel | convención `localForce` y cálculo a mano |
| Equilibrio nodal | nudo con 3 elementos, $P_x = 1000$ N | $\lvert\mathbf{r}_n\rvert_\infty \le 10^{-3}$ N | 1e-6 rel | estática |
| Máximo de vano | $M(0)=0$, $V(0)=20000$ N, $w=10000$ N/m, $L=4$ m; y $x^*=5\ \text{m} > L$ | $M_{\max}=20000$ N·m en $x^*=2$ m; fuera del vano, máximo en el extremo $j$ | 1e-6 rel / 1e-9 | estática |
| Envolvente | $\{+120000,\ -80000,\ +200000\}$ N·m | $E^{+}=200000$, $E^{-}=-80000$, $c^{*}$ = la 3.ª | exacta | cálculo a mano |
| Envolvente no separable | $E^{+}$ en $i$ y $E^{-}$ en $j$ de combinaciones distintas | prohibido: se reporta por estación | — | regla §3 |
| $D/C$ | $D = 250000$ N, $C = 200000$ N | $D/C = 1.25$ → «no cumple» | 1e-3 rel | fórmula implementada |
| Banda numérica | $D/C = 1.004$, $\tau = 0.005$ | «cumple (banda numérica)» | exacta | regla §5 |
| Envolver $D/C$ vs $D$ | capacidad dependiente del axil | el máximo de $D/C$ no coincide con el de $D$ | 1e-3 rel | cálculo a mano |
| Escala degenerada | $\{0, 0, 0, 10^{-12}\}$ | color plano, sin división por cero | sin NaN/Inf | prueba unitaria |
| Escala con valor extremo | 100 valores en $[0,1]$ y uno de $10^{6}$ | recorte al percentil 98 + aviso contado | exacta | prueba unitaria |
| Valores nulos | 97 finitos y 3 `NaN` | rango sobre 97; `n_no_finitos = 3` reportado | exacta | prueba unitaria |
| Exportación | tabla con el valor $1/3$ | `repr` reconstruye el mismo `double` | round-trip | `services/result_tables.py` |
| Trazabilidad | cualquier número del informe | resuelve a caso, combinación e instantánea existentes | — | inspección automática |
| Preliminar | dato con `verified: false` | cabecera y archivos marcados `preliminar` | — | regla §6 |

Además: contraste de la envolvente de un pórtico de dos vanos contra el cálculo manual de las combinaciones gobernantes (1 % relativo en fuerzas internas; 1 % o 1e-6 m en desplazamientos, según la guía de estilo).

## Errores frecuentes y trampas

1. **Envolver los extremos por separado**: $E^{+}$ en $i$ y $E^{-}$ en $j$ de combinaciones distintas genera un diagrama que ningún estado de carga produce.
2. **Envolver $D/C$ en vez de la demanda**: con capacidad dependiente del axil, el máximo de la relación no está en la combinación del máximo de $D$.
3. **No invertir el signo del extremo $j$**: diente de sierra en cada nudo y valores duplicados en la tabla.
4. **Comparar componentes entre elementos con ejes locales distintos**: una viga rotada 90° intercambia $M_y$ y $M_z$; el escalar no es comparable.
5. **Dibujar un elemento de celosía con el layout de frame**: los índices de cortante y momento no existen y devuelven cero silencioso en vez de un aviso.
6. **Confundir el vector de 6 componentes (2D) con el de 12 (3D)**: se lee el momento equivocado sin ningún error visible.
7. **Interpolar linealmente entre extremos con carga repartida**: subestima el máximo de vano y con él la envolvente.
8. **Calcular el rango de color incluyendo el valor nulo o cero**: el modelo sale de un solo color, o el rango degenerado divide por cero.
9. **Dejar que `NaN` entre en `min`/`max`**: propaga, el rango sale `NaN` y el gráfico queda transparente sin error.
10. **Redondear la tabla y comparar después contra el límite**, o exportar con formato de seis cifras: el veredicto difiere del valor calculado y el CSV no reconstruye el resultado, lo que hace imposible la auditoría posterior.
11. **Perder los avisos del solver** (parada temprana, paso no convergido): se emite un informe «limpio» de un análisis incompleto.
12. **Marcar `verificado` un resultado que consumió un dato con `verified: false`**, o `ready` una entrega con `VERIFICAR` abiertos.
13. **Escala no simétrica en un campo con signo**: el cero no cae en el color neutro y la lectura del signo se invierte.

## Interfaz de salida

- **Cabecera de estado y avisos**: `verificado` | `preliminar` | `bloqueado`, con la lista de datos normativos sin verificar y su motivo, más los avisos activos del análisis y del post-proceso, sin descartar ninguno.
- **Tablas filtrables** con la unidad de cada columna y el caso y la combinación de origen; el filtro no altera el valor exportado.
- **Envolventes y diagramas**: $E^{+}$, $E^{-}$ y la combinación gobernante por estación, componente y elemento; diagramas continuos con la escala declarada (máximo dibujado, factor de escala, estaciones de vano muestreadas).
- **Mapas de color** con leyenda que declare rango, simetría, percentil de recorte y cuántos valores quedaron fuera o no eran finitos.
- **Matriz de cumplimiento**: comprobación, demanda y capacidad con unidades, $D/C$ sin redondear, artículo aplicable, tolerancia declarada, veredicto y evidencia que lo sustenta.
- **Trazabilidad** de cada número: caso, combinación, instantánea con huella, elemento/nudo, componente y estación, archivo de datos con cita y `verified_on`.
- **Exportación** de resultados (CSV/JSON, round-trip) y del informe (documento con las seis secciones de §7), todos con la marca de estado.

## Referencias

1. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures* — capítulo 1 (base de diseño y documentos de construcción).
2. OpenSeesPy 3.8.0.0, documentación de la respuesta `localForce` de `elasticBeamColumn` y `forceBeamColumn` — convención de signos por extremo.
3. `docs/architecture.md` — arquitectura MVVM y capa de servicios; `CLAUDE.md` — convenciones y trampas conocidas (inversión del extremo $j$, guarda `abs_max`, escritura atómica).
4. Skill `platform/platform-architecture-and-services` — contratos de capa, ciclo de vida de la ejecución y persistencia.
5. Skill `seismic/load-combinations-and-limit-states` — envolventes y trazabilidad de la combinación gobernante.
6. Skill `codes/code-crosswalk-and-extension` — contrato de los archivos de datos normativos versionados.
7. Skill `core/fem-verification-and-benchmarks` — tolerancias y casos de contraste del núcleo.

## Registro de verificación

- **Verificado**: la inversión del signo del extremo $j$ y la guarda `abs_max <= 0` corresponden al extractor de diagramas y al renderizador del proyecto; el contrato del almacén (`manifest.json` + HDF5 float64) y la escritura atómica de `services/persistence`; la exportación round-trip de `services/result_tables.py`; las tolerancias de la guía de estilo de la biblioteca.
- **Pendiente**: la cita exacta de ASCE 7-22 capítulo 1 sobre documentos de construcción; los requisitos de firma y sellado por jurisdicción; las cifras significativas obligatorias. Los tres están abiertos como `VERIFICAR`, y por eso la skill queda en `draft`.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia licenciada del código aplicable y el listado de requisitos de la autoridad local.
