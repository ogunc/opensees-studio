---
name: performance-and-scaling
description: >-
  Guía el rendimiento y la escalabilidad del motor de análisis estructural:
  renumeración de GDL (reverse Cuthill-McKee y mínimo grado aproximado), formato
  disperso CSR, costo real de Cholesky/LDLT según ancho de banda y perfil,
  estimación de memoria de secciones de fibra, umbrales de tamaño para elegir
  solver denso, en banda o disperso directo, ensamblaje con localidad de caché,
  perfilado con cProfile y py-spy, presupuestos de tiempo por etapa y escritura
  de resultados grandes por bloques fuera de memoria. Úsala cuando un modelo
  tarda demasiado o agota la memoria, al elegir numberer y system en un caso de
  análisis, al presupuestar una malla grande o al perfilar el proceso hijo.
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [analysis]
---

# Rendimiento y escalabilidad del motor

## Cuándo usar esta skill

- Un caso tarda minutos u horas y hay que decidir **dónde** se va el tiempo antes de tocar código; o el proceso hijo muere por memoria al factorizar, no al ensamblar.
- Hay que elegir `numberer` y `system` para un caso: en este repositorio `Plain`/`RCM`/`AMD` y `BandGeneral`/`BandSPD`/`ProfileSPD`/`SparseGeneral`/`UmfPack`/`FullGeneral`.
- Se dimensiona un modelo nuevo (malla de sólidos, edificio de 40 pisos, 20 000 pasos de historia de respuesta) y hay que saber si cabe en la máquina.
- Hay que perfilar el CLI de análisis o el ensamblaje propio, o los resultados de una THA no caben en RAM y hay que escribirlos por bloques.

**No usar** para la formulación de elementos o constitutivas (→ `core/fem-formulation-core`, `core/fem-materials-and-sections`), la convergencia no lineal (→ `core/nonlinear-and-solver-strategies`) ni la arquitectura de capas (→ `platform/platform-architecture-and-services`).

## Alcance y límites

Cubre: grafo de GDL, reordenamiento, almacenamiento disperso, costo y memoria de la factorización, presupuesto de memoria de secciones de fibra, criterios de selección de solver, ensamblaje, perfilado, presupuestos de tiempo por etapa y resultados fuera de memoria.
No cubre: precondicionadores iterativos ni multigrid (el motor solo ofrece solvers directos), paralelismo entre máquinas, GPU, ni la elección del método de autovalores (→ `core/modal-and-time-history`).
Supuestos: álgebra estática lineal $K u = F$ con $K$ simétrica; ensamblaje en doble precisión; 6 GDL/nodo en barras o 3 GDL/nodo en sólidos; un solo proceso de análisis por caso.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| GDL libres y restringidos $n$ | sí | contarlos del modelo; no estimarlos |
| Conectividad elemento–nodo | sí | se deriva del modelo: es la fuente del grafo |
| GDL/nodo y MPC o diafragma rígido | sí | sin esto la estimación de $nnz$ es inválida |
| Presupuesto de memoria del proceso hijo | sí | valor por defecto documentado y visible en el informe |
| Presupuesto de tiempo por etapa | no | se lee de `data/perf/budgets.json`; si no existe, solo se reporta |
| Pasos y canales de la THA | solo en THA | bloquear: define el tamaño del almacén |
| Fibras por sección e integración | solo con fibras | bloquear si hay `FiberSection` |

Regla: nunca se bloquea por falta de presupuesto **de tiempo**; sí por falta de un dato que cambia el resultado.

## Fundamento y formulación

### 1. Grafo de GDL, ancho de banda y perfil

Con patrón simétrico, $b_i = \max\{j-i : A_{ij}\neq 0\}$ para $j\ge i$, y

$$b = \max_i b_i, \qquad P = \sum_{i=1}^{n} b_i, \qquad M_{sky} \approx 8\sum_{i=1}^{n}(b_i+1)\ \text{bytes}$$

La permutación $u' = Pu$ no cambia la solución, solo el costo. Dos objetivos **no equivalentes**: RCM minimiza $b$; AMD minimiza el relleno (*fill-in*).

### 2. Reverse Cuthill-McKee

Sobre el grafo no dirigido $G=(V,E)$: (1) elegir un nodo pseudoperiférico con dos BFS encadenadas —raíz de grado mínimo, luego el último visitado—; (2) BFS desde esa raíz encolando en cada nivel los vecinos no numerados en orden creciente de grado; (3) invertir el vector de orden, lo que reduce el perfil sin empeorar $b$. Costo $O(n+nnz)$, despreciable frente a la factorización. En una cadena RCM reproduce el orden natural ($b=1$); en dos subdominios unidos por una arista los agrupa y $b\approx\max(|V_1|,|V_2|)$.

### 3. Almacenamiento disperso CSR

Solo la mitad triangular: $M_{CSR} = 8\,nnz + 4\,nnz + 4(n+1) = 12\,nnz + 4(n+1)$ bytes con índices de 32 bits. Si $nnz \ge 2^{31}$ hay que pasar a 64 bits y $M = 16\,nnz + 8(n+1)$: comprobarlo **antes** de factorizar. Para un pórtico 3D, cada elemento aporta cuatro bloques $6\times6$, luego $nnz \approx 36(N_{nodo} + 2N_{el})$, válido **sin** diafragma rígido ni MPC: un diafragma que une $m$ nodos añade $\approx 18m^2$ entradas por piso y puede dominar el patrón.

### 4. Cholesky, LDLT y su costo

Con $K=LL^{\mathsf T}$ (definida positiva) o $K=LDL^{\mathsf T}$ (admite autovalores negativos de rigidez degradada):

$$\text{flops}=\sum_{j=1}^{n}|L_j|^2, \qquad \text{flops}_{banda}\approx\frac{1}{3}\sum_{i=1}^{n}b_i^2 \le \frac{1}{3}\,n\,b^2, \qquad M_L \approx 8\,n\,(b+1)\ \text{bytes}$$

donde $|L_j|$ es el número de no ceros de la columna $j$ de $L$. Regla operativa: **duplicar $b$ cuadruplica el trabajo**. Un solo nodo que une dos alas puede fijar $b$ para todo el modelo; por eso $b$ o $P$ se miden antes y después de renumerar y se reporta la razón. En solver disperso el relleno lo gobierna el árbol de eliminación, no la banda, y AMD lo reduce por grado aproximado mínimo. Ningún orden es óptimo para todos los modelos: la decisión es empírica y se registra con el caso.

### 5. Memoria de secciones de fibra

Cada fibra guarda estado (tensión, deformación, tangente y variables de historia): $M_{fib} = n_{sec}\,n_{ip}\,n_{fib}\,\kappa\cdot 8$ bytes, con $n_{sec}$ secciones, $n_{ip}$ puntos de integración por elemento, $n_{fib}$ fibras y $\kappa$ el número de `double` de estado por fibra.

> ⚠️ VERIFICAR: el valor exacto de $\kappa$ (cuántos `double` de estado e historia guarda el solver por fibra en OpenSeesPy 3.8.0.0, y si el estado es por fibra o por punto de integración de sección) no se pudo confirmar contra la fuente. Se comprueba midiendo RSS con un modelo de fibras instrumentado y comparando con $M_{fib}$; hasta entonces $\kappa$ se lee de `data/perf/fiber_state.json` con `source` y `verified_on`, nunca del código.

### 6. Denso, en banda o disperso

El denso cuesta $M_{dense}=\eta\cdot 8n^2$ con $\eta\approx3$ (matriz, copia reducida del problema generalizado y espacio de trabajo de LAPACK), con topes $n_{mem}=\sqrt{M_{presupuesto}/(8\eta)}$ y $n_{tiempo}=\sqrt[3]{3\,t_{presupuesto}\,r_{pico}}$, con $r_{pico}$ en flops/s **efectivos**, no de pico teórico. Con 2 GiB y $\eta=3$, $n_{mem}\approx 9.5\times10^{3}$; el tope de tiempo suele mandar antes.

| Régimen | $n$ (GDL libres) | Almacenamiento | System | Nota |
|---|---|---|---|---|
| Muy pequeño | $\le 5\times10^{2}$ | denso | `FullGeneral` | el umbral denso del repositorio aplica solo a modales |
| Pequeño–medio | $5\times10^{2}$–$2\times10^{4}$ | banda o disperso | `BandGeneral`/`BandSPD`/`SparseGeneral` | `*SPD` exige definida positiva: falla con fibras degradadas |
| Grande | $>2\times10^{4}$ | disperso | `SparseGeneral`/`UmfPack` | AMD/RCM y medición obligatoria de $nnz$ y memoria |
| Iterativo | — | — | — | no ofrecido hoy; exige un `system` nuevo en `services/` |

### 7. Ensamblaje, localidad de caché y paralelismo

Un elemento de pórtico suma un bloque $12\times12$ (144 sumas, $\approx 144\times12$ bytes de tráfico): el ensamblaje está **limitado por memoria**, no por FLOPs. Precalcular el mapa GDL locales → índices CSR una vez por malla en un arreglo `int32` contiguo, nunca resolverlo con `dict` dentro del bucle; acumular con `np.add.at` o `np.bincount`, porque la indexación avanzada `K[idx] += Ke` no acumula duplicados. Paralelizar por partición del conjunto de elementos con un búfer por hilo y fusión determinista: el orden de suma en punto flotante cambia el último bit, y una partición no determinista rompe la regresión aunque el resultado sea correcto.

### 8. Perfilado y presupuesto de tiempo

`cProfile` sobre el CLI del análisis —no sobre la GUI: el solver corre en otro proceso— da reparto relativo, no tiempos absolutos ($2$–$5\times$ de sobrecarga). `py-spy record --native --rate 100 --pid <pid>` ve además el tiempo nativo del solver, invisible a `cProfile`: `ops.analyze()` es una caja opaca. Instrumentar el *runner* con marcas por etapa y comprobar que su suma cierra con el total.

| Etapa | Reparto esperado | Cómo se reduce |
|---|---|---|
| Ensamblaje | 5–15 % | vectorizar, eliminar `dict`, precomputar índices |
| Factorización | 50–75 % | renumerar (RCM/AMD), no densificar, revisar $b$ |
| Resolución / backsolve | 2–5 % | reutilizar la factorización entre casos con la misma $K$ |
| Autovalores | variable | umbral denso/ARPACK (→ `core/modal-and-time-history`) |
| Post-proceso y escritura | 5–20 % | escritura por bloques, no acumular pasos en RAM |

> ⚠️ VERIFICAR: el reparto anterior es un **orden de magnitud a calibrar**, no una medición del motor. La línea base medida por etapa (modelo, tamaño, numberer, system, fecha, máquina) se guarda en `data/perf/budgets.json` con su `source`; el programa compara contra ese archivo y no contra constantes incrustadas.

### 9. Resultados fuera de memoria

$M_{res}=8\,n_{pasos}\,n_{canales}$ bytes: $5\times10^{3}$ pasos por $60\times10^{3}$ canales son 2.4 GB. Escribir en un dataset HDF5 fragmentado con `maxshape=(None, n_canales)` y `dtype=float64`, añadiendo un bloque por paso o cada $k$ pasos; dimensionar el *chunk* por patrón de acceso apuntando a $\sim1$ MiB por fragmento (caché de fragmentos por defecto de HDF5), porque un *chunk* grande amplifica la lectura y uno diminuto añade metadatos; evitar `gzip` en la ruta crítica (usa CPU y es la etapa a acortar) y dejar combinación, edición normativa, unidades, solver y numberer en el `manifest.json`, no dentro del dataset.

## Procedimiento

1. Contar $n$ y construir el grafo de acoplamiento; calcular $nnz$ (o su cota) y $M_{CSR}$.
2. Estimar $M_{fib}$ si hay fibras, leyendo $\kappa$ del archivo de datos.
3. Clasificar el modelo con la tabla de §6, elegir `system` y comparar $n$ con $n_{mem}$ y $n_{tiempo}$.
4. Medir $b$ o $P$ en orden natural, aplicar RCM, remedir, y aplicar AMD y remedir si el solver es disperso; registrar las tres cifras.
5. Ensamblar con índices precomputados y comprobar simetría y ausencia de filas vacías (un GDL sin rigidez es un mecanismo, no un problema de rendimiento).
6. Factorizar y resolver con marcas por etapa; registrar el tamaño real de $L$ y el pico de memoria.
7. Escribir resultados por bloques y liberar los pasos ya escritos.
8. Emitir el informe de rendimiento y avisar de cada etapa que exceda su presupuesto.
9. Ante cualquier cambio de código, repetir con la misma línea base y el mismo numberer: comparar casos distintos no significa nada.

## Implementación en la plataforma

```python
# src/opensees_studio/core/performance/ordering.py  (core puro: sin Qt, sin openseespy)
def build_dof_graph(dof_pairs: np.ndarray, n_free: int) -> csr_graph: ...
def reverse_cuthill_mckee(graph: csr_graph) -> np.ndarray: ...   # nueva -> vieja, O(n+nnz)
def approximate_minimum_degree(graph: csr_graph) -> np.ndarray: ...
def bandwidth(perm: np.ndarray, graph: csr_graph) -> int: ...
def profile(perm: np.ndarray, graph: csr_graph) -> int: ...

# src/opensees_studio/core/performance/memory.py
def estimate_csr_bytes(nnz: int, n: int, index_bits: int = 32) -> int: ...
def estimate_fiber_bytes(n_sec: int, n_ip: int, n_fib: int, kappa: float) -> int: ...
def choose_system(n_free: int, budget_bytes: int, has_fibers: bool) -> SystemChoice: ...
def estimate_result_bytes(n_steps: int, n_channels: int) -> int: ...

# src/opensees_studio/core/performance/budget.py
class StageBudget(BaseModel):
    assembly_s: float; factorization_s: float; solve_s: float; post_s: float
def load_budgets(path: Path) -> dict[str, StageBudget]: ...
def check_budget(measured: StageBudget, budget: StageBudget) -> list[str]:
    """Devuelve avisos; exceder tiempo nunca lanza excepcion."""
```

Reglas de arquitectura: el ordenamiento, la estimación de memoria y el presupuesto viven en `core/` (sin Qt, sin OpenSeesPy, verificables sin solver); solo `services/` habla con el solver, y `opensees_runner` emite `ops.numberer(...)`/`ops.system(...)` desde `case.numberer` y `case.system` además de medir tiempos por etapa y pico de memoria del hijo. Los presupuestos y $\kappa$ son datos versionados en `data/perf/*.json`, no constantes del motor. La permutación RCM debe registrarse y aplicarse de forma consistente al des-permutar autovectores, porque la regla de desempate por menor índice de GDL depende del orden. Ninguna estimación sustituye a la medición: el informe lleva ambas.

## Datos normativos

No aplica. El rendimiento no está regido por ningún reglamento y esta skill no contiene coeficientes normativos ($R$, $C_d$, $\Omega_0$, $\phi$) que citar. Los únicos números con documento son los de la literatura de cálculo numérico —costo $\frac{1}{3}nb^2$, flops $\sum_j|L_j|^2$, tamaño de bloque denso—, citados en «Referencias». Los parámetros de máquina ($\kappa$, presupuestos, $r_{pico}$) **no son normativos**: viven en `data/perf/*.json` con `source` y `verified_on` y se recalibran por máquina.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| RCM en cadena | camino de $n=100$, orden barajado | $b=1$ y permutación inversa exacta | exacto | cálculo a mano |
| RCM en mancuerna | dos bloques de 40 unidos por 1 arista | $b\le41$ (natural $\ge79$) | exacto | cálculo a mano |
| Perfil en cadena | $n=100$, $b_i=1$ | $P=100$; $M_{sky}=1600$ B | exacto | cálculo a mano |
| Flops en banda | $n=300$, $b=20$ | $4.0\times10^{4}$ flops | 5 % relativo | Bathe §8.3 |
| Memoria CSR | $nnz=7.2\times10^{6}$, $n=2\times10^{5}$ | $8.64\times10^{7}$ B $=82.4$ MiB | 1 % relativo | cálculo a mano |
| Índices 64 bits | $nnz=2^{31}$ | exige `int64`: $16\,nnz+8(n+1)$ | exacto | cálculo a mano |
| Memoria densa | $n=2\times10^{4}$, $\eta=3$ | $9.6\times10^{9}$ B $\Rightarrow$ no cabe en 2 GiB | 1 % relativo | cálculo a mano |
| Umbral de memoria | 2 GiB, $\eta=3$ | $n_{mem}=9\,464$ | exacto | $\sqrt{M/(8\eta)}$ |
| Fibras | $n_{sec}=500$, $n_{ip}=5$, $n_{fib}=100$, $\kappa=8$ | $1.6\times10^{7}$ B $=15.3$ MiB | 1 % relativo | $M_{fib}$ (§5) |
| Almacén | 5000 pasos $\times$ 60 000 canales | $2.4\times10^{9}$ B: bloques obligatorios | 1 % relativo | cálculo a mano |
| Paridad de solver | mismo modelo, `FullGeneral` vs `SparseGeneral` | desplazamientos iguales | $10^{-12}$ relativo | paridad numérica |
| Determinismo | dos corridas, mismo numberer | resultados bit a bit idénticos | igualdad exacta | regresión |
| Permutación | RCM + des-permutar autovectores | residual $<10^{-10}\|K\|\|u\|$ | $10^{-10}$ relativo | cálculo a mano |
| Presupuesto | etapa medida $=2.0\times$ presupuesto | aviso con etapa y valor medido | exacto (texto) | `check_budget` |

Las tolerancias de tiempo no son comparables entre máquinas: la regresión de tiempo compara **repartos relativos** entre etapas, no segundos absolutos.

## Errores frecuentes y trampas

1. **Ensamblar con `K[idx] += Ke`**: la indexación avanzada de NumPy no acumula duplicados; las contribuciones compartidas se pierden y la matriz queda silenciosamente blanda. Se usa `np.add.at` o `np.bincount`.
2. **Renumerar sin des-permutar los autovectores**: la regla de desempate por menor índice de GDL (tolerancia $10^{-9}$) es dependiente del orden y RCM puede invertir el signo elegido, rompiendo la regresión.
3. **Medir `ops.analyze()` desde la GUI**: el análisis corre en un proceso hijo y el perfil de la interfaz no contiene ni una muestra del solver.
4. **Creer que `cProfile` ve el costo del solver**: el tiempo en código nativo de OpenSees no aparece; hay que medirlo por diferencia o con `py-spy --native`.
5. **Comparar tiempos fríos con calientes**: la primera importación del solver domina en modelos pequeños y el orden de las corridas cambia la conclusión.
6. **Suponer que `SparseGeneral -piv` cambia algo**: en este build el pivoteo parcial está siempre activo y el argumento retirado se carga con aviso y se descarta.
7. **Elegir `BandSPD`/`ProfileSPD` con rigidez no definida positiva** (fibras degradadas, fisuración): la factorización falla o devuelve un resultado inválido.
8. **Un nodo mal conectado fija $b$ para todo el modelo**: el ancho de banda es un máximo, así que un elemento que salta entre dos alas duplica el costo global; se detecta comparando $b$ por fila, no solo el global.
9. **Ignorar el diafragma rígido al estimar $nnz$**: un diafragma que une $m$ nodos añade $\approx18m^2$ entradas por piso y en losas grandes domina el patrón.
10. **Medir memoria con RSS justo después de factorizar**: la factorización asigna y libera y el pico se pierde; usar pico de RSS del proceso y `tracemalloc` para los objetos de Python.
11. **Pasar a `float32` para "que quepa"**: ahorra la mitad de memoria y hace inalcanzable la tolerancia de regresión de $10^{-12}$ relativo.
12. **Fijar el *chunk* de HDF5 por estética**: un *chunk* que no sigue el patrón de acceso multiplica las lecturas y convierte el post-proceso en el cuello de botella.
13. **Repetir la factorización entre casos con la misma $K$**: en un modal seguido de estáticos con la misma rigidez, no reutilizarla desperdicia la etapa más cara.

## Interfaz de salida

Por caso de análisis el programa reporta: $n$ (libres y restringidos), $nnz$ y $M_{CSR}$ estimada y medida; el `numberer` usado y, si aplica, $b$ o $P$ **antes y después** de renumerar con la razón de reducción; el `system` elegido con la razón de la elección (régimen de §6) y si se cruzó $n_{mem}$ o $n_{tiempo}$; $M_{fib}$ estimada cuando hay fibras, citando el archivo del que se leyó $\kappa$; los tiempos por etapa (ensamblaje, factorización, resolución, autovalores, post-proceso) y el pico de memoria, marcando las etapas que exceden su presupuesto; la ruta y fecha del archivo de presupuestos usado, para que el número sea trazable; y los avisos de datos no verificados ($\kappa$, presupuestos) viajando con el resultado hasta el informe, como exige `platform/results-reporting-and-compliance-audit`.

## Referencias

1. K.-J. Bathe, *Finite Element Procedures*, 2.ª ed., Prentice Hall, 2014 — cap. 8: solución de ecuaciones, costo en banda y perfil.
2. T. A. Davis, *Direct Methods for Sparse Linear Systems*, SIAM, 2006 — eliminación, árbol de eliminación, flops $\sum_j|L_j|^2$, relleno.
3. E. Cuthill y J. McKee, *Reducing the bandwidth of sparse symmetric matrices*, Proc. 24th ACM National Conference, 1969.
4. P. Amestoy, T. A. Davis e I. S. Duff, *An approximate minimum degree ordering algorithm*, SIAM J. Matrix Anal. Appl. 17(4), 1996.
5. G. H. Golub y C. F. Van Loan, *Matrix Computations*, 4.ª ed., Johns Hopkins University Press, 2013 — Cholesky/LDLT y conteo de operaciones.
6. J. Dongarra et al., *LAPACK Users' Guide*, 3.ª ed., SIAM, 1999 — rutinas densas y espacio de trabajo.
7. The HDF Group, *HDF5 User's Guide*, ed. 1.14, 2023 — conjuntos fragmentados, caché de fragmentos, compresión.
8. B. Gregg, *py-spy* — documentación del muestreador (`--native`, `--rate`).
9. `docs/architecture.md` y `CLAUDE.md` del repositorio — umbral denso de autovalores, numberers ofrecidos, nota de `SparseGeneral` y contrato del proceso hijo.

## Registro de verificación

- **Verificado** contra documentación del repositorio: los `numberer` (`Plain`/`RCM`/`AMD`) y los `system` ofrecidos; que el análisis corre en un proceso hijo y por tanto el perfilado va sobre el CLI; `DENSE_EIGEN_MAX_FREE_DOF` como precedente de umbral por tamaño; que `SparseGeneral -piv` no cambia resultados en este build.
- **Verificado** contra literatura: $\frac{1}{3}\sum b_i^2$ y $\sum_j|L_j|^2$; memoria CSR; formulación de RCM y AMD.
- **Pendiente**: $\kappa$ (estado por fibra en OpenSeesPy 3.8.0.0) debe medirse con un modelo de fibras instrumentado y escribirse en `data/perf/fiber_state.json`; los presupuestos por etapa deben calibrarse con la línea base real de la máquina objetivo en `data/perf/budgets.json`. Ninguna cifra de tiempo absoluto de esta skill es criterio de aceptación hasta entonces.
- **Responsable de cerrar**: responsable de rendimiento del proyecto, con los perfiles medidos del CLI de análisis adjuntos al cierre.
