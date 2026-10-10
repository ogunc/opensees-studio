---
name: modal-and-time-history
description: >-
  Especifica y verifica el análisis dinámico lineal de la plataforma: autovalores
  generalizados, solver denso frente a ARPACK, determinismo con modos degenerados
  (ortogonalización respecto de la masa, normalización de signo), participación y
  masa modal efectiva acumulada, amortiguamiento de Rayleigh a partir de dos modos,
  e integración en el tiempo (Newmark-β media y lineal, HHT-α, diferencia central y
  su paso crítico), con excitación uniforme por registro sísmico, corrección de
  línea base, interpolación y escalado a un espectro objetivo. Úsala al implementar
  o auditar un caso `Modal` o `Transient`, si los períodos o signos modales no son
  reproducibles entre corridas, si la masa modal acumulada no alcanza el umbral, si
  hay pares de autovalores repetidos, al fijar α y β de Rayleigh, o al corregir y
  escalar un registro antes de excitar la base.
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [analysis, seismic, qa]
---

# Análisis modal e integración en el tiempo

## Cuándo usar esta skill

- Se implementa o audita un caso de análisis `Modal` (autovalores) o `Transient`
  (integración directa en el tiempo).
- Los períodos, las formas modales o los signos de las formas cambian entre dos
  corridas idénticas, o entre la corrida directa y la corrida por CLI.
- Hay que decidir cuántos modos extraer y justificar la masa modal efectiva
  acumulada para el análisis espectral o sísmico.
- Hay que fijar el amortiguamiento: α y β de Rayleigh, o ζ objetivo en uno o dos
  modos, y se sospecha de sobreamortiguación en modos altos.
- Un registro sísmico debe corregirse de línea base, interpolarse a un Δt único y
  escalarse a un espectro objetivo antes de alimentar una excitación uniforme.
- El paso de tiempo elegido produce crecimiento monótono de la respuesta, o el
  integrador explícito revienta.

**No usar** para el espectro de diseño ni para coeficientes normativos (→
`codes/...`, p. ej. `codes/asce7-22-seismic-design`), para la combinación de
respuestas modales con reglas CQC/SRSS (→ `seismic/...`), ni para el modelado de
masas, diafragmas y elementos (→ las skills de modelado correspondientes).

## Alcance y límites

Cubre el análisis dinámico **lineal**: extracción de autovalores, participación
modal, y respuesta en el tiempo por integración directa con excitación uniforme en
la base. Supone matriz de masa definida positiva, matriz de rigidez simétrica y
amortiguamiento viscoso equivalente.

Queda fuera: análisis no lineal en el tiempo (plasticidad, gaps, contacto) más allá
de lo que tolera el esquema de Newmark con rigidez tangente; análisis *multiple
support* con desfase de apoyos; interacción suelo-estructura; y la generación del
espectro objetivo, que entra como dato.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Matriz de masa del modelo (consistente o concentrada) | sí | bloquear: sin masa no hay período |
| Número de modos `n_modes` | sí | partir de `n_modes = min(3·n_pisos, n_gdl_libres)` y verificar masa acumulada |
| Amortiguamiento ζ objetivo y pares de modos o frecuencias | sí | bloquear; no se asume 5 % sin declararlo |
| Registro: aceleración, `dt`, unidades | sí | bloquear: no se infiere la unidad del registro |
| Espectro objetivo con su fuente | si se escala | bloquear el escalado; se permite correr sin escalar dejando constancia |
| Dirección de excitación (DOF 1..6) y factor | sí | bloquear |
| Condiciones iniciales (u₀, v₀) | no | cero |

Unidades internas SI coherentes: m, N, kg, s, Pa. `g = 9.80665 m/s²`. El registro
se convierte a m/s² al importarlo, y se declara la unidad de origen del archivo.

## Fundamento y formulación

### 1. Problema de autovalores generalizado

Para vibración libre sin amortiguamiento, con **K** la matriz de rigidez global
(N/m) y **M** la matriz de masa (kg):

$$\mathbf{K}\,\boldsymbol{\phi}_i = \lambda_i\,\mathbf{M}\,\boldsymbol{\phi}_i,
\qquad \lambda_i = \omega_i^2 \ \ [\text{rad}^2/\text{s}^2], \qquad
T_i = \frac{2\pi}{\omega_i} \ \ [\text{s}]$$

Masa-ortogonalidad y normalización de masa unitaria:

$$\boldsymbol{\phi}_j^{\mathsf T}\mathbf{M}\boldsymbol{\phi}_i = \delta_{ij},
\qquad \boldsymbol{\phi}_j^{\mathsf T}\mathbf{K}\boldsymbol{\phi}_i = \lambda_i\,\delta_{ij}$$

Con **M** definida positiva, la forma autoacoplada que usan los solvers densos es
$\mathbf{A} = \mathbf{L}^{-1}\mathbf{K}\mathbf{L}^{-\mathsf T}$ con
$\mathbf{M} = \mathbf{L}\mathbf{L}^{\mathsf T}$ (Cholesky), simétrica y con los
mismos λ. Si **M** es singular (concentrada con DOF sin masa), ningún solver
simétrico sirve: los DOF sin masa deben eliminarse por *static condensation* antes
de extraer autovalores.

> ⚠️ VERIFICAR: la convención exacta de OpenSeesPy al devolver `eigen` (orden,
> signo, y el tratamiento de λ ≤ 0 para modos de cuerpo rígido) debe confirmarse
> contra la documentación de la versión instalada (3.8.0.0) y con una prueba de
> integración; el programa debe leerla de un archivo de datos versionado
> (`data/modal/solver_conventions.json`) y no codificarla.

### 2. Solvers densos frente a iterativos

| Familia | Coste | Uso correcto | Riesgo |
|---|---|---|---|
| Denso (`fullGenLapack`) | O(n³) | n_gdl pequeño/medio (≤ ~500) | memoria y tiempo; determinista |
| Iterativo (ARPACK, `genBandArpack`) | O(n·n_modos²) por iteración | n_gdl grande, pocos modos | vector de arranque aleatorio; modos repetidos mal resueltos |
| Banda simétrica (`symmBandLapack`) | O(n·b²) | solo con masa definida positiva | falla con DOF sin masa |

Regla de la plataforma (implementada en `core/modal.resolve_modal_solver`): denso
hasta `DENSE_EIGEN_MAX_FREE_DOF = 500` gdl libres (override por
`OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF`), ARPACK por encima; y ARPACK retrocede a
denso cuando `2 * n_modes >= n_free`, porque el espacio de Arnoldi no cabe y el
solver aborta con `_saupd info = -9999`.

### 3. Determinismo: modos degenerados y signo

ARPACK conserva su vector de arranque aleatorio dentro del proceso, así que **solo
la primera llamada eigen de un proceso es reproducible**; la segunda invierte
signos y rota un par de autovalores repetidos. Consecuencias obligatorias:

1. Un proceso no ejecuta dos extracciones ARPACK: el caso se re-ejecuta en un hijo
   nuevo.
2. Todo par degenerado (λ iguales dentro de `1e-6` relativo) se re-ortogonaliza
   respecto de la masa dentro del subespacio propio, porque el solver denso puede
   devolver una base oblicua.
3. Toda forma modal que llegue a pantalla o a combinación se normaliza de signo:
   componente de mayor valor absoluto positiva; empates dentro de `1e-9` relativo
   los decide el índice de DOF más bajo.
4. El solver realmente usado y `n_free_dof` se guardan en los resultados.

### 4. Participación modal y masa efectiva

Con **ι** el vector de influencia de la dirección (unos en los DOF de traslación
excitados) y **M** la matriz de masa:

$$\Gamma_i = \frac{\boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\,\boldsymbol{\iota}}
{\boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\boldsymbol{\phi}_i},
\qquad
M_i^{\text{ef}} = \frac{\left(\boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\,\boldsymbol{\iota}\right)^2}
{\boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\boldsymbol{\phi}_i}
= \Gamma_i^2\,M_i^{*} \ \ [\text{kg}]$$

$$M_{\text{tot}} = \boldsymbol{\iota}^{\mathsf T}\mathbf{M}\,\boldsymbol{\iota},
\qquad \sum_{i=1}^{N} M_i^{\text{ef}} = M_{\text{tot}} \quad (N = n_{\text{gdl libres}})$$

La suma es exacta hasta el error de redondeo: es el invariante que valida toda la
extracción. Con menos de N modos, la masa acumulada
$\sum_{i\le k} M_i^{\text{ef}} / M_{\text{tot}}$ debe superar el umbral exigido por
el procedimiento de análisis aplicable.

> ⚠️ VERIFICAR: el umbral numérico de masa modal acumulada (habitualmente 90 %) es
> un requisito **normativo por jurisdicción** y no se escribe aquí sin cita. El
> programa lo lee de `data/modal/participation_thresholds.json` con campos
> `source` (norma, edición, artículo) y `value`; sin esa entrada, la plataforma
> informa la masa acumulada y se abstiene de declarar cumplimiento.

### 5. Amortiguamiento de Rayleigh

$$\mathbf{C} = \alpha\,\mathbf{M} + \beta\,\mathbf{K}
\;\Longrightarrow\;
\zeta_i = \frac{\alpha}{2\omega_i} + \frac{\beta\,\omega_i}{2}$$

Fijando ζ en dos modos (ω₁ < ω₂), con ζ₁ = ζ₂ = ζ:

$$\alpha = \frac{2\zeta\,\omega_1\omega_2}{\omega_1+\omega_2},
\qquad
\beta = \frac{2\zeta}{\omega_1+\omega_2}$$

La rama en 1/ω amortigua los modos bajos; la rama en ω, los altos. ζ(ω) es convexa
con mínimo en $\omega_{\min} = \sqrt{\alpha/\beta}$ y crece sin límite para
ω → ∞: **β sobre la rigidez tangente sobreamortigua los modos altos** y puede
hacer ζ > 1. Variantes y su efecto en OpenSeesPy:

| Coeficiente | Matriz | Efecto | Cuándo usarlo |
|---|---|---|---|
| α (`rayleigh` slot 1) | **M** | amortigua modos bajos | siempre que se declare |
| β (`rayleigh` slot 2) | **K** tangente | ζ crece con ω | solo si los modos que participan son pocos |
| β_init (slot 3) | **K** inicial | ζ estable, no cambia con la no linealidad | análisis no lineal en el tiempo |
| β_comm (slot 4) | **K** comprometida | variante de la anterior | casos con rigidez por etapas |

Los cuatro coeficientes se emiten en **una sola** llamada `rayleigh`; una segunda
llamada reemplaza la primera silenciosamente.

### 6. Integración en el tiempo

Ecuación de movimiento con excitación uniforme en la base (dirección ι):

$$\mathbf{M}\ddot{\mathbf{u}} + \mathbf{C}\dot{\mathbf{u}} + \mathbf{K}\mathbf{u}
= -\,\mathbf{M}\,\boldsymbol{\iota}\,\ddot{u}_g(t)$$

**Newmark-β.** Parámetros γ y β; aceleración media (γ = 1/2, β = 1/4, incondicional
estable, sin disipación numérica) y lineal (γ = 1/2, β = 1/6, estable si
Δt ≤ 0.551·T_min, con período numérico acortado). Con Δt y los valores en el paso n:

$$\mathbf{K}_{\text{ef}} = \mathbf{K} + \frac{\gamma}{\beta\,\Delta t}\mathbf{C}
+ \frac{1}{\beta\,\Delta t^2}\mathbf{M}$$

$$\mathbf{K}_{\text{ef}}\,\mathbf{u}_{n+1} = \mathbf{p}_{n+1}
+ \mathbf{M}\!\left(\frac{\mathbf{u}_n}{\beta\Delta t^2}
+ \frac{\dot{\mathbf{u}}_n}{\beta\Delta t}
+ \left(\frac{1}{2\beta}-1\right)\ddot{\mathbf{u}}_n\right)
+ \mathbf{C}\!\left(\frac{\gamma\,\mathbf{u}_n}{\beta\Delta t}
+ \left(\frac{\gamma}{\beta}-1\right)\dot{\mathbf{u}}_n
+ \Delta t\left(\frac{\gamma}{2\beta}-1\right)\ddot{\mathbf{u}}_n\right)$$

$$\ddot{\mathbf{u}}_{n+1} = \frac{\mathbf{u}_{n+1}-\mathbf{u}_n}{\beta\Delta t^2}
- \frac{\dot{\mathbf{u}}_n}{\beta\Delta t} - \left(\frac{1}{2\beta}-1\right)\ddot{\mathbf{u}}_n,
\qquad
\dot{\mathbf{u}}_{n+1} = \dot{\mathbf{u}}_n + \Delta t\left[(1-\gamma)\ddot{\mathbf{u}}_n + \gamma\,\ddot{\mathbf{u}}_{n+1}\right]$$

**HHT-α.** Promedia las fuerzas en n+1 y n e introduce disipación de alta
frecuencia:

$$\mathbf{M}\ddot{\mathbf{u}}_{n+1} + (1+\alpha_h)\mathbf{C}\dot{\mathbf{u}}_{n+1}
- \alpha_h\mathbf{C}\dot{\mathbf{u}}_n
+ (1+\alpha_h)\mathbf{K}\mathbf{u}_{n+1} - \alpha_h\mathbf{K}\mathbf{u}_n
= \mathbf{p}_{n+1}$$

con $\alpha_h \in [-1/3, 0]$; $\alpha_h = 0$ devuelve Newmark de aceleración media
(segundo orden, sin disipación); valores más negativos disipan más energía en los
modos altos a costa de degradar a primer orden. El término en α_h exige guardar
**K uₙ** y **C vₙ** del paso anterior: es un estado adicional, no un parámetro.

**Diferencia central explícita.** Sin invertir **K**; requiere **M** diagonal y
**C** tal que C v se evalúe explícitamente:

$$\mathbf{u}_{n+1} = 2\mathbf{u}_n - \mathbf{u}_{n-1} + \Delta t^2\,\mathbf{M}^{-1}
\left(\mathbf{p}_n - \mathbf{C}\dot{\mathbf{u}}_n - \mathbf{K}\mathbf{u}_n\right),
\qquad
\dot{\mathbf{u}}_n = \frac{\mathbf{u}_{n+1}-\mathbf{u}_{n-1}}{2\Delta t}$$

Arranque: $\mathbf{u}_{-1} = \mathbf{u}_0 - \Delta t\,\dot{\mathbf{u}}_0 +
\tfrac{\Delta t^2}{2}\ddot{\mathbf{u}}_0$. El paso crítico sin amortiguamiento es

$$\Delta t_{\text{cr}} = \frac{T_{\min}}{\pi}, \qquad T_{\min} = \frac{2\pi}{\omega_{\max}}$$

y el amortiguamiento viscoso **reduce** Δt_cr. En la práctica se usa
Δt = (0.1 … 0.5)·Δt_cr y se comprueba contra el modo más alto retenido.

### 7. Tratamiento del registro sísmico

1. **Importación**: leer Δt y el número de puntos; unidades declaradas en el
   archivo. Un Δt no uniforme por redondeo ASCII rompe el parser: la plataforma
   compara con tolerancia relativa `DT_UNIFORMITY_RTOL = 1e-3` y adopta el Δt
   redondeado, no el promedio de diferencias.
2. **Corrección de línea base**: restar la media y luego un ajuste polinómico de
   grado bajo (típicamente 1) a la aceleración, o integrar y corregir en
   velocidad/desplazamiento. El desplazamiento residual final del registro
   integrado dos veces es el indicador: si no converge a cero, la corrección es
   insuficiente.
3. **Interpolación**: remuestreo a un Δt único por interpolación lineal o
   *spline* cúbica, según lo requiera el integrador; si Δt_registro > Δt_análisis,
   la interpolación lineal **no añade contenido de alta frecuencia** y no excita
   modos que el registro no contenía.
4. **Escalado a un espectro objetivo**: factor único por registro o por par, o
   factores por período para ajuste de forma. El factor de PGA es

$$f_{\text{PGA}} = \frac{a_{\text{PGA}}^{\text{objetivo}}}{a_{\text{PGA}}^{\text{registro}}}$$

y el de un período T₁ se obtiene de la razón de ordenadas espectrales,
$f_{T_1} = S_a^{\text{obj}}(T_1)/S_a^{\text{reg}}(T_1)$, con $S_a$ calculado con el
mismo ζ del análisis. El espectro de la respuesta del registro escalado se
recalcula y se grafica contra el objetivo: la verificación es visual y numérica.

> ⚠️ VERIFICAR: los parámetros del filtro paso-alto de la corrección de línea base
> (frecuencia de corte, número de pasadas, tratamiento de los extremos) y el
> procedimiento de escalado aceptado dependen de la norma de aplicación y del
> formato del registro (PEER NGA). No se fijan aquí. Se comprueban en la
> documentación del proveedor del registro y en la norma de la jurisdicción, y el
> programa debe leerlos de `data/ground-motion/processing.json` con `source` y
> `verified_on`.

## Procedimiento

1. Verificar la matriz de masa: ninguna fila nula; si hay DOF sin masa, condensarlos
   estáticamente y registrar cuáles.
2. Contar DOF libres (`core.modal.free_dof_count`) y resolver el solver con
   `resolve_modal_solver`; nunca elegirlo a mano.
3. Extraer los modos; si el solver fue ARPACK, re-ejecutar el caso en un proceso
   nuevo antes de una segunda extracción.
4. Agrupar autovalores degenerados (`degenerate_groups`) y ortogonalizar cada grupo
   respecto de la masa (`orthogonalize_degenerate_modes`).
5. Normalizar signos (`normalize_mode_sign`) y **guardar** los modos ya tratados.
6. Calcular Γᵢ y Mᵢ^ef por dirección; verificar ΣMᵢ^ef = M_tot y la masa acumulada
   contra el umbral leído del archivo de datos.
7. Si la masa acumulada no alcanza: aumentar `n_modes` y repetir desde 3; nunca
   relajar el umbral sin declararlo.
8. Para el caso transitorio: fijar α y β a partir de los dos modos retenidos;
   comprobar ζ(ω) en todos los modos con masa apreciable y avisar si ζ ≥ 1.
9. Elegir integrador y Δt: Newmark de aceleración media por defecto; HHT-α solo con
   α_h declarado; diferencia central solo con masa diagonal y Δt ≤ 0.5·T_min/π.
10. Procesar el registro (línea base, interpolación, escalado) y **recalcular** su
    espectro de respuesta para comprobar el escalado.
11. Correr, guardar series y trazabilidad (solver, umbrales, α, β, Δt, factores).

## Implementación en la plataforma

```python
# opensees_studio/core/modal.py        (core puro: sin Qt, sin openseespy)
def free_dof_count(project: Project) -> int: ...
def resolve_modal_solver(requested: str, n_free: int, n_modes: int) -> tuple[str, str]: ...
def degenerate_groups(eigenvalues, *, rel_tol: float = 1e-6) -> list[list[int]]: ...
def orthogonalize_degenerate_modes(eigenvalues, mode_shapes, node_mass, *, rel_tol=1e-6): ...
def normalize_mode_sign(shape: dict[int, np.ndarray], *, rel_tol: float = 1e-9): ...

# opensees_studio/core/modal_participation.py   (nuevo)
def participation_factors(mode_shapes, node_mass, influence: np.ndarray) -> np.ndarray: ...
def effective_modal_mass(mode_shapes, node_mass, influence) -> np.ndarray: ...
def cumulative_mass_ratio(meff: np.ndarray, total_mass: float) -> np.ndarray: ...
def modes_for_mass_ratio(meff: np.ndarray, total_mass: float, target: float) -> int: ...

# opensees_studio/core/damping.py   (nuevo)
def rayleigh_from_two_modes(w1: float, w2: float, zeta: float) -> tuple[float, float]: ...
def modal_damping_ratios(alpha: float, beta: float, omegas: np.ndarray) -> np.ndarray: ...

# opensees_studio/core/ground_motion.py  (existente, ampliar)
def read_record(path) -> tuple[float, np.ndarray, dict]: ...
def correct_baseline(dt: float, accel: np.ndarray, *, degree: int, data: dict): ...
def resample(dt_in: float, accel: np.ndarray, dt_out: float) -> np.ndarray: ...
def scale_to_target(accel, dt, target: TargetSpectrum, zeta: float, data: dict): ...
```

Reglas de arquitectura:

- Todo lo anterior vive en `core/`: sin Qt y sin OpenSeesPy. La participación
  modal y el cálculo de α/β son funciones puras sobre arreglos de NumPy.
- `services/` es el único que habla con el solver: emite `eigen`, `rayleigh`,
  `integrator`, `UniformExcitation` y `PathTimeSeries`, y devuelve los resultados
  ya tratados (`ModalResults`, `TransientResults`).
- El núcleo no decide el solver ni conoce nombres de OpenSees: recibe la familia
  resuelta como cadena y la registra en los resultados.
- Los umbrales de masa modal y los parámetros de procesamiento de registros vienen
  de archivos de datos versionados, con `source` y `verified_on`.
- `rayleigh` se emite **una sola vez** por caso, con los cuatro coeficientes.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| ζ de Rayleigh: ζᵢ = α/(2ωᵢ) + βωᵢ/2; α y β de dos modos | Chopra, *Dynamics of Structures*, 5.ª ed., §11.4 | sí (álgebra estándar) |
| Newmark de aceleración media γ = 1/2, β = 1/4; lineal β = 1/6 | Chopra, 5.ª ed., §5.3 y Tabla 5.4.1 | sí |
| HHT-α con α_h ∈ [−1/3, 0] y su orden | Hilber, Hughes & Taylor (1977) | sí |
| Δt_cr = T/π para diferencia central sin amortiguamiento | Chopra, 5.ª ed., §5.6 | sí |
| Σ Mᵢ^ef = M_tot para el conjunto completo de modos | ortogonalidad respecto de la masa | sí (identidad algebraica) |
| Umbral de masa modal acumulada por jurisdicción | norma aplicable, artículo por confirmar | no — `VERIFICAR` |
| Parámetros de corrección de línea base y escalado | norma aplicable / PEER NGA | no — `VERIFICAR` |
| Convención exacta de `eigen` en OpenSeesPy 3.8.0.0 | documentación del solver instalado | no — `VERIFICAR` |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Períodos, sistema de 2 masas | m₁ = m₂ = 1000 kg, k₁ = k₂ = 1000 N/m, 2 DOF libres | T₁ = 10.1664 s, T₂ = 3.88322 s | 0.5 % relativo |
| Factores de participación | ídem, ι = [1, 1]ᵗ | Γ₁ = −1.37638, Γ₂ = −0.324920 | 1e-4 absoluto |
| Masa efectiva acumulada | ídem | M₁^ef = 1894.427 kg (94.7214 %), M₂^ef = 105.573 kg; Σ = 2000.000 kg | 1e-6 relativo; cierre con M_tot a 1e-9 relativo |
| Número de modos para el umbral | ídem, umbral leído = 0.90 | 1 modo basta (94.72 %) | — |
| α y β de Rayleigh | ω₁ = 0.618034, ω₂ = 1.618034 rad/s, ζ = 0.05 | α = β = 0.0447214 s⁻¹ y s | 1e-9 |
| ζ modal resultante | α = β = 0.0447214, ω = ω₁, ω₂ | ζ₁ = ζ₂ = 0.0500000 | 1e-9 |
| Newmark media, amortiguado | SDOF m = 1 kg, k = 100 N/m, ζ = 0.05, u₀ = 1 m, Δt = 0.01 s | u(1.0 s) = 0.606531 m (envolvente e^(−ζωt)); sin oscilación espuria | 0.5 % relativo |
| Diferencia central no amortiguada | SDOF m = 1 kg, k = 100 N/m, u₀ = 1 m, Δt = 0.05 s (T = 0.6283 s) | amplitud conservada, sin crecimiento | 1e-3 relativo |
| Diferencia central en el paso crítico | ídem, Δt = 0.21 s > T/π = 0.2 s | divergencia (|u| > 1e6) | cualitativo |
| Aproximación de la raíz más alta | SDOF no amortiguado, Newmark media, Δt/T = 0.1 | T_num > T_exacto en < 1 % | 1 % relativo |
| Signo determinista | par degenerado con empate a 1e-9 | componente de mayor |·| positiva; empate al DOF de índice menor | exacto |
| Reproducibilidad | dos corridas del mismo caso en procesos distintos | períodos idénticos y signos idénticos | 1e-12 relativo |
| Escalado de PGA | registro con PGA = 0.10 g, objetivo 0.40 g | factor = 4.00000 | 1e-9 |
| Δt no uniforme | archivo con Δt nominal 0.02 s y dispersión 5e-4 s | aceptado, Δt = 0.02 s | `DT_UNIFORMITY_RTOL` |

## Errores frecuentes y trampas

1. **Invertir la convención de `eigen`.** `ops.eigen(n)` decide la familia de
   solver; pasar `'genBandArpack'` o `'fullGenLapack'` cambia el determinismo. El
   solver no se elige a mano: se resuelve con `resolve_modal_solver`.
2. **Dos llamadas ARPACK en un proceso.** El vector de arranque persistente
   invierte signos y rota pares repetidos; la corrida por CLI y la directa dejan de
   coincidir. Se re-ejecuta en un hijo nuevo.
3. **Confundir `lambda` con ω.** `ModalResults.eigenvalues` viene en rad²/s²
   (convención OpenSees); `T = 2π/√λ`, no `2π/λ`.
4. **Masa modal efectiva con la matriz de masa equivocada.** Si el modelo usa masa
   concentrada y el cálculo de participación usa masas nodales inconsistentes con
   lo que ensambló el solver, ΣMᵢ^ef ≠ M_tot. El cierre contra M_tot es la prueba.
5. **Ortogonalizar mal los modos degenerados.** Diagonalizar la matriz de masa
   modal (inversa) en vez de la forma simétrica produce pérdida de rango: se
   perturba el bloque con un jitter y se comprueba que el subespacio se conserva.
6. **β sobre rigidez tangente en modelos no lineales.** El ζ efectivo de los modos
   altos cambia con la deformación y la respuesta pierde sentido físico; hay que
   usar β inicial (slot 3) o β comprometida (slot 4).
7. **Emitir `rayleigh` dos veces.** La segunda llamada reemplaza la primera sin
   aviso; el amortiguamiento queda en cero para α.
8. **Dividir por ω sin proteger el cero.** Un modo de cuerpo rígido
   (λ → 0) produce α/(2ω) infinito; el modo se excluye del cálculo de ζ y se avisa.
9. **Elegir Δt solo por el registro.** El Δt lo manda el modo más alto retenido y el
   esquema: para diferencia central, Δt ≤ 0.5·T_min/π; para Newmark lineal, solo
   estable si Δt ≤ 0.551·T_min.
10. **Tratar la interpolación como inocua.** Interpolar con *spline* cúbica un
    registro de Δt grande introduce contenido de alta frecuencia y excita modos que
    el registro no tenía; la interpolación lineal no lo hace.
11. **Redondear el Δt del registro.** Un Δt con seis decimales truncado a dos
    cambia la duración efectiva y desajusta el escalado espectral; se conserva el
    valor declarado con tolerancia `1e-3`.
12. **Escalar por PGA y creer que se cumplió el espectro.** El factor de PGA no
    controla la ordenada en T₁; hay que recomputar el espectro del registro escalado.

## Interfaz de salida

Para cada dirección de análisis, la plataforma reporta:

- `modal`: períodos (s), frecuencias (Hz) y ω (rad/s); solver usado, razón de la
  elección y `n_free_dof`; Δt de análisis y número de modos.
- Tabla de participación: Γᵢ (adimensional), Mᵢ^ef (kg), % de masa por modo y
  acumulado; la fila que cruza el umbral, con el umbral y su `source`.
- Formas modales normalizadas, con el signo ya fijado y la marca de los grupos
  degenerados ortogonalizados.
- Amortiguamiento: α (s⁻¹), β (s), modos o frecuencias usados, ζᵢ resultante por
  modo y aviso si algún ζᵢ ≥ 1.
- Transitorio: esquema (Newmark media/lineal, HHT-α con α_h, diferencia central),
  Δt, Δt_cr y su relación, número de pasos, y la verificación de equilibrio en el
  primer paso.
- Registro: unidad de origen, Δt, número de puntos, corrección aplicada con sus
  parámetros, y el factor de escalado con la tabla de comparación
  $S_a^{\text{reg}}(T)$ frente a $S_a^{\text{obj}}(T)$.
- Series temporales en HDF5 float64 con `manifest.json`; nunca en memoria de la GUI.
- Advertencias activas: umbral no alcanzado, ζ ≥ 1, Δt por encima del crítico,
  corrección de línea base sin verificación.

## Referencias

1. A. K. Chopra, *Dynamics of Structures: Theory and Applications to Earthquake
   Engineering*, 5.ª ed., Pearson, 2017 — caps. 5 (integración), 10–11 (modos,
   participación, amortiguamiento), 12–13 (sismo).
2. K.-J. Bathe, *Finite Element Procedures*, 2.ª ed., 2014 — §9.2 (Newmark),
   §9.4.1 (diferencia central), autovalores.
3. H. M. Hilber, T. J. R. Hughes y R. L. Taylor, "Improved numerical dissipation
   for time integration algorithms in structural dynamics", *Earthquake
   Engineering and Structural Dynamics*, 5(3), 1977.
4. R. W. Clough y J. Penzien, *Dynamics of Structures*, 3.ª ed., 2003 — cap. 12.
5. OpenSeesPy 3.8.0.0, documentación de `eigen`, `rayleigh`, `integrator`,
   `UniformExcitation`, `PathTimeSeries` (versión instalada en la plataforma).
6. PEER NGA, *Ground Motion Database* — formato `.at2` y recomendaciones de
   procesamiento del registro.

## Registro de verificación

- **Verificado**: la forma autoacoplada del problema de autovalores y la
  normalización de masa; las expresiones de Γᵢ y Mᵢ^ef y el cierre ΣMᵢ^ef = M_tot;
  ζᵢ = α/(2ωᵢ) + βωᵢ/2 y los α, β de dos modos; los parámetros de Newmark de
  aceleración media y lineal; HHT-α con α_h ∈ [−1/3, 0]; Δt_cr = T/π; los valores
  numéricos de los casos de prueba (recalculados con NumPy el 2026-02-14); el
  umbral denso/ARPACK y la condición `2·n_modes < n_free` tal como están en
  `core/modal.py`.
- **Pendiente**: umbral de masa modal acumulada por jurisdicción (requiere la norma
  de aplicación); parámetros del filtro de línea base y del escalado (requiere la
  norma y la documentación PEER NGA); convención exacta de `eigen` en la versión
  instalada de OpenSeesPy (prueba de integración contra el solver).
- **Responsable de cerrar**: responsable de dinámica estructural del proyecto, con
  la norma de la jurisdicción y una corrida de referencia de OpenSeesPy.
