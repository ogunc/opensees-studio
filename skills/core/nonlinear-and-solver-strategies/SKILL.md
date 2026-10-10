---
name: nonlinear-and-solver-strategies
description: >-
  Especifica el bucle de solución no lineal de la plataforma: Newton-Raphson completo, modificado y BFGS, Krylov-Newton y búsqueda de línea; control del paso por carga, por desplazamiento y arc-length de Crisfield; y criterios de convergencia de fuerza, desplazamiento y energía con tolerancias y máximo de iteraciones. Cubre el diagnóstico de fallos (rigidez singular, salto de convergencia, bifurcación, inestabilidad), el análisis pushover (patrón de cargas, rótulas plásticas concentradas frente a plasticidad distribuida, curva capacidad-cortante, punto de desempeño), los efectos P-Delta por rigidez geométrica y los autovalores de pandeo. Úsala al configurar un caso no lineal, cuando un análisis no converge o diverge, o al auditar un pushover o un pandeo.
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [analysis, qa]
---

# Solución no lineal, pushover y estabilidad

## Cuándo usar esta skill

- Hay que fijar `integrator`, `algorithm`, `test`, `tolerance` y `max_iter` de un `StaticCase`, `TransientCase` o `PushoverCase` no lineal.
- El análisis **no converge o se corta**: «failed to converge», «ctest failed», residuo que oscila, iteraciones que crecen paso a paso, pivote nulo o negativo, matriz singular, o la rama que se devuelve hacia atrás.
- Hay que **leer o auditar una curva pushover**: patrón de cargas, cortante basal, desplazamiento de control, punto de desempeño.
- Aparece **pandeo o inestabilidad**: autovalores de pandeo, efectos P-Delta, amplificación de momentos por carga axil.
- Se implementa o revisa el bucle de solución: quién decide el tamaño de paso, quién cambia de algoritmo y cómo se registra el fallo.

**No usar** para la formulación y el ensamblaje de elementos (→ `core/fem-formulation-core`), las constitutivas y `FiberSection` (→ `core/fem-materials-and-sections`), la integración temporal y los autovalores de vibración (→ `core/modal-and-time-history`), ni para el patrón de cargas y el desplazamiento objetivo que exige un reglamento (→ `seismic/seismic-analysis-procedures` y el skill del código aplicable).

## Alcance y límites

Cubre el álgebra del bucle incremental-iterativo, la selección y el escalado del paso, los criterios de parada, el diagnóstico de fallos, la construcción e interpretación de la curva pushover y el tratamiento de la rigidez geométrica. Supone que la matriz tangente y el vector de fuerzas internas ya son correctos: un error de formulación no se arregla cambiando de algoritmo.

**No cubre** la plasticidad de la sección (→ `core/fem-materials-and-sections`), el amortiguamiento y la integración en el tiempo (→ `core/modal-and-time-history`), ni los valores reglamentarios de desempeño (→ `codes/`, `seismic/`). Todo dato normativo se lee de un archivo versionado, nunca se escribe en el motor.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Control del paso (carga, desplazamiento, arc-length) | sí | bloquear: determina qué magnitud se prescribe |
| Módulo y dirección de control (`control_node`, `control_dof` 1..6) | sí en desplazamiento y arc-length | bloquear |
| Desplazamiento objetivo y tamaño de paso, firmados | sí en pushover | bloquear |
| Patrón o patrones de carga pushover | sí en pushover | bloquear |
| Rigidez inicial (o módulo elástico) para normalizar | sí en arc-length | bloquear: el escalado de Crisfield lo necesita |
| Relación constitutiva con degradación | sí | advertir: una rama descendente sin degradación es un artefacto numérico |
| Unidades del modelo | sí | bloquear: el proyecto las declara |

## Fundamento y formulación

### 1. Equilibrio, residuo y tangente

$$ \mathbf R(\mathbf u,\lambda)=\lambda\,\mathbf F_{ref}-\mathbf F_{int}(\mathbf u),\qquad \text{equilibrio: } \mathbf R=\mathbf 0,\qquad \mathbf K_T(\mathbf u)=\frac{\partial \mathbf F_{int}}{\partial \mathbf u}\ \ [\text{N/m},\ \text{N}\cdot\text{m/rad}] $$

\(\mathbf u\in\mathbb R^n\): desplazamientos generalizados (m y rad); \(\lambda\): factor adimensional del patrón de referencia; \(\mathbf F_{ref}\): patrón aplicado (N y N·m); \(\mathbf F_{int}\): fuerzas internas (N y N·m); \(\mathbf R\): residuo, mismas unidades que \(\mathbf F\). A lo largo de la curva de equilibrio \(\mathbf F_{int}=\lambda\mathbf F_{ref}\) y \(\mathrm d\lambda/\mathrm ds=\mathbf n^{\mathsf T}\mathbf F_{ref}\), con \(\mathbf n=\mathrm d\mathbf u/\mathrm ds\) la tangente normalizada de la curva.

### 2. Algoritmos de iteración

| Algoritmo | Paso de iteración | Convergencia | Factorizaciones por paso | Uso |
|---|---|---|---|---|
| Newton-Raphson completo | \(\mathbf K_T(\mathbf u_k)\Delta\mathbf u_k=\mathbf R_k\) | cuadrática | 1 por iteración | defecto con no linealidad fuerte |
| Newton modificado | \(\mathbf K_T(\mathbf u_0)\Delta\mathbf u_k=\mathbf R_k\) | lineal | 1 por paso | tangente cara y respuesta regular |
| BFGS | actualización de secante de \(\mathbf K_T\) | superlineal | 1 por paso | tangente costosa, curvatura suave |
| Krylov-Newton | NR con el sistema resuelto en subespacio de Krylov | superlineal | ninguna explícita | \(n\) grande, refactorizar domina |
| Broyden | actualización de rango 1, no simétrica | superlineal | 1 por paso | respaldo cuando NR falla |

Actualización BFGS de \(\mathbf B_k\approx\mathbf K_T\), con \(\mathbf s_k=\Delta\mathbf u_k\) (m) y \(\mathbf y_k=\mathbf F_{int}(\mathbf u_{k+1})-\mathbf F_{int}(\mathbf u_k)\) (N):

$$ \mathbf B_{k+1}=\mathbf B_k+\frac{\mathbf y_k\mathbf y_k^{\mathsf T}}{\mathbf y_k^{\mathsf T}\mathbf s_k}-\frac{\mathbf B_k\mathbf s_k\mathbf s_k^{\mathsf T}\mathbf B_k}{\mathbf s_k^{\mathsf T}\mathbf B_k\mathbf s_k},\qquad \text{solo si } \mathbf y_k^{\mathsf T}\mathbf s_k>0 $$

La condición de curvatura es obligatoria: si \(\mathbf y_k^{\mathsf T}\mathbf s_k\le0\) (descarga, cambio de estado de la sección) la actualización **se omite**; aplicarla deja \(\mathbf B\) indefinida y produce divergencia silenciosa. Krylov-Newton reconstruye el subespacio con los últimos \(m\) pares \((\Delta\mathbf u,\mathbf R)\), \(m\approx2\ldots10\), sin armar \(\mathbf K_T\).

### 3. Búsqueda de línea

Se busca \(\eta\in(0,1]\) que reduzca la medida escalar de trabajo \(\pi(\eta)=\mathbf R(\mathbf u_k+\eta\Delta\mathbf u_k)^{\mathsf T}\Delta\mathbf u_k\) (N·m) mediante retroceso tipo Armijo: se acepta \(\eta\) si \(\lVert\mathbf R(\mathbf u_k+\eta\Delta\mathbf u_k)\rVert\le(1-c\eta)\lVert\mathbf R(\mathbf u_k)\rVert\), y si no \(\eta\leftarrow\eta/2\). \(c=10^{-4}\) es un valor por defecto del programa (parámetro de software, no normativo). La búsqueda de línea **no salva un punto límite**: en el pliegue la dirección de Newton es ortogonal al eje de carga y ningún \(\eta\) alcanza el equilibrio; eso lo resuelve el arc-length.

### 4. Control del paso

- **Carga**: se fija \(\Delta\lambda\) (adimensional) y se itera \(\mathbf u\). Falla en el punto límite, donde \(\mathbf K_T\) se vuelve singular y \(\mathrm d\lambda/\mathrm du=0\).
- **Desplazamiento**: se prescribe \(\Delta u_d\) (m o rad) en el GDL de control. Con \(\mathbf K_T\Delta\mathbf u_I=\mathbf R_k\) y \(\mathbf K_T\Delta\mathbf u_{II}=\mathbf F_{ref}\), resulta \(\Delta\mathbf u=\Delta\mathbf u_I+\Delta\lambda\Delta\mathbf u_{II}\) y \(\Delta\lambda=(\Delta u_d-\Delta u_{I,c})/\Delta u_{II,c}\), con el subíndice \(c\) en el GDL de control; \(\Delta u_{II}\) va en m por unidad de \(\lambda\) y \(\Delta\lambda\) es adimensional. Atraviesa puntos límite de carga, no *snap-back*.
- **Arc-length de Crisfield (esférico)**: restricción \(\Delta\mathbf u^{\mathsf T}\Delta\mathbf u+\psi^2\Delta\lambda^2=\Delta s^2\), con \(\Delta s\) el radio de arco (m) y \(\psi^2=\Delta\mathbf u_1^{\mathsf T}\Delta\mathbf u_1/\Delta\lambda_1^2\) (m²) evaluado en el **primer** paso. Sustituyendo la descomposición anterior queda \(a\Delta\lambda^2+b\Delta\lambda+c=0\), con \(a=\Delta\mathbf u_{II}^{\mathsf T}\Delta\mathbf u_{II}+\psi^2\), \(b=2\Delta\mathbf u_I^{\mathsf T}\Delta\mathbf u_{II}\) y \(c=\Delta\mathbf u_I^{\mathsf T}\Delta\mathbf u_I-\Delta s^2\), todos en m². La variante **cilíndrica** usa \(\Delta\mathbf u^{\mathsf T}\Delta\mathbf u=\Delta s^2\) y conserva el \(\Delta\lambda\) anterior.
- **Selección de raíz**: se toma la raíz que conserva el sentido de avance, \(\Delta\mathbf u_{prev}^{\mathsf T}\Delta\mathbf u_{nuevo}>0\). Si las dos raíces dan el mismo signo, el paso cruzó un punto límite y hay que reducir \(\Delta s\). \(\Delta s\) no es un parámetro normativo: se calibra por prueba (\(10^{-3}\)–\(10^{-2}\) del desplazamiento total esperado) y se registra con el caso.

### 5. Criterios de convergencia

| Criterio | Expresión | Unidades | Mide |
|---|---|---|---|
| Fuerza (`NormUnbalance`) | \(\lVert\mathbf R_k\rVert\le tol\,\lVert\mathbf R_0\rVert\) | N, N·m | desequilibrio |
| Desplazamiento (`NormDispIncr`) | \(\lVert\Delta\mathbf u_k\rVert\le tol\,\lVert\Delta\mathbf u_0\rVert\) | m, rad | tamaño del paso |
| Energía (`EnergyIncr`) | \(\lvert\Delta\mathbf u_k^{\mathsf T}\mathbf R_k\rvert\le tol\,\lvert\Delta\mathbf u_0^{\mathsf T}\mathbf R_0\rvert\) | N·m | trabajo residual |
| Desplazamiento relativo (`RelativeNormDispIncr`) | \(\lVert\Delta\mathbf u_k\rVert\le tol\,\lVert\Delta\mathbf u_{paso}\rVert\) | m, rad | avance dentro del paso |

El subíndice \(0\) es la primera iteración del paso. Se converge solo si **todos** los criterios activos se cumplen. Valores por defecto del programa: `tolerance = 1e-6` y `max_iter = 25` en `TransientCase` y `PushoverCase`, `1e-8` en `StaticCase` (ya existen en el modelo; no son normativos). Rango recomendado: \(10^{-6}\)–\(10^{-10}\) para fuerza y energía, \(10^{-5}\)–\(10^{-8}\) para desplazamiento. Aflojar la tolerancia para «que converja» es un parche: se fija por el error admisible en la respuesta, no por el coste.

> ⚠️ VERIFICAR: los denominadores exactos de normalización de cada `test` en OpenSeesPy 3.8.0 (`NormUnbalance`, `NormDispIncr`, `EnergyIncr`, `RelativeNormDispIncr`) no se comprobaron contra el código fuente de esa versión. Se comprueban en el árbol fuente de OpenSees del *tag* 3.8.0 (`SRC/analysis/algorithm/equiSolnAlgo/`). Mientras tanto el programa registra en el manifiesto el nombre y el valor de `test` usados, sin afirmar a qué magnitud se normalizó.

### 6. Diagnóstico de fallos

| Síntoma | Causa probable | Acción automática |
|---|---|---|
| Pivote nulo o negativo al factorizar | \(\mathbf K_T\) singular: mecanismo, punto límite, GDL sin rigidez | reducir el paso a la mitad, hasta 5 veces; luego arc-length |
| Un pivote negativo con residuo pequeño | equilibrio inestable alcanzado, pasado el pliegue | continuar con arc-length; no abortar |
| \(\lVert\mathbf R\rVert\) cae y vuelve a subir 2–3 órdenes | cambio de estado de sección (fisura, rótula) con tangente desactualizada | reiniciar la tangente (`-initial`) y repetir el paso |
| La norma baja pero no alcanza la tolerancia en `max_iter` | tolerancia inalcanzable por redondeo, o paso demasiado grande | dividir el paso en 2 y reintentar |
| \(\Delta\lambda<0\) en control por carga | *snap-back*: el control por carga no lo representa | cambiar a arc-length esférico |
| El autovalor menor de \(\mathbf K_T\) cambia de signo | bifurcación: dos caminos de equilibrio | registrar el modo y avisar; no seguir a ciegas |

### 7. Análisis pushover

**Patrón de cargas.** Los habituales son uniforme (\(F_i=w_i/\sum_j w_j\cdot V_{ref}\)), triangular invertido (\(F_i=w_ih_i^k/\sum_jw_jh_j^k\), con \(h_i\) la altura en m y \(k\) un exponente adimensional) y modal (\(F_i\propto m_i\phi_{i1}\)). La curva depende del patrón: se reporta la envolvente de los patrones aplicados, nunca uno solo. El patrón exigido por un reglamento se lee del skill del código.

**Curva capacidad-cortante.** \(V_b=\sum_r R_r\) (N) es la suma de las reacciones horizontales en los nodos de la base en la dirección de empuje, y \(u_c\) (m) el desplazamiento del GDL de control. Se grafica \(V_b\) contra \(u_c\) y se registran \(V_y\) (primera fluencia), \(V_{max}\), \(u_{max}\) y la caída de resistencia posterior.

**Espectro de capacidad** (solo si se pide), con \(\boldsymbol\phi_1\) normalizado a \(\phi_{r,1}=1\) en el nivel de control:

$$ S_a=\frac{V_b}{\alpha_1W}\ [\text{m/s}^2],\qquad S_d=\frac{u_c}{PF_1\phi_{r,1}}\ [\text{m}],\qquad PF_1=\frac{\sum_im_i\phi_{i1}}{\sum_im_i\phi_{i1}^2},\qquad \alpha_1=\frac{\left(\sum_im_i\phi_{i1}\right)^2}{\left(\sum_im_i\right)\left(\sum_im_i\phi_{i1}^2\right)} $$

\(W=\sum_i m_i g\) (N) con \(g=9.80665\ \text{m/s}^2\); \(PF_1\) y \(\alpha_1\) son adimensionales. Si el código publica \(S_a\) en g, se declara explícitamente.

**Rótula concentrada frente a plasticidad distribuida.** La rótula concentrada usa \(M_p\) (N·m) y una longitud plástica \(L_p\) (m); el desplazamiento plástico de la punta de un voladizo de altura \(h\) (m) con curvaturas \(\phi_y,\phi_u\) (1/m) es

$$ \Delta_p=(\phi_u-\phi_y)L_p\left(h-\frac{L_p}{2}\right)\ [\text{m}] $$

La plasticidad distribuida (sección de fibras, integración en puntos de Gauss) no necesita \(L_p\), pero exige convergencia de malla y cuesta más por iteración. Si se publica un resultado con rótula concentrada, deben declararse \(L_p\) y su fuente.

> ⚠️ VERIFICAR: la expresión de \(L_p\) y la capacidad de rotación plástica \(\theta_p\) dependen del elemento, del confinamiento y del código aplicable (ASCE 41-23, tablas 9-x y 10-x; FEMA 356, tablas 6-x) y no se pudieron leer del documento oficial. El programa debe leerlos de `data/<codigo>/plastic-hinge-rotation.json`, con campos `source` y `verified_on`, y no incluirlos en el código.

**Punto de desempeño.** Se obtiene por el *coefficient method* (desplazamiento objetivo) o por el *capacity spectrum method* (intersección con el espectro reducido por amortiguamiento equivalente). Ambos usan coeficientes publicados (\(C_0\ldots C_3\), \(\kappa\), amortiguamiento efectivo) que no se inventan:

> ⚠️ VERIFICAR: los coeficientes del *coefficient method* y las tablas de amortiguamiento efectivo del *capacity spectrum method* (ASCE 41-23 §7.4.3.3 y ATC-40 cap. 8) no se transcriben. Se comprueban en el estándar impreso y se cargan desde un archivo de datos versionado; el punto de desempeño nunca se calcula con constantes embebidas.

### 8. P-Delta y autovalores de pandeo

Rigidez geométrica consistente de un elemento barra 2D de longitud \(L\) (m) y axil \(P\) (compresión positiva, N), en el orden de GDL \((u_1,v_1,\theta_1,u_2,v_2,\theta_2)\); las entradas de traslación quedan en N/m y las de rotación en N·m:

$$ \mathbf K_g=\frac{P}{30L}\begin{bmatrix}0&0&0&0&0&0\\0&36&3L&0&-36&3L\\0&3L&4L^2&0&-3L&-L^2\\0&0&0&0&0&0\\0&-36&-3L&0&36&-3L\\0&3L&-L^2&0&-3L&4L^2\end{bmatrix} $$

La tangente del análisis con P-Delta es \(\mathbf K+\mathbf K_g\) y debe reensamblarse si \(P\) cambia de forma significativa; el procedimiento de dos pasadas (resolver, leer axiles, reensamblar, volver a resolver) es el mínimo aceptable. El pandeo sale del problema de autovalores generalizado

$$ \left(\mathbf K+\lambda\mathbf K_g(\mathbf F_{ref})\right)\boldsymbol\phi=\mathbf 0,\qquad \det\!\left(\mathbf K+\lambda\mathbf K_g\right)=0,\qquad P_{cr}=\lambda_{\min}P_{ref} $$

con \(\lambda\) adimensional y \(P_{ref}\) el axil del patrón de referencia. Para una columna biarticulada y una en voladizo, \(P_{cr}=\pi^2EI/L^2\) y \(P_{cr}=\pi^2EI/(4L^2)\) (\(EI\) en N·m²). La amplificación por P-Delta **no** es \(1/(1-P/P_{cr})\) en general: en un voladizo con carga lateral en la punta y \(k=\sqrt{P/EI}\) (1/m), el momento en la base amplifica como \(\tan(kL)/(kL)\); con \(P=0.5P_{cr}\) eso da 1.8168, no 2.0. La comprobación reglamentaria del coeficiente \(\theta\) pertenece a `seismic/seismic-analysis-procedures`.

> ⚠️ VERIFICAR: el comando exacto de OpenSeesPy 3.8.0 que resuelve el pandeo a partir de un estado con carga axil de referencia, y si reutiliza el mismo motor de autovalores que el análisis modal, no se comprobó contra esta compilación. Se comprueba ejecutando un caso biarticulado con \(P_{cr}\) conocido. Mientras tanto el pandeo se resuelve en `core/` con NumPy sobre \(\mathbf K\) y \(\mathbf K_g\) ensambladas a partir de los axiles que devuelve el solver, y se contrasta con \(\pi^2EI/L^2\).

## Procedimiento

1. Verificar que el caso es realmente no lineal (material no lineal, P-Delta, contacto, gran desplazamiento); un caso lineal con `algorithm = Newton` solo gasta iteraciones.
2. Normalizar el patrón de referencia a una fuerza total conocida en N y dejar que \(\lambda\) haga el resto.
3. Elegir el control del paso: carga si la respuesta es monótona y estable, desplazamiento para pushover con nodo de control, arc-length si se espera punto límite, *snap-through* o *snap-back*.
4. Fijar tolerancia y máximo de iteraciones por criterio, con al menos un criterio de fuerza y uno de desplazamiento o energía.
5. Arrancar con Newton-Raphson completo y tangente inicial.
6. Si un paso no converge en `max_iter`, ejecutar la escalera: reiniciar tangente → búsqueda de línea → Broyden/Krylov-Newton → dividir el paso → cambiar a arc-length.
7. Al converger, verificar que la solución es estable (pivotes del mismo signo que en el paso anterior) y que \(\Delta\lambda\) tiene el signo esperado; registrar por paso \(\lambda\), \(u_c\), \(\lVert\mathbf R\rVert\), iteraciones, algoritmo, bandera de escalera y motivo.
8. En pushover, acumular \(V_b\) y \(u_c\), detectar primera fluencia, máximo y caída, y cortar cuando la deriva de control supere el objetivo o la resistencia caiga bajo el umbral declarado.
9. En pandeo, resolver el autovalor, contrastarlo con la solución cerrada del mismo modelo y registrar la malla usada.

## Implementación en la plataforma

```python
# src/opensees_studio/core/analysis/solver_strategies.py   (core puro: sin Qt, sin OpenSeesPy)
@dataclass(frozen=True)
class StepPlan:
    control: Literal["load", "disp", "arc"]
    delta_lambda: float   # adimensional (control por carga)
    delta_u: float        # m o rad (control por desplazamiento / radio de arco)

def convergence_checks(test: str, tol: float, max_iter: int) -> tuple[str, ...]: ...
def next_step_plan(plan: StepPlan, attempt: int, state: SolveState) -> StepPlan:
    """Escalera: 0 intacto, 1 tangente, 2 linea, 3 broyden/krylov, 4 medio paso."""
def arclength_root(a: float, b: float, c: float, du_prev: np.ndarray) -> float:
    """Raiz de a*dL^2+b*dL+c=0 que conserva du_prev . du > 0. a, b, c en m^2."""
def plastic_tip_displacement(phi_y: float, phi_u: float, lp: float, h: float) -> float: ...

# src/opensees_studio/core/analysis/stability.py        (core puro)
def geometric_stiffness_2d(P: float, L: float) -> np.ndarray: ...   # 6x6, N/m y N*m
def buckling_factors(K: np.ndarray, Kg: np.ndarray, n: int) -> list[float]: ...
def amplification_exact(P: float, EI: float, L: float) -> float:
    """tan(kL)/(kL), k = sqrt(P/EI); P en N, EI en N*m^2, L en m."""
```

Reglas de arquitectura:

- `core/analysis/` decide, calcula y valida; **no** importa Qt ni OpenSeesPy. Lo que necesita del solver entra como `numpy.ndarray` o escalares (axiles, reacciones, desplazamientos).
- El solver se usa **solo** desde `services/opensees_runner.py`, único sitio donde se emiten `ops.test`, `ops.algorithm` y `ops.integrator`. La escalera de recuperación ya existe allí (`Newton -initial`, `NewtonLineSearch`, `Broyden`, división de paso): la tabla de decisión se extrae a `core/` y el servicio la ejecuta.
- Los nombres de algoritmo, test e integrador son los que ofrece y acepta esta compilación: `Linear`, `Newton`, `ModifiedNewton`, `KrylovNewton`, `BFGS`, `Broyden`; `NormDispIncr`, `NormUnbalance`, `EnergyIncr`, `RelativeNormDispIncr`; `LoadControl`, `DisplacementControl`, `ArcLength`.
- Un tipo de análisis nuevo que use autovalores (pandeo) se declara en la reejecución del CLI (`_uses_eigen` / `_routed_to_arpack` en `run.py`) y se enruta con `core.modal.resolve_modal_solver`; nunca se añade una segunda llamada ARPACK al mismo proceso, porque deja de ser reproducible.
- Los umbrales y tolerancias por defecto viven en un archivo de datos versionado; cambiar de edición de norma no toca el motor.

## Datos normativos

Esta skill es de jurisdicción agnóstica: no publica coeficientes. Lo que el programa **no** debe incrustar y de dónde lo lee:

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Patrón de cargas pushover exigido | skill del código aplicable | no — `VERIFICAR` |
| Desplazamiento objetivo, \(C_0\ldots C_3\), \(\kappa\) | ASCE 41-23 §7.4.3.3 / ATC-40 cap. 8 | no — `VERIFICAR` |
| Capacidad de rotación plástica \(\theta_p\) y \(L_p\) | ASCE 41-23 / FEMA 356, tablas por elemento | no — `VERIFICAR` |
| Comando de pandeo y normalización de los `test` | fuente de OpenSees 3.8.0 | no — `VERIFICAR` |
| \(P_{cr}=\pi^2EI/L^2\) y \(\pi^2EI/(4L^2)\) | mecánica de sólidos (Euler) | sí (álgebra propia) |
| \(\mathbf K_g\) consistente 2D y \(\tan(kL)/(kL)\) del voladizo con carga en punta | Przemieniecki; McGuire, Gallagher y Ziemian; solución cerrada del beam-column | sí |

Todo dato de las cuatro primeras filas vive en `data/` con `source` (norma, edición, tabla o artículo) y `verified_on`, y tiene prueba unitaria contra la tabla publicada.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| NR, 1 GDL cúbico | \(F_{int}=1000u+100u^3\ \text{N}\), \(P=2000\ \text{N}\), \(u_0=0\) | \(u=1.594562116631153\ \text{m}\) en 5 iteraciones | 1e-12 rel. | cálculo propio |
| Newton modificado | ídem, \(\mathbf K_T\) congelada en \(u_0=0\) | mismo \(u\), 66 iteraciones, 1 factorización | 1e-8 rel. | cálculo propio |
| BFGS | ídem, \(\mathbf B_0=K_T(0)\) | mismo \(u\) en 7 iteraciones; \(\mathbf B\to1762.79\ \text{N/m}\) | 1e-10 rel. | cálculo propio |
| Búsqueda de línea | \(F_{int}=10^6u^3\ \text{N}\), \(P=8000\ \text{N}\), \(u_0=0.05\ \text{m}\) | Newton puro salta a \(u_1=1.1\ \text{m}\); con Armijo \(\eta<1\) y \(\lVert R\rVert\) decreciente; converge a \(u=0.2\ \text{m}\) | 1e-9 rel. | cálculo propio |
| Control por desplazamiento | ídem, \(u_d=0.2\ \text{m}\) en 20 pasos | \(\lambda=1.0\) en cada paso tras el primero | 1e-9 abs. | cálculo propio |
| Punto límite | \(F_{int}=10^6u\,e^{-u/0.01}\ \text{N}\), \(P=1000\ \text{N}\) | \(\lambda_{cr}=3.678794\) en \(u=0.01\ \text{m}\); con arc-length esférico existe un punto con \(u=0.02\ \text{m}\), \(\lambda=2.706706\) | 1e-6 abs.; 1 % rel. | cálculo propio |
| Raíz de arc-length | \(\Delta u_I=0.3\ \text{m}\), \(\Delta u_{II}=1.2\ \text{m}\), \(\psi^2=0.25\ \text{m}^2\), \(\Delta s^2=0.5\ \text{m}^2\) | raíces \(0.323620\) y \(-0.749656\); se elige la de avance | 1e-6 abs. | cálculo propio |
| Pandeo (biarticulado y voladizo) | \(EI=10^6\ \text{N·m}^2\), \(L=4\ \text{m}\), 10 elementos | \(P_{cr}=616850.28\ \text{N}\) y \(P_{cr}=154212.57\ \text{N}\) | 1 % rel. | Euler |
| Amplificación P-Delta | \(P=0.5P_{cr}\), voladizo, carga lateral en punta | \(M_{base}/(HL)=1.816828\) | 1e-4 abs. (cerrada), 1 % (MEF) | solución cerrada |
| Cortante basal de fluencia | \(M_p=900\ \text{kN·m}\), \(h=3\ \text{m}\) | \(V_y=300\ \text{kN}\) | 1e-9 rel. | equilibrio |
| Desplazamiento plástico | \(\phi_u-\phi_y=0.02\ \text{1/m}\), \(L_p=0.4\ \text{m}\), \(h=3\ \text{m}\) | \(\Delta_p=0.0224\ \text{m}\) | 1e-6 abs. | fórmula de rótula |
| Invariancia de unidades | el caso NR en N/m y en kN/mm | mismo número de iteraciones y misma \(u\) | idéntico | arquitectura |

Además, la curva pushover de un voladizo elástico-lineal debe dar exactamente \(V_b=3EIu_c/h^3\) hasta la fluencia, y todo caso no lineal se contrasta contra la solución lineal en el primer paso (comprobación de que la tangente inicial está bien ensamblada).

## Errores frecuentes y trampas

1. **Norma del residuo con unidades mezcladas.** \(\lVert\mathbf R\rVert\) suma fuerzas (N) y momentos (N·m) en el mismo vector; con longitudes en m y fuerzas en N el bloque de momentos domina por órdenes de magnitud y el criterio de fuerza mide algo distinto de lo que se cree.
2. **Confundir convergencia con corrección, o aflojar la tolerancia para salvar un caso.** Converger con un paso demasiado grande deja intacto el error de truncamiento, y el caso que dejó de converger lo hizo por una razón física (rótula, punto límite, tangente indefinida): aflojar oculta el diagnóstico y publica un resultado sesgado.
3. **Aplicar BFGS sin condición de curvatura.** En descarga \(\mathbf y^{\mathsf T}\mathbf s\le0\); aplicarla deja \(\mathbf B\) indefinida y diverge sin mensaje.
4. **Esperar que la búsqueda de línea salve el punto límite.** En el pliegue la dirección es ortogonal a la carga y el retroceso baja \(\eta\) hasta el mínimo sin encontrar equilibrio; hay que cambiar a arc-length.
5. **Elegir la raíz equivocada del arc-length.** Tomar siempre la raíz positiva de \(\Delta\lambda\) hace rebotar el análisis en el pliegue y repetir la rama ya recorrida.
6. **Contaminar el escalado \(\psi^2\) con un primer paso anómalo.** \(\psi^2\) depende del paso inicial y se usa en todo el análisis; un primer paso mal medido sesga la métrica de arco completa.
7. **No reensamblar \(\mathbf K_g\) cuando el axil cambia de signo.** Un arriostramiento que primero tracciona y luego comprime invierte el signo de \(\mathbf K+\mathbf K_g\); la rigidez geométrica se reensambla por estado.
8. **Usar \(1/(1-P/P_{cr})\) como amplificación universal.** Vale como cota en pórticos con carga repartida; en un voladizo con carga puntual sobreestima un 10 % a \(P=0.5P_{cr}\) (2.0 frente a 1.8168).
9. **Componer mal la curva pushover.** Un solo patrón de cargas no es una envolvente (hacen falta al menos el uniforme y el triangular o modal), y no se mezclan en la misma curva la rótula concentrada y la plasticidad distribuida: \(\Delta_p\) crece linealmente con \(L_p\), que debe declararse.
10. **Añadir una segunda llamada ARPACK al proceso para el pandeo.** La segunda llamada al mismo motor en el mismo proceso no es reproducible (cambia signos y rota autovalores repetidos); el caso debe reejecutarse en un hijo nuevo.
11. **Redondear \(\lambda\), \(u_c\) o \(V_b\) antes de la comparación final.** Los pasos intermedios se guardan en doble precisión; redondear es cosa de la capa de presentación.

## Interfaz de salida

- Tabla por paso con el control del paso, \(\Delta\lambda\) o \(\Delta s\), algoritmo, `test`, tolerancia y `max_iter` **efectivamente usados** (no solo los pedidos), más \(\lambda\), \(u_c\), \(\lVert\mathbf R\rVert\), iteraciones y motivo de la escalera.
- Avisos explícitos: pivote negativo, cambio de signo del autovalor de \(\mathbf K_T\), reducción de paso, cambio a arc-length, entrada en rama descendente.
- Curva pushover: \(u_c\) [m] contra \(V_b\) [N] (kN en presentación), con \(V_y\), \(V_{max}\), \(u_{max}\), ductilidad y patrón de cargas declarado.
- Pandeo: \(\lambda_{cr}\), \(P_{cr}\) [N], malla usada y comparación con la solución cerrada del mismo modelo.
- Trazabilidad: versión de la skill, edición de la norma aplicada (si la hay), `verified_on` del archivo de datos y hash del modelo resuelto.

## Referencias

1. M. A. Crisfield, *Non-linear Finite Element Analysis of Solids and Structures*, vol. 1, Wiley (1991) — arc-length y control de paso.
2. K. J. Bathe, *Finite Element Procedures*, 2.ª ed., Prentice Hall (2014) — Newton-Raphson, búsqueda de línea, criterios de convergencia.
3. W. McGuire, R. H. Gallagher y G. C. Ziemian, *Matrix Structural Analysis*, 2.ª ed. (2000) — rigidez geométrica y pandeo de pórticos.
4. OpenSees, *Command Language Manual*, edición de la versión 3.8.0 (2025) — nombres de `test`, `algorithm` e `integrator`.
5. ATC, *ATC-40: Seismic Evaluation and Retrofit of Concrete Buildings* (1996).
6. ASCE/SEI 41-23, *Seismic Evaluation and Retrofit of Existing Buildings* (2023).
7. FEMA, *FEMA 356: Prestandard and Commentary for the Seismic Rehabilitation of Buildings* (2000).
8. M. J. N. Priestley, F. Seible y G. M. Calvi, *Seismic Design and Retrofit of Bridges*, Wiley (1996) — longitud plástica equivalente.
9. D. G. Luenberger y Y. Ye, *Linear and Nonlinear Programming*, 4.ª ed., Springer (2016) — BFGS, Armijo y condición de curvatura.

## Registro de verificación

- **Verificado en esta revisión**: el álgebra del bucle incremental-iterativo y los cuatro criterios de convergencia; la cuadrática de Crisfield y su regla de selección de raíz; la rigidez geométrica consistente 2D y su simetría; las cargas de Euler biarticulada y en voladizo; la amplificación \(\tan(kL)/(kL)\) del voladizo con carga puntual; la fórmula del desplazamiento plástico; y los nombres de algoritmos, tests e integradores y los valores por defecto `tolerance`/`max_iter`, leídos del código del proyecto. Todos los casos numéricos de la tabla de verificación se recalcularon de forma independiente (álgebra cerrada y doble precisión) antes de escribirlos.
- **Pendiente**: los cuatro `VERIFICAR` de la sección de datos normativos (comando de pandeo en OpenSeesPy 3.8.0, normalización interna de los `test`, coeficientes de desempeño y capacidades de rotación plástica). Por eso el `status` es `draft`.
- **Responsable de cerrar**: quien mantenga `core/analysis/`, con acceso al árbol fuente de OpenSees 3.8.0 y a copias licenciadas de ASCE 41-23 y FEMA 356.
- **Fecha de revisión**: 2026-02-14.
