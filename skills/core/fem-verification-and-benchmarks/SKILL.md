---
name: fem-verification-and-benchmarks
description: >-
  Verifica y valida el motor de elementos finitos antes de aceptar un cambio en
  el solver: patch test de deformación constante, prueba de MacNeal-Harder para
  shell, benchmarks con solución analítica (voladizo, pórtico, armadura, marco de
  corte, placa), convergencia de malla con orden observado y Richardson,
  invariancia al sistema de unidades, conteo de modos de cuerpo rígido,
  equilibrio global, balance de energía no lineal, contraste con casos publicados
  (OpenSees, PEER, NAFEMS) y regresión con tolerancias por magnitud. Úsala al
  modificar un elemento, un material, la transformación de ejes o el solver;
  cuando un resultado no cuadre; al fijar tolerancias de regresión; o al exigir
  paridad entre la ejecución directa y la de línea de comandos y determinismo
  entre corridas.
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [qa]
---

# Verificación y benchmarks del motor de elementos finitos

## Cuándo usar esta skill

- Se toca un elemento (`core/fem-formulation-core`), una constitutiva (`core/fem-materials-and-sections`) o el integrador de paso (`core/nonlinear-and-solver-strategies`): ningún cambio de esos módulos se acepta sin volver a correr esta suite.
- Aparece una pregunta de la forma «el desplazamiento del voladizo no cuadra», «el shell se ve demasiado rígido» o «la malla fina da menos que la gruesa».
- Hay que fijar o auditar las tolerancias de regresión de `tests/integration/`, o demostrar independencia del sistema de unidades, determinismo entre corridas y paridad directo vs. CLI (`platform/platform-architecture-and-services`).
- Hay que incorporar un benchmark publicado (OpenSees, PEER, NAFEMS) a `data/benchmarks/` con su cita.

**No usar** para calibrar contra un código normativo (→ `codes/*`) ni para elegir coeficientes de diseño: esta skill mide error numérico, no cumplimiento reglamentario.

## Alcance y límites

Cubre **verificación de código** (¿se resuelven bien las ecuaciones programadas?) y **verificación de solución** (¿cuánto error tiene la malla elegida?), en la terminología de ASME V&V 10-2019. No cubre **validación** (contraste con ensayo físico): exige datos experimentales y queda fuera hasta que exista un banco de ensayos. Queda fuera también la verificación de las constitutivas complejas (→ `core/nonlinear-and-solver-strategies`), la de la combinación modal (→ `core/modal-and-time-history`) y el reporte al usuario (→ `platform/results-reporting-and-compliance-audit`).

Supuesto de partida: el valor esperado es analítico, cerrado o publicado con fuente primaria. Una corrida anterior del propio programa **no** es un valor esperado; es una referencia de regresión y se etiqueta como tal.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Sistema de unidades del modelo (coherente) | sí | bloquear: sin él no hay invariancia que comprobar |
| Definición del benchmark (geometría, malla, cargas) | sí | leerla de `data/benchmarks/<id>.json`; nunca del código |
| Solución esperada con su unidad | sí | bloquear: un caso sin valor esperado no es un caso |
| `source` y `verified_on` del valor esperado | sí | rechazar la entrada del archivo de datos |
| Versión del solver (OpenSeesPy 3.8.0.0) y commit | sí | bloquear: un resultado sin procedencia no es trazable |
| Secuencia de mallas (\(r \ge 2\), ≥ 3 niveles) | sólo en convergencia | `No aplica` en los casos exactos |
| Orden teórico esperado del elemento | sólo en convergencia | deducirlo del grado del polinomio, no suponerlo |

## Fundamento y formulación

### 1. Patch test de deformación constante
Se prescribe en el contorno de un parche distorsionado un campo lineal exacto, con \(x,y,z\) en m y \(a_i,b_i,c_i\) en m:

$$u_x = a_0 + a_1x + a_2y + a_3z,\quad u_y = b_0 + b_1x + b_2y + b_3z,\quad u_z = c_0 + c_1x + c_2y + c_3z$$

Las deformaciones exactas son constantes: \(\varepsilon_{xx}=a_1\), \(\varepsilon_{yy}=b_2\), \(\gamma_{xy}=a_2+b_1\) (adimensionales), y con \(D\) la matriz constitutiva elástica (Pa), \(\sigma=D\varepsilon\) es constante. Un elemento **completo y compatible** reproduce ese campo con independencia de la distorsión. Métrica:

$$\eta_\varepsilon=\frac{\max_e\lVert\varepsilon_h^{(e)}-\varepsilon\rVert_\infty}{\lVert\varepsilon\rVert_\infty}\le 10^{-12}$$

El parche debe incluir elementos distorsionados, un nodo interior libre (no de contorno) y, en elementos con nodos de lado, un elemento cuyo lado caiga sobre el borde del parche. En sólidos 3D, \(\gamma_{xy}\), \(\gamma_{yz}\) y \(\gamma_{zx}\) se activan en parches separados.

El **método de soluciones manufacturadas** (MMS) generaliza la prueba: se elige \(u\) analítico no polinómico, se calcula el término fuente \(f=-\nabla\!\cdot\!\sigma(u)\) (N/m³), se prescribe \(u\) en todo el contorno y se mide el orden de convergencia. Es la única verificación de código que detecta un error en la formulación de \(f\) o en la integración de la carga.

### 2. Prueba de MacNeal–Harder
Placa rectangular en voladizo con malla gruesa (2×2 elementos) y los estados de carga del obstáculo: cortante y flexión en el plano (membrana), cortante y flexión fuera del plano (placa) y torsión. El propósito es que un elemento robusto reproduzca la solución de placa delgada **con malla gruesa**; un elemento con bloqueo por cortante o por membrana se vuelve casi rígido y falla aunque pase el patch test. Un patch test de membrana correcto **no** valida la parte de flexión del shell: son operadores distintos y se verifican por separado.

> ⚠️ VERIFICAR: la geometría exacta (proporciones 6:2:0.1), los estados de carga, \(E\), \(\nu\) y los valores de referencia del obstáculo de MacNeal–Harder deben copiarse del artículo original, no de una fuente secundaria; se comprueban en MacNeal & Harder (1985), *Finite Elements in Analysis and Design* 1(1):3–20. Mientras tanto el programa **lee el caso de `data/benchmarks/macneal-harder.json`** (`source`, `geometry`, `loads`, `expected`, `tolerance`, `units`) y no incrusta ningún número en el módulo.

### 3. Soluciones analíticas de referencia
Con \(E\) (Pa), \(I\) (m⁴), \(A\) (m²), \(L\) (m), \(P\) (N), \(w\) (N/m), \(q\) (Pa), \(t\) (m), \(D=Et^3/[12(1-\nu^2)]\) (N·m) y \(k_s\) el factor de cortante:

| Caso | Resultado exacto |
|---|---|
| Voladizo, carga puntual en el extremo (Euler–Bernoulli) | \(\delta=\dfrac{PL^3}{3EI}\), \(\theta=\dfrac{PL^2}{2EI}\) |
| Voladizo, carga distribuida \(w\); carga axial \(P\) | \(\delta=\dfrac{wL^4}{8EI}\); \(\delta=\dfrac{PL}{EA}\) |
| Voladizo de Timoshenko, \(P\) en el extremo | \(\delta=\dfrac{PL^3}{3EI}+\dfrac{PL}{k_sGA}\), \(k_s=5/6\) (sección rectangular) |
| Viga simplemente apoyada, carga uniforme | \(\delta_c=\dfrac{5wL^4}{384EI}\), \(M_c=\dfrac{wL^2}{8}\) |
| Armadura simétrica de dos barras, ángulo \(\theta\) | \(\delta_v=\dfrac{PL}{2EA\sin^2\theta}\), \(N=\dfrac{P}{2\sin\theta}\) |
| Columna de altura \(h\) con base empotrada; extremo superior articulado / empotrado | \(k=\dfrac{3EI}{h^3}\) / \(k=\dfrac{12EI}{h^3}\) |
| Placa cuadrada simplemente apoyada, carga uniforme | \(w_{max}=0.00406\,\dfrac{qa^4}{D}\) |
| Edificio de corte uniforme de \(N\) pisos, masa \(m\) (kg), rigidez \(k\) (N/m) | \(\omega_j=2\sqrt{\dfrac{k}{m}}\,\sin\dfrac{(2j-1)\pi}{2(2N+1)}\) |

El pórtico de un vano y un piso con **viga infinitamente rígida** a flexión (hipótesis de edificio de corte) tiene \(k_{piso}=12\,n_cEI_c/h^3\) con \(n_c\) columnas iguales. Si la viga es flexible, la rigidez de entrepiso queda **entre** \(3EI_c/h^3\) y \(12EI_c/h^3\) por columna: fuera de ese intervalo hay un error de modelo o de liberación de extremos.

### 4. Convergencia de malla
Con \(h\) el tamaño característico (m), \(u_h\) la magnitud escalar de interés y \(r=h_k/h_{k+1}\ge 2\) la razón de refinamiento constante de tres mallas:

$$e(h)=\lVert u_h-u\rVert\le Ch^p,\quad p_{obs}=\frac{\ln\!\big((u_2-u_1)/(u_3-u_2)\big)}{\ln r},\quad u_\infty\approx u_3+\frac{u_3-u_2}{r^{\,p_{obs}}-1},\quad GCI_{fino}=F_s\,\frac{\left|(u_2-u_3)/u_3\right|}{r^{\,p_{obs}}-1},\ \ F_s=1.25$$

Para un elemento con polinomio completo de grado \(p\), el error en norma de energía converge como \(O(h^p)\) y el error \(L^2\) de desplazamiento como \(O(h^{p+1})\): barra de 2 nodos, triángulo de 3 y cuadrilátero de 4 dan \(p=1\); triángulo de 6 y cuadrilátero de 8, \(p=2\). \(p_{obs}\) sólo es válido en régimen asintótico: con malla gruesa o con una singularidad (carga puntual, esquina entrante) miente.

### 5. Invariancia al sistema de unidades
Con \(c_L\) el factor de longitud, \(c_F\) el de fuerza y \(c_E=c_F/c_L^2\) el de tensión (Pa = N/m²), las magnitudes del problema lineal elástico escalan exactamente:

| Magnitud (SI) | Escala | Magnitud (SI) | Escala |
|---|---|---|---|
| Longitud, desplazamiento (m) | \(c_L\) | Tensión, \(E\) (Pa) | \(c_E\) |
| Área / inercia (m² / m⁴) | \(c_L^2\) / \(c_L^4\) | Rigidez (N/m) | \(c_F/c_L\) |
| Fuerza, reacción (N); momento (N·m) | \(c_F\); \(c_Fc_L\) | Densidad de masa (kg/m³) | \(c_Fs^2/c_L^4\) |
| Aceleración y \(g\) (m/s²) | \(c_L/s^2\) | Período (s), frecuencia (Hz) | \(1\), invariante |

Ejemplo de sistema coherente alterno: mm–N–MPa–t, con \(c_L=10^3\), \(c_F=1\), \(c_E=10^{-6}\) y densidad del acero \(7850\ \text{kg/m}^3=7.85\times10^{-9}\ \text{t/mm}^3\). Un \(g\) escrito como 9.81 en un modelo en mm es invisible en estática y rompe toda la dinámica.

### 6. Modos de cuerpo rígido
Para un modelo sin restringir, \(K\phi=0\) tiene tantas soluciones independientes como movimientos de cuerpo rígido (MCR) por componente conexa: 6 en sólido o shell 3D, 3 en pórtico plano o tensión plana, 3 en armadura espacial, 2 en armadura plana. El conteo usa umbral **relativo** \(\lambda_i\le\epsilon\lambda_{max}\) con \(\epsilon=10^{-10}\), nunca uno absoluto, porque \(\lambda\) depende de las unidades y de \(E\). Cada \(\phi\) debe cumplir además \(\sum_i m_i\phi_i=0\) (traslación) y \(\sum_i r_i\times m_i\phi_i=0\) (rotación respecto al centro de masa), lo que distingue un MCR de un mecanismo: el mecanismo también da autovalor nulo pero no es un movimiento de sólido rígido.

### 7. Equilibrio global
$$\sum_i R_i+\sum_j F_j=0\ (\text{N}),\qquad \sum_i r_i\times R_i+\sum_j r_j\times F_j=0\ (\text{N·m})$$

con \(R_i\) las reacciones (N), \(F_j\) las cargas aplicadas (N) y \(r\) las posiciones (m). Se comprueba en **cada** dirección, en momentos respecto a un punto fuera del origen y en cada caso de carga, incluidos los de deformación impuesta y temperatura (fuerza externa nula, reacciones no nulas). La tolerancia relativa se toma contra \(\max(\lVert F_{ext}\rVert_\infty,\lVert R\rVert_\infty)\) con piso absoluto de \(10^{-8}\) N para no dividir por cero.

### 8. Balance de energía en análisis no lineal
Con \(P_n\), \(u_n\) la carga y el desplazamiento en el paso \(n\), \(U\) la energía de deformación almacenada (J), \(D_p\) la disipación plástica (J) y \(D_v\) la de amortiguamiento (J):

$$W_{ext}=\sum_n\tfrac{1}{2}(P_n+P_{n-1})(u_n-u_{n-1}),\qquad r_E=\frac{\left|W_{ext}-U-D_p-D_v\right|}{\max(W_{ext},U)}$$

La regla trapezoidal del camino es exacta si el camino es lineal a tramos. Para plasticidad asociativa, \(\dot D_p=\int_V\sigma:\dot\varepsilon^p\,dV\ge0\) (máxima disipación plástica) y \(D_p\) es monótona no decreciente. En dinámica, con \(E_{kin}=\tfrac12\dot u^TM\dot u\), la suma \(E_{kin}+U+D_p+D_v-W_{ext}\) se conserva con el esquema de aceleración media (\(\gamma=1/2\), \(\beta=1/4\), sin amortiguamiento); con HHT-\(\alpha\) (\(\alpha<0\)) el esquema disipa energía por diseño y debe contarse aparte. \(r_E\) se evalúa **en cada paso**, no sólo al final: un drift que crece y regresa se cancela en el total.

### 9. Regresión numérica y tolerancias por magnitud
| Magnitud | Identidad (patch/MMS) | Exactitud vs. analítico o publicado | Regresión entre corridas |
|---|---|---|---|
| Desplazamiento (m) | \(10^{-12}\) rel | 1 % rel o \(10^{-6}\) m abs | \(10^{-9}\) rel (0 en solver directo) |
| Fuerza interna, reacción (N) | \(10^{-10}\) rel (equilibrio) | 1 % rel | \(10^{-9}\) rel |
| Tensión (Pa) | \(10^{-12}\) rel (campo constante) | 2 % rel | \(10^{-9}\) rel |
| Período propio (s) | — | 0.5 % rel (0.1 % con malla convergida) | 0 en solver denso; \(10^{-6}\) en ARPACK |
| Masa o factor de participación | — | 0.1 % abs | \(10^{-9}\) abs |
| \(p_{obs}\); energía en el balance | — | \(\pm0.3\) del orden teórico; \(10^{-4}\) rel no lineal | \(10^{-9}\) rel |

Toda tolerancia relativa lleva piso absoluto; sin él, una magnitud esperada cercana a cero (reacción de un caso autoequilibrado) falla siempre. La comparación de resultados se hace en `float64` de extremo a extremo.

## Procedimiento

1. Cargar el suite desde `data/benchmarks/*.json`; rechazar toda entrada sin `source`, `units`, `expected`, `tolerance` o `verified_on`.
2. Correr primero los casos de identidad (patch test 2D y 3D, MMS): si fallan, ningún otro resultado es interpretable.
3. Correr los analíticos exactos (voladizo EB y Timoshenko, armadura, marco de corte, placa) y comparar contra la fórmula cerrada.
4. Correr MacNeal–Harder con malla gruesa y fina; la razón entre ambas es el indicador de bloqueo.
5. Correr la secuencia de convergencia (≥ 3 mallas, \(r\ge2\)), calcular \(p_{obs}\), \(u_\infty\) y \(GCI\), y contrastar \(p_{obs}\) con el orden teórico del elemento.
6. Repetir un subconjunto en el sistema de unidades alterno y verificar la tabla de escalas.
7. Contar MCR y comprobar equilibrio global y balance de energía caso por caso.
8. Ejecutar el mismo caso por vía directa y por CLI, y dos veces en procesos nuevos; comparar.
9. Emitir el informe con veredicto por caso y global, y archivarlo con el commit y la versión del solver.

## Implementación en la plataforma

```python
# core/verification/  (núcleo puro: sin Qt, sin openseespy; sólo stdlib + NumPy)
def check_scalar(case_id: str, actual: float, expected: float, tol: Tolerance) -> CheckResult:
    """Compara una magnitud: relativo con piso absoluto."""
def check_patch_strain(strains: dict[int, tuple[float, ...]], exact: tuple[float, ...]) -> CheckResult:
    """eta_epsilon del patch test; exige <= 1e-12."""
def rigid_body_mode_count(K: np.ndarray, *, rel_tol: float = 1e-10) -> RbmReport:
    """Autovalores nulos relativos por componente conexa; momento de masa nulo."""
def check_equilibrium(reactions, applied, points, *, abs_floor: float = 1e-8) -> CheckResult:
    """Fuerzas y momentos respecto a un punto fuera del origen."""
def observed_order(u_coarse: float, u_medium: float, u_fine: float, r: float) -> ConvergenceReport:
    """p_obs, u_infinito (Richardson) y GCI con Fs = 1.25."""
def energy_balance(history: LoadDisplacementPath) -> EnergyReport:
    """W_ext, U, D_p, D_v y residuo r_E maximo por paso."""
def unit_invariance_report(base: ResultSet, scaled: ResultSet, scale: UnitScale) -> CheckResult:
    """Aplica la tabla de escalas y devuelve el error relativo por magnitud."""
```

Reglas de arquitectura:

- `core/verification/` compara y decide; **nunca** importa OpenSeesPy ni Qt. Los modelos de benchmark se construyen con los mismos objetos de `core/` que usa el programa, no por una ruta paralela.
- `services/verification/runner.py` es el único que ejecuta el solver, por el constructor de argv existente (nunca codificando `sys.executable -m ...`): `run_suite(suite: Path, executor: SolverExecutor, out: Path) -> SuiteReport`.
- Los valores esperados viven en `data/benchmarks/*.json` con `source` y `verified_on`; el código sólo contiene la fórmula o el lector.
- CLI propuesta: `python -u -m opensees_studio.verify --suite core --out <dir>`, con una línea JSON por caso en `stdout` y salidas `0` todo pasa, `1` algún caso falla la tolerancia, `2` error numérico del solver, `3` suite o archivo de datos inválido.
- Pruebas: `tests/unit/test_verification_analytic.py` (puro, instantáneo) y `tests/integration/test_benchmark_suite.py` (openseespy real). Un caso no se marca `skip` para que la suite pase: se marca `xfail` con incidencia y fecha.

## Datos normativos

Esta skill no reproduce coeficientes regulados (\(R\), \(C_d\), \(\Omega_0\), \(Q\), \(I\), \(\phi\), límites de deriva): no participan en la verificación numérica. Los datos aquí son valores de referencia de benchmarks y el marco de V&V.

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Terminología y marco de verificación de código y de solución | ASME V&V 10-2019 | sí |
| \(GCI\) con \(F_s=1.25\) para tres mallas; \(p_{obs}\) y Richardson | ASME V&V 20-2009; Roache (1998) | sí |
| \(w_{max}=0.00406\,qa^4/D\), placa cuadrada simplemente apoyada | Timoshenko & Woinowsky-Krieger, 2.ª ed., Tabla 8 | sí (valor clásico de tabla) |
| \(k_s=5/6\) en sección rectangular | Timoshenko, teoría de vigas | sí |
| Frecuencias del edificio de corte uniforme | Chopra, *Dynamics of Structures*, 5.ª ed. | sí (contrastado en \(N=1,2\)) |
| Valores de referencia de MacNeal–Harder | MacNeal & Harder (1985) | no — `VERIFICAR` |
| Serie NAFEMS (placas, sólidos, no lineal) | NAFEMS *Standard Benchmarks* | no — `VERIFICAR` |
| Identificadores y valores de los casos publicados de OpenSees/PEER | manual de ejemplos de OpenSees 3.8.0.0 | no — `VERIFICAR` |

> ⚠️ VERIFICAR: los valores esperados de MacNeal–Harder, de la serie NAFEMS y de los casos publicados de OpenSees/PEER no se pudieron contrastar con la fuente primaria. Se comprueban en el artículo y en los manuales originales, y se transcriben a `data/benchmarks/<id>.json` con `source` y `verified_on`. El programa **lee esos valores del archivo versionado** y no los incrusta en el código.

## Verificación y casos de prueba

| # | Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|---|
| 1 | Patch test 2D | \(a_1=2\times10^{-3}\), \(b_2=1.5\times10^{-3}\), \(a_2=5\times10^{-4}\), \(b_1=-3\times10^{-4}\) | \(\eta_\varepsilon\le10^{-12}\) | absoluta | completitud del elemento |
| 2 | Voladizo EB | \(L=4\) m, \(E=200\) GPa, \(I=10^{-5}\) m⁴, \(P=1000\) N | \(\delta=1.0667\times10^{-2}\) m | \(10^{-10}\) rel | \(PL^3/3EI\) |
| 3 | Voladizo Timoshenko | \(L=1\) m, \(A=10^{-2}\) m², \(I=10^{-5}\) m⁴, \(\nu=0.3\), \(P=1000\) N | \(\delta=1.6823\times10^{-4}\) m | 0.5 % rel | \(PL^3/3EI+PL/k_sGA\) |
| 4 | Marco de corte 1 piso | \(h=3\) m, 2 columnas \(EI=1.6\times10^7\) N·m², \(V=10^5\) N | \(\delta=7.03125\times10^{-3}\) m | \(10^{-6}\) rel | \(k=24EI_c/h^3\) |
| 5 | Armadura de 2 barras | \(A=5\times10^{-4}\) m², \(L=2\) m, \(\theta=45^\circ\), \(P=10^5\) N | \(\delta_v=2\times10^{-3}\) m; \(N=7.0711\times10^4\) N | \(10^{-10}\) rel | \(PL/2EA\sin^2\theta\) |
| 6 | Marco de corte 2 pisos | \(m=10^5\) kg, \(k=1.42222\times10^7\) N/m por piso | \(T_1=0.85248\) s; \(T_2=0.32562\) s | \(10^{-6}\) rel | \(\omega_j\) de edificio de corte |
| 7 | Placa cuadrada SS | \(a=1\) m, \(t=0.01\) m, \(E=200\) GPa, \(\nu=0.3\), \(q=1000\) Pa | \(w_{max}=2.2168\times10^{-4}\) m | 2 % rel (16×16); 0.5 % extrapolado | Timoshenko, Tabla 8 |
| 8 | Convergencia Q4 / Q8 | tensión plana, \(r=2\), 3 mallas | \(p_{obs}=1\) (Q4); \(p_{obs}=2\) (Q8) | \(\pm0.3\) | teoría de elementos |
| 9 | Invariancia de unidades | caso 2 en (m,N,Pa,kg) y (mm,N,MPa,t) | \(\delta_{mm}=10^3\delta_m\); \(T\) y \(\nu\) idénticos | \(10^{-9}\) rel | tabla de escalas §5 |
| 10 | Modos de cuerpo rígido | sólido 3D libre / pórtico plano / armadura plana | 6 / 3 / 2 autovalores \(\lambda_i\le10^{-10}\lambda_{max}\) | conteo exacto | teoría de MCR |
| 11 | Equilibrio global | casos 2, 4 y 5; momentos respecto a un punto fuera del origen | \(\lVert\text{res}\rVert_\infty\le10^{-10}\max\lVert F\rVert\) | piso absoluto \(10^{-8}\) N | estática |
| 12 | Balance de energía | elastoplástico bilineal, control de desplazamiento monótono | \(\lvert W_{ext}-U-D_p\rvert/W_{ext}\le10^{-6}\); \(D_p\) no decreciente | por paso | Simo & Hughes |
| 13 | MacNeal–Harder | obstáculo completo, malla 2×2 | solución de placa delgada/gruesa del artículo | del archivo de datos | `VERIFICAR` |
| 14 | Paridad y determinismo | misma instantánea por vía directa y por CLI, y dos procesos frescos | diferencia bit a bit nula; modos idénticos tras `normalize_mode_sign` | 0 (float64); \(10^{-9}\) rel en ARPACK | `test_cli_result_parity.py` |

## Errores frecuentes y trampas

1. **Patch test «aprobado» con malla regular.** Sólo con elementos distorsionados el test detecta un jacobiano mal evaluado; en malla regular muchos elementos incompletos pasan por casualidad.
2. **Confundir orden \(L^2\) con orden de energía.** Comparar el \(p_{obs}=2\) de un Q4 (error \(L^2\)) contra el \(p=1\) teórico de energía y declarar un bug inexistente; o al revés, tapar un elemento que pierde un grado.
3. **Umbral absoluto para el conteo de MCR.** \(\lambda\) escala con \(E\) y con las unidades, así que el conteo cambia al pasar de m a mm; y un submesh desconectado o un nodo flotante añade 6 modos nulos más por componente. Hace falta umbral relativo, conteo por componente conexa y verificación del momento de masa nulo.
4. **Validar el shell sólo con el patch test de membrana.** La flexión (bloqueo por cortante) no queda cubierta: sin MacNeal–Harder, un elemento sobre-rígido pasa toda la suite.
5. **Autocomparación de mallas.** Aceptar la convergencia fina-contra-gruesa cuando ambas convergen a la respuesta equivocada (bloqueo, espesor mal transformado, inercia mal leída).
6. **Equilibrio comprobado con un caso simétrico o autoequilibrado.** Los errores de camino de carga se cancelan; hacen falta casos asimétricos y momentos respecto a un punto que no sea el origen.
7. **Extraer sólo los 3 GDL de traslación de la reacción.** En un apoyo que restringe giro, o en un shell con GDL de taladro, el momento de reacción se pierde y el equilibrio «falla» sin que el solver tenga un error.
8. **Balance de energía evaluado sólo en el último paso, o sin contar HHT-\(\alpha\) y Rayleigh.** Un residuo que crece y regresa se cancela, así que hay que registrar el máximo por paso; y con \(\alpha<0\) o con amortiguamiento viscoso el esquema disipa energía por diseño, de modo que el residuo no es un error del material ni del integrador.
9. **Dos llamadas a `ops.eigen` en el mismo proceso.** La segunda invierte signos y rota pares degenerados (el vector de inicio de ARPACK persiste); la regresión falla de forma intermitente. Hay que enrutar el caso por el proceso hijo y resolver el solver con `core.modal.resolve_modal_solver`.
10. **Comparar el desplazamiento impuesto en vez de la reacción.** Bajo control de desplazamiento el desplazamiento es la entrada, no el resultado: la verificación es sobre la fuerza.
11. **Iterar sobre `dict` o `set` sin ordenar al construir el modelo o serializar el informe.** El hash aleatorio de Python cambia el orden y rompe el determinismo entre procesos sin ningún error numérico de por medio.
12. **Mezclar mallas de extracción y de ensamblaje.** Comparar el desplazamiento de un nodo que en la malla gruesa está en el eje y en la fina no, o interpolar en vez de comparar en el mismo punto físico.

## Interfaz de salida

El programa expone un informe de verificación, por caso y global:

- `case_id`, `suite`, `source` (documento y edición del valor esperado) y `verified_on`.
- Magnitud, unidad explícita, valor esperado, valor calculado, error relativo, tolerancia aplicada y veredicto (`pass`/`fail`/`xfail`).
- En convergencia: las tres mallas, \(p_{obs}\), orden teórico del elemento, \(u_\infty\) y \(GCI_{fino}\) con su \(F_s\).
- Procedencia y determinismo: versión del solver (OpenSeesPy 3.8.0.0), commit, tipo de elemento, número de GDL, MCR detectados, sistema de unidades, hash del archivo de benchmarks, y comparación directo vs. CLI y entre dos procesos frescos.
- Salida máquina-legible `verification-report.json` (claves ordenadas, sin marcas de tiempo dentro del bloque numérico) y resumen en `reports/verification/<fecha>.md`.
- Aviso explícito por cada caso `xfail` con su incidencia, y aviso de bloqueo cuando el caso usa valores con `VERIFICAR` pendiente.

## Referencias

1. ASME, *V&V 10-2019 — Standard for Verification and Validation in Computational Solid Mechanics* (2019) y *V&V 20-2009* (2009, marco del \(GCI\), \(F_s=1.25\)).
2. P. J. Roache, *Verification and Validation in Computational Science and Engineering*, Hermosa Publishers, 1998.
3. K.-J. Bathe, *Finite Element Procedures*, 2.ª ed., 2014 (patch test, completitud, bloqueo, convergencia); O. C. Zienkiewicz y R. L. Taylor, *The Finite Element Method*, 7.ª ed., 2013.
4. R. H. MacNeal y R. L. Harder, «A proposed standard set of problems to test finite element accuracy», *Finite Elements in Analysis and Design*, 1(1), 1985, pp. 3–20.
5. NAFEMS, *The Standard NAFEMS Benchmarks*, ediciones revisadas (serie LE y benchmarks no lineales).
6. F. McKenna, M. H. Scott y G. L. Fenves, «Nonlinear finite-element analysis software architecture using object composition», *Journal of Computing in Civil Engineering*, 24(1), 2010.
7. OpenSees / OpenSeesPy 3.8.0.0 — manual de ejemplos y documentación de elementos (PEER, University of California, Berkeley).
8. A. K. Chopra, *Dynamics of Structures: Theory and Applications to Earthquake Engineering*, 5.ª ed., 2017 (edificio de corte, frecuencias propias).
9. S. Timoshenko y S. Woinowsky-Krieger, *Theory of Plates and Shells*, 2.ª ed., 1959, Tabla 8 (coeficientes de placa).
10. J. C. Simo y T. J. R. Hughes, *Computational Inelasticity*, Springer, 1998 (disipación plástica y balance de energía).

## Registro de verificación

- **Verificado** (derivación propia y contraste con texto de referencia): las soluciones del voladizo de Euler–Bernoulli y de Timoshenko; el marco de corte con viga rígida y sus cotas \(3EI/h^3\)–\(12EI/h^3\); la armadura de dos barras; el edificio de corte uniforme (comprobado en \(N=1\) y \(N=2\) contra \(1.0\) y \(0.6180/1.6180\) de \(\sqrt{k/m}\)); el coeficiente 0.00406 de la placa cuadrada simplemente apoyada (coherente con el límite de viga \(5/384=0.01302\)); la tabla de escalas de unidades; \(p_{obs}\), Richardson y el \(GCI\) con \(F_s=1.25\); el conteo de MCR por tipo de modelo; y las expresiones de equilibrio y de balance de energía.
- **Pendiente**: valores de referencia de MacNeal–Harder y de la serie NAFEMS; identificadores y valores de los casos publicados de OpenSees/PEER; umbral absoluto definitivo para magnitudes cercanas a cero; tolerancias de regresión del solver disperso.
- **Responsable de cerrar**: responsable de QA numérico del proyecto, con copia del artículo de MacNeal & Harder y de los manuales de NAFEMS y OpenSees.
