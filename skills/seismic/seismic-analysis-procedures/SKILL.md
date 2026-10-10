---
name: seismic-analysis-procedures
description: >-
  Especifica y verifica los procedimientos de análisis sísmico: fuerza lateral
  equivalente (cortante basal y distribución con el exponente k), modal espectral
  (SRSS, CQC, masa modal acumulada, escalado del cortante basal modal al
  estático), torsión accidental y amplificación A_x, combinación direccional
  100/30 y SRSS, efectos P-Delta, derivas con factor de deflexión e importancia,
  historia de respuesta no lineal (selección, escalado y reducción de registros)
  y pushover con punto de desempeño. Úsala al elegir el procedimiento permitido,
  al escalar el cortante basal modal, al aplicar torsión accidental, al combinar
  direcciones, al evaluar θ o la deriva de entrepiso, y al seleccionar registros.
metadata:
  track: seismic
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, analysis, qa]
---

# Procedimientos de análisis sísmico

## Cuándo usar esta skill

- Hay que decidir **qué procedimiento de análisis** permite la norma para la estructura dada y documentar por qué se excluyen los demás.
- Se implementa o audita el cortante basal estático \(V\), su distribución en altura con el exponente \(k\), o los límites de uso del método.
- El cortante basal modal \(V_t\) es menor que el estático y hay que decidir el **escalado** y a qué magnitudes se aplica.
- Hay que aplicar **torsión accidental** (\(\pm 5\,\%\) de la dimensión perpendicular), la amplificación \(A_x\), o la **combinación direccional** 100/30.
- Se evalúa el **coeficiente de estabilidad** \(\theta\), la amplificación \(1/(1-\theta)\), o la **deriva de entrepiso** con \(C_d\) e \(I_e\).
- Se prepara un caso de **historia de respuesta no lineal** (selección, escalado y regla de reducción) o de **pushover** con punto de desempeño.

**No usar** para el espectro de diseño ni los coeficientes de sistema estructural (→ `codes/asce7-22-seismic-design` y las skills de código nacional), para la extracción de autovalores y formas modales (→ `core/modal-and-time-history`), ni para el diseño de elementos (→ `design/...`).

## Alcance y límites

Cubre la selección, ejecución y verificación del procedimiento: fuerza lateral equivalente, modal espectral, historia de respuesta no lineal y pushover, con sus combinaciones, amplificaciones y criterios de aceptación.
Queda fuera el espectro de peligro y los parámetros de sitio, el diseño de elementos, la interacción suelo-estructura, el análisis *multiple support* y el modelado de masas, diafragmas y elementos. Supone comportamiento lineal elástico en ELF y modal espectral, y elementos ya calibrados en pushover e historia de respuesta. Los límites de uso, umbrales y factores **no se fijan aquí**: son normativos por jurisdicción y viven en archivos de datos versionados.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Código y edición (`code_id` + edición) | sí | bloquear: sin edición no hay límites ni valores |
| Espectro de diseño \(S_a(T)\) con su `source` | sí | bloquear |
| \(R\), \(C_d\), \(\Omega_0\) del sistema estructural | sí | leer de `data/<code>/systems.json`; sin entrada, bloquear |
| \(I_e\) y categoría de riesgo | sí | bloquear |
| Pesos \(w_x\), alturas \(h_x\) y carga \(P_x\) por nivel | sí | bloquear |
| \(T_1\) por dirección (autovalores o aproximado) | sí | calcular; el aproximado se lee de la tabla del código |
| Tipo de diafragma (rígido o flexible) | sí | bloquear: define \(\delta_{\text{avg}}\) y \(A_x\) |
| \(\delta_{xe}\) y \(V_x\) por entrepiso | sí | provienen del caso resuelto |
| Registros con \(\Delta t\), PGA y unidad de origen | si hay historia | bloquear el caso no lineal |
| Curva pushover \(V_b\)–\(u_n\) y forma modal asumida | si hay pushover | bloquear |

Unidades internas SI coherentes: m, N, kg, s, Pa; \(g = 9.80665\ \text{m/s}^2\). Las aceleraciones espectrales entran **en g** cuando el código las publica en g, se declara esa unidad en el objeto de espectro y se convierte a m/s² antes de multiplicar por una masa.

## Fundamento y formulación

### 1. Selección del procedimiento y límites de uso
La elección es normativa, no de conveniencia: se fija por categoría de diseño sísmico, regularidad en planta y en altura, altura total \(h_n\) [m], período \(T_1\) [s] y tipo de diafragma. El método de fuerza lateral equivalente es el más restringido; el modal espectral lo sustituye al excederse los límites; la historia de respuesta se exige con irregularidades severas o cuando el modal no captura la respuesta.
> ⚠️ VERIFICAR: los cortes exactos de los límites de uso (procedimientos permitidos por SDC, umbrales de \(h_n\) y de irregularidad) cambian entre ediciones y no se transcriben. Se comprueban en el capítulo de análisis sísmico de la edición aplicable; el programa los lee de `data/<code>/procedures.json` (`source`, `edition`, `article`), nunca del código.
### 2. Método de fuerza lateral equivalente
Con \(W\) [N] el peso sísmico efectivo, \(w_i\) [N] y \(h_i\) [m] el peso y la altura sobre la base del nivel \(i\), \(R\) e \(I_e\) [-] y \(S_{DS}\) [g] leídos del archivo de datos (ASCE 7-22, §12.8.1 y §12.8.3): \(V = C_sW\) [N], \(C_s = S_{DS}/(R/I_e)\), \(F_x = C_{vx}V\), \(C_{vx} = w_xh_x^{k}/\sum_{i=1}^{n}w_ih_i^{k}\), \(V_x = \sum_{i=x}^{n}F_i\). El exponente \(k\) [-] vale \(k = 1\) para \(T \le 0.5\ \text{s}\), \(k = 2\) para \(T \ge 2.5\ \text{s}\), con interpolación lineal entre ambos. Los topes y el mínimo de \(C_s\) se leen del archivo de datos.
### 3. Análisis modal espectral: combinación y masa
Con \(\boldsymbol{\phi}_i\) normalizada respecto de la masa, \(\Gamma_i = \boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\boldsymbol{\iota}/(\boldsymbol{\phi}_i^{\mathsf T}\mathbf{M}\boldsymbol{\phi}_i)\) [-] el factor de participación, \(\omega_i\) [rad/s], \(\zeta_i\) [-] y \(M_{\text{tot}} = \boldsymbol{\iota}^{\mathsf T}\mathbf{M}\boldsymbol{\iota}\) [kg]; las respuestas pico modales \(R_i\) son cualesquiera (fuerza, momento, desplazamiento), y \(\mathbf{u}_i = \boldsymbol{\phi}_i\Gamma_iS_a(T_i)/\omega_i^{2}\) [m], \(V_i = M_i^{\text{ef}}S_a(T_i)\) [N] con \(M_i^{\text{ef}} = \Gamma_i^{2}M_i^{*}\) [kg]:

$$R_{\text{SRSS}} = \sqrt{\textstyle\sum_i R_i^{2}}, \qquad R_{\text{CQC}} = \sqrt{\textstyle\sum_i\sum_j \rho_{ij}R_iR_j}, \qquad \rho_{ij} = \frac{8\sqrt{\zeta_i\zeta_j}\;(\zeta_i + r\zeta_j)\;r^{3/2}}{(1-r^{2})^{2} + 4\zeta_i\zeta_j r(1+r^{2}) + 4(\zeta_i^{2}+\zeta_j^{2})r^{2}}, \quad r = \frac{\omega_j}{\omega_i} \ge 1$$

SRSS supone modos no correlacionados y **subestima** al acercarse \(\rho \to 1\): en un par degenerado con \(R_1 = R_2 = R\), SRSS da \(\sqrt{2}R = 1.414214R\) y CQC da \(2R\), un 29.3 % menos. CQC es la regla por defecto siempre que existan modos con \(\omega_j/\omega_i \le 1/0.9\). La masa modal acumulada, ordenando los modos por masa efectiva decreciente, es \(\eta = \sum_{i\in\mathcal{S}}M_i^{\text{ef}}/M_{\text{tot}} \ge \eta_{\text{norma}}\).
> ⚠️ VERIFICAR: son normativos, y difieren entre ediciones, tanto \(\eta_{\text{norma}}\) (el 90 % histórico fue elevado en ediciones recientes, con alternativas por número de modos o período de corte) como el factor \(\alpha\) del escalado del cortante basal modal, su artículo exacto y si el cortante de referencia incluye la torsión accidental. Se comprueban en el capítulo de análisis modal de la edición impresa aplicable; el programa lee `eta_norma`, `alpha` y `reference_includes_torsion` de `data/<code>/modal.json` y, sin esas entradas, informa las magnitudes y **se abstiene** de declarar cumplimiento.
### 4. Escalado del cortante basal modal
Si \(V_t < \alpha V\) (con \(V\) de la §2), **todas** las respuestas del análisis modal —fuerzas, momentos, desplazamientos y derivas— se multiplican por \(f_s = \alpha V/V_t > 1\), con \(V_t\) la combinación CQC o SRSS de los \(V_i\).
El escalado es por dirección y se aplica **después** de combinar los modos y **antes** de la torsión accidental, la combinación direccional y las combinaciones de carga. Escalar solo el cortante deja las derivas subestimadas en el mismo factor.
### 5. Torsión accidental y amplificación torsional
Momento torsional accidental por nivel, aplicado en **ambos signos** (ASCE 7-22, §12.8.4.2): \(M_{ta,x} = \pm 0.05\,B_y\,V_x\) [N·m], con \(B_y\) [m] la dimensión en planta perpendicular a la dirección de las fuerzas \(x\) y \(V_x\) [N] el cortante de entrepiso. Se corre \(+\) y \(-\) y se envuelve.
Amplificación torsional donde la norma la exige (ASCE 7-22, §12.8.4.3): \(1 \le A_x = (\delta_{\max}/(1.2\,\delta_{\text{avg}}))^{2} \le A_{x,\max}\), con \(\delta_{\max}\) y \(\delta_{\text{avg}}\) [m] el desplazamiento máximo del nivel y el promedio de los puntos que la norma define en el nivel (extremos del diafragma, no solo los nodos del modelo). \(A_x\) multiplica los **esfuerzos internos**, no los desplazamientos de la deriva.
> ⚠️ VERIFICAR: el tope \(A_{x,\max}\) (históricamente 3.0, con excepciones por irregularidad torsional en ediciones recientes) y las categorías que lo requieren. Se comprueban en la edición aplicable; el programa lee `ax_max` y `ax_required_for` de `data/<code>/torsion.json`.
### 6. Combinación direccional
Con \(E_x\), \(E_y\) los efectos sísmicos de las dos direcciones ortogonales (ASCE 7-22, §12.5.4): \(E_h = 1.00E_x + 0.30E_y\), \(E_h = 0.30E_x + 1.00E_y\), o bien \(E_h = \sqrt{E_x^{2}+E_y^{2}}\). La regla SRSS solo vale con diafragma rígido y formas modales equivalentes en ambas direcciones; cuando la norma exige 100/30, la envolvente de las dos permutaciones es obligatoria y una sola no basta.
### 7. Efectos P-Delta y coeficiente de estabilidad
Con \(P_x\) [N] la carga vertical sin mayorar sobre el nivel \(x\), \(\Delta\) [m] la **deriva de diseño** del entrepiso, \(V_x\) [N] el cortante sísmico, \(h_{sx}\) [m] la altura libre y \(C_d\), \(I_e\), \(\beta\) [-] (ASCE 7-22, §12.8.7):

$$\theta = \frac{P_x\,\Delta\,I_e}{V_x\,h_{sx}\,C_d} = \frac{P_x\,\delta_{xe}}{V_x\,h_{sx}}, \qquad \Delta = \frac{C_d\,\delta_{xe}}{I_e}, \qquad \theta \le \frac{0.5}{\beta C_d} \le 0.25$$

La segunda igualdad es la trampa clásica: \(I_e\) y \(C_d\) se cancelan porque \(\Delta\) ya viene amplificada. \(\beta\) vale 1.0 salvo indicación contraria de la norma. Si \(\theta \le 0.10\) no se amplifica; si \(0.10 < \theta \le \theta_{\max}\), **desplazamientos y fuerzas internas** se multiplican por \(1/(1-\theta)\); si se excede \(\theta_{\max}\) el análisis es inadmisible y hay que rigidizar.
### 8. Derivas
\(\delta_x = C_d\delta_{xe}/I_e\) [m]; \(\Delta_x = \delta_x^{\text{topo}}-\delta_x^{\text{fondo}}\) [m]; deriva de entrepiso \(= \Delta_x/h_{sx}\) [-]. Se compara con el límite normativo **después** de aplicar torsión accidental, \(A_x\) y la amplificación \(1/(1-\theta)\), y con la combinación de carga sísmica que la norma exige, no con la envolvente de todas las combinaciones.
> ⚠️ VERIFICAR: la tabla de límites de deriva por categoría de riesgo y el tratamiento de estructuras de baja altura. Se comprueba en la edición aplicable; el programa lee `drift_limits` de `data/<code>/drift.json` con prueba unitaria contra la tabla publicada.
### 9. Análisis no lineal de historia de respuesta
Con al menos \(N_{\min}\) registros (por pares en análisis bimensional) se calcula el espectro de cada registro con el mismo \(\zeta\) del análisis y se busca un factor **común** al conjunto tal que, en el rango \([0.2T_1,\ 1.5T_1]\):

$$\min_{T}\ \frac{\overline{S_a^{\text{SRSS}}(T)}}{S_a^{\text{objetivo}}(T)} \ge 1, \qquad \overline{S_a^{\text{SRSS}}(T)} = \frac{1}{N}\sum_{k=1}^{N}\sqrt{S_{a,k,x}^{2}(T) + S_{a,k,y}^{2}(T)}$$

Reducción de la respuesta: \(\mathbf{E} = \max_k|\mathbf{E}_k|\) **componente a componente** si \(N < 7\), y \(\mathbf{E} = \frac{1}{N}\sum_k\mathbf{E}_k\) si \(N \ge 7\). Nunca se promedian valores absolutos ni la norma del vector.
> ⚠️ VERIFICAR: \(N_{\min}\), el umbral de 7 registros, el rango de períodos, la cota superior del factor de escala y si el espectro objetivo es el de diseño o el MCEr. Se comprueban en el capítulo de historia de respuesta aplicable; el programa lee `record_rules` de `data/<code>/records.json`.
### 10. Pushover y punto de desempeño
Con la forma \(\boldsymbol{\phi}\) normalizada a 1 en el nivel de control: \(\Gamma = \boldsymbol{\phi}^{\mathsf T}\mathbf{M}\boldsymbol{\iota}/(\boldsymbol{\phi}^{\mathsf T}\mathbf{M}\boldsymbol{\phi})\) [-], \(m^{*} = \boldsymbol{\phi}^{\mathsf T}\mathbf{M}\boldsymbol{\iota}\) [kg], \(d^{*} = u_n/\Gamma\) [m], \(F^{*} = V_b/\Gamma\) [N], \(S_a = F^{*}/m^{*}\) [m/s²], \(S_d = S_aT^{*2}/(4\pi^{2})\) [m], \(T^{*} = 2\pi\sqrt{m^{*}d^{*}/F^{*}}\) [s]. El punto de desempeño es la intersección iterada entre la curva de capacidad en formato \(S_a\)–\(S_d\) y el espectro de demanda reducido por amortiguamiento equivalente, con \(\zeta_{\text{eq}} = E_D/(4\pi E_S)\), \(E_D = \oint F\,\mathrm{d}u\) [J] la energía disipada por ciclo y \(E_S = \frac{1}{2}F_{\max}u_{\max}\) [J] la energía elástica. Convergencia: \(|S_d^{(k)}-S_d^{(k-1)}| \le 10^{-4}S_d^{(k)}\) con tope explícito de iteraciones.
> ⚠️ VERIFICAR: la relación cerrada \(\zeta_{\text{eq}}(\mu)\) y el factor de reducción por amortiguamiento dependen del procedimiento (N2, ATC-40, FEMA 440) y de su edición; no se transcriben. Se comprueban en el documento del procedimiento y el programa los lee de `data/seismic/performance_point.json` con `source` y `verified_on`.

## Procedimiento

1. Resolver código, edición, \(R\), \(C_d\), \(\Omega_0\) e \(I_e\) del archivo de datos; sin edición, detener.
2. Evaluar regularidad y altura y llamar a `allowed_procedures`; registrar los procedimientos permitidos y el motivo de exclusión de los demás.
3. Calcular \(T_1\) por dirección y, si el método lo exige, el período aproximado de la tabla del código con su tope normativo.
4. **ELF**: calcular \(C_s\), \(V\), \(k\), \(C_{vx}\), \(F_x\) y \(V_x\), y verificar \(\sum F_x = V\).
5. **Modal**: extraer modos (→ `core/modal-and-time-history`), combinar por la regla que exige la norma y verificar \(\eta\); si no alcanza, aumentar modos y repetir.
6. Escalar el cortante basal modal con \(f_s\) y propagar el factor a todas las respuestas; registrar \(V\), \(V_t\) y \(f_s\).
7. Aplicar \(M_{ta}\) en \(+\) y \(-\) por nivel, correr ambos signos y envolver; calcular \(A_x\) y amplificar esfuerzos internos donde proceda.
8. Combinar direcciones (100/30 o SRSS) y obtener la envolvente por dirección.
9. Recalcular derivas con \(C_d/I_e\), evaluar \(\theta\) y amplificar por \(1/(1-\theta)\) donde \(0.10 < \theta \le \theta_{\max}\).
10. Verificar \(\theta_{\max}\) y la deriva contra los límites del archivo de datos; emitir veredicto por entrepiso y dirección.
11. **Historia**: seleccionar registros, escalar el conjunto con factor común, correr y reducir por la regla de \(N\).
12. **Pushover**: correr con al menos dos patrones (modal y uniforme), convertir a \(S_a\)–\(S_d\) e iterar el punto de desempeño.
13. Persistir cada paso con su entrada, su salida, la combinación que lo produjo, la edición normativa y el archivo de datos usado.

### Criterios de aceptación y trazabilidad

| Paso | Salida | Criterio | Fuente |
|---|---|---|---|
| Selección | procedimientos permitidos | cumple los límites del elegido | `data/<code>/procedures.json` |
| ELF | \(V\), \(F_x\), \(V_x\) | \(\sum F_x = V\) a 1e-9 relativo | §12.8.3 |
| Modal | \(\eta\) acumulada | \(\eta \ge \eta_{\text{norma}}\) | `data/<code>/modal.json` |
| Escalado | \(f_s\) | \(f_s \ge 1\) aplicado a todas las respuestas | `data/<code>/modal.json` |
| Torsión | envolvente de \(+\) y \(-\) | ambos signos corridos y registrados | §12.8.4.2 |
| \(A_x\) | esfuerzos amplificados | \(1 \le A_x \le A_{x,\max}\) | `data/<code>/torsion.json` |
| Direccional | envolvente | ambas permutaciones 100/30 | §12.5.4 |
| P-Δ | \(\theta\), \(1/(1-\theta)\) | \(\theta \le 0.5/(\beta C_d) \le 0.25\) | §12.8.7 |
| Derivas | \(\Delta_x/h_{sx}\) | \(\le\) límite de la tabla | `data/<code>/drift.json` |
| Historia | \(\mathbf{E}\) reducida | \(N \ge N_{\min}\) y regla de reducción correcta | `data/<code>/records.json` |
| Pushover | \((S_d^{*}, S_a^{*})\) | convergencia declarada y dos patrones | procedimiento adoptado |

## Implementación en la plataforma

```python
# core/seismic/  — núcleo puro: sin Qt, sin OpenSeesPy, sin solver
def allowed_procedures(facts: SeismicFacts, data: CodeData) -> list[ProcedureVerdict]: ...
def elf_base_shear(sds: float, r: float, i_e: float, w: float, data: CodeData) -> float: ...
def vertical_exponent(t1: float, data: CodeData) -> float: ...
def vertical_distribution(w: np.ndarray, h: np.ndarray, k: float) -> np.ndarray: ...
def modal_base_shear(modal: ModalResults, spectrum: Spectrum, direction: int) -> float: ...
def scale_modal_base_shear(v_modal: float, v_static: float, data: CodeData) -> float: ...
def accidental_torsion(v_x: float, b_perp: float, data: CodeData) -> float: ...
def torsional_amplification(d_max: float, d_avg: float, data: CodeData) -> float: ...
def directional_combine(ex: np.ndarray, ey: np.ndarray, rule: str) -> np.ndarray: ...
def design_drift(delta_xe: float, cd: float, i_e: float) -> float: ...
def stability_coefficient(p_x: float, delta_xe: float, v_x: float, h_sx: float) -> float: ...
def pdelta_amplification(theta: float, data: CodeData) -> float: ...
def scale_record_set(records, target: Spectrum, t1: float, data: CodeData) -> ScalingResult: ...
def reduce_responses(responses: np.ndarray, data: CodeData) -> np.ndarray: ...
def equivalent_sdof(shape, node_mass, influence) -> Sdof: ...
def capacity_spectrum(curve: PushoverCurve, sdof: Sdof) -> AdrsCurve: ...
def performance_point(capacity: AdrsCurve, demand: DemandCurve, data: PerformanceData) -> PerformancePoint: ...

# services/  — único lugar donde se habla con el solver
def run_modal_spectrum(case, project) -> ModalSpectrumResults:   # ops.eigen + combinación modal
def run_pushover(case, project) -> PushoverResults:              # ops.integrator("DisplacementControl")
def run_time_history(case, project) -> TransientResults:         # Path + UniformExcitation
def load_records(paths, data) -> list[Record]:                   # services/peer_record.py
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):

- Todo el cálculo de esta skill vive en `core/seismic/` y es **puro**: no importa Qt ni OpenSeesPy y opera sobre NumPy y modelos de `core/`.
- El solver se usa **solo** desde `services/`; un módulo de `core/` que necesite un autovalor lo recibe ya extraído en un objeto de resultados.
- La correlación de CQC ya implementada en `core/modal_combination.py` se reutiliza; no se duplica.
- Umbrales y factores normativos se cargan de `data/<code>/*.json` y `data/seismic/*.json`; ninguna tabla se escribe en la lógica.
- Un caso con autovalores se declara en `run.py` (`_uses_eigen`, `_routed_to_arpack`) para respetar el determinismo del solver.
- Envolventes, derivas, \(\theta\) y punto de desempeño se guardan en el almacén HDF5 float64 de `services/result_store.py`, junto a la instantánea que los produjo.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(V = C_sW\) | ASCE 7-22, §12.8.1 | sí (forma de la expresión) |
| \(F_x = C_{vx}V\), \(C_{vx} = w_xh_x^k/\sum w_ih_i^k\) | ASCE 7-22, §12.8.3 | sí |
| \(k = 1\) si \(T \le 0.5\ \text{s}\); \(k = 2\) si \(T \ge 2.5\ \text{s}\); lineal entre ambos | ASCE 7-22, §12.8.3 | sí |
| \(\rho_{ij}\) de Der Kiureghian | Der Kiureghian (1981); `core/modal_combination.py` | sí (usada por el programa) |
| Torsión accidental \(\pm 0.05\,B\,V_x\) | ASCE 7-22, §12.8.4.2 | sí |
| \(A_x = (\delta_{\max}/(1.2\delta_{\text{avg}}))^{2}\), \(A_x \ge 1\) | ASCE 7-22, §12.8.4.3 | sí |
| Combinación direccional 100/30 o SRSS | ASCE 7-22, §12.5.4 | sí |
| \(\theta = P_x\Delta I_e/(V_xh_{sx}C_d) \le 0.5/(\beta C_d) \le 0.25\); amplificación \(1/(1-\theta)\) | ASCE 7-22, §12.8.7 | sí |
| \(\delta_x = C_d\delta_{xe}/I_e\) | ASCE 7-22, §12.8.6 | sí |
| \(\sum M_i^{\text{ef}} = M_{\text{tot}}\) | ortogonalidad respecto de la masa | sí (identidad algebraica) |
| Límites de uso por SDC, altura y regularidad | edición aplicable | no — `VERIFICAR` |
| Umbral \(\eta_{\text{norma}}\) y factor \(\alpha\) del escalado modal | edición aplicable | no — `VERIFICAR` |
| \(A_{x,\max}\) y categorías que lo requieren | edición aplicable | no — `VERIFICAR` |
| Límites de deriva por categoría de riesgo | edición aplicable | no — `VERIFICAR` |
| \(N_{\min}\), regla de 7 registros y rango de escalado | edición aplicable | no — `VERIFICAR` |
| \(\zeta_{\text{eq}}(\mu)\) y factor de reducción | N2 / ATC-40 / FEMA 440 | no — `VERIFICAR` |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Exponente \(k\) | \(T = 1.0\ \text{s}\); \(T = 1.5\ \text{s}\) | \(k = 1.25\); \(k = 1.5\) (interpolación lineal entre 0.5 s y 2.5 s) | 1e-9 |
| Distribución en altura | \(w_1 = w_2 = 1.0\times10^{6}\ \text{N}\), \(h_1 = 3\ \text{m}\), \(h_2 = 6\ \text{m}\), \(k = 1.5\), \(V = 1.0\times10^{5}\ \text{N}\) | \(C_{v1} = 0.261204\), \(C_{v2} = 0.738796\); \(F_1 = 26120.4\ \text{N}\), \(F_2 = 73879.6\ \text{N}\) | 1e-6 relativo; \(\sum F_x = V\) a 1e-9 |
| Cortante modal de un modo | \(M^{\text{ef}} = 5.0\times10^{5}\ \text{kg}\), \(S_a = 0.60\,g\) | \(V_i = 2.941995\times10^{6}\ \text{N}\) | 1e-6 relativo |
| CQC de un par degenerado | \(\omega_i = \omega_j\), \(R_1 = R_2 = R\) | \(\rho = 1\); CQC \(= 2R\); SRSS \(= 1.414214R\) | 1e-6 relativo |
| Correlación CQC lejana | \(\omega_1 = 1\), \(\omega_2 = 10\ \text{rad/s}\), \(\zeta = 0.05\) | \(\rho_{12} = 7.0895\times10^{-4}\) | 1e-6 absoluto |
| Escalado del cortante modal | \(\alpha = 0.85\), \(V = 1000\ \text{kN}\), \(V_t = 800\ \text{kN}\) | \(f_s = 1.0625\) | 1e-9 |
| \(A_x\) y su tope | \(\delta_{\max} = 1.5\,\delta_{\text{avg}}\); y \(3.0\,\delta_{\text{avg}}\) con \(A_{x,\max} = 3\) | \(1.5625\); \(6.25\) sin tope y \(3.0\) con tope | 1e-9 |
| Direccional 100/30 y SRSS | \(E_x = 100\ \text{kN}\), \(E_y = 60\ \text{kN}\) | \(118.0\) y \(90.0\ \text{kN}\); SRSS \(= 116.6190379\ \text{kN}\) | 1e-9 / 1e-6 |
| \(\theta\) sin amplificar | \(P_x = 5\ \text{MN}\), \(\delta_{xe} = 0.02\ \text{m}\), \(V_x = 2\ \text{MN}\), \(h_{sx} = 3\ \text{m}\) | \(\theta = 0.0166667 \le 0.10\) | 1e-9 |
| \(\theta\) en el tope | \(P_x = 30\ \text{MN}\), \(\delta_{xe} = 0.05\ \text{m}\), \(V_x = 2\ \text{MN}\), \(h_{sx} = 3\ \text{m}\) | \(\theta = 0.25\); comparar con \(0.5/(\beta C_d)\) | 1e-9 |
| Deriva de diseño | \(\delta_{xe} = 0.010\ \text{m}\), \(C_d = 5.5\), \(I_e = 1.0\), \(h_{sx} = 3\ \text{m}\) | \(\delta_x = 0.055\ \text{m}\); deriva \(= 0.0183333\) | 1e-9 |
| Escalado de registros | 3 registros con \(S_a(T_1) = 0.20,\ 0.40,\ 0.60\,g\); objetivo 0.50 g de media | factor común \(1.25\); media escalada \(= 0.50\,g\) | 1e-9 |
| Reducción con \(N = 5\) | 5 respuestas pico distintas por componente | máximo componente a componente, no la media | exacto |
| Conversión a \(S_a\)–\(S_d\) y SDOF | \(T^{*} = 1.0\ \text{s}\), \(S_a = 0.40\,g\); y \(m_1 = m_2 = 1000\ \text{kg}\), \(\boldsymbol{\phi} = [0.5,\ 1.0]^{\mathsf T}\) | \(S_d = 0.0993621\ \text{m}\); \(\Gamma = 1.2\) y \(m^{*} = 1500\ \text{kg}\) | 1e-6 m / 1e-9 |

Contraste obligatorio: un edificio de referencia resuelto a mano o con un programa comercial reconocido, para ELF y modal espectral, más la comparación de \(V_t\) contra \(V\) en las dos direcciones principales.

## Errores frecuentes y trampas

1. **Escalar solo el cortante basal modal.** El factor \(f_s\) multiplica toda la respuesta; escalar únicamente \(V_t\) deja derivas y momentos subestimados.
2. **Aplicar \(C_d/I_e\) dos veces.** Si \(\Delta\) ya es la deriva de diseño, \(\theta = P_x\delta_{xe}/(V_xh_{sx})\); volver a dividir por \(C_d\) y multiplicar por \(I_e\) da un \(\theta\) falso por un factor de hasta 7.
3. **Usar SRSS con modos próximos.** Un par degenerado subestima la respuesta un 29.3 %; el fallo no se ve en los períodos, solo en \(\rho_{ij}\).
4. **Torsión accidental con un solo signo.** Correr solo \(+0.05B\) omite la envolvente y deja el resultado del lado inseguro la mitad de las veces.
5. **Desplazar el centro de masa del modelo** en lugar de aplicar el momento torsional: cambia la rigidez torsional del sistema y no es lo que pide la norma.
6. **\(A_x\) aplicado a los desplazamientos.** \(A_x\) amplifica esfuerzos internos; aplicarlo al desplazamiento infla la deriva y puede disparar \(1/(1-\theta)\) de forma espuria.
7. **\(\delta_{\text{avg}}\) calculado solo con los nodos del modelo.** Con diafragma rígido el promedio se toma sobre los puntos del nivel que define la norma.
8. **Masa modal sin cierre contra \(M_{\text{tot}}\).** Si \(\sum M_i^{\text{ef}} \ne M_{\text{tot}}\) con el conjunto completo, la matriz de masa de la participación no es la que ensambló el solver y \(\eta\) no significa nada.
9. **Invertir el orden de las operaciones.** El orden es modos → \(f_s\) → torsión → direccional → P-Δ → derivas; invertirlo cambia el resultado y rompe la trazabilidad.
10. **Escalar cada registro a la ordenada media individualmente.** Elimina la dispersión del conjunto y la media resultante no representa la demanda; el factor es común. Y **promediar con menos registros de los exigidos**: con \(N < 7\) la norma pide el máximo, y promediar subestima de forma sistemática.
11. **Amplificar dos veces por \(1/(1-\theta)\).** Si la deriva de diseño ya incluyó la amplificación, volver a aplicarla duplica el efecto.
12. **Pushover con un solo patrón de carga.** La envolvente exige al menos el patrón modal y el uniforme; un patrón único sesga el mecanismo.
13. **Fijar \(T^{*}\) con la forma modal inicial durante todo el pushover.** Al plastificar cambia la forma; \(T^{*}\) se recalcula con la rigidez secante en cada iteración del punto de desempeño.
14. **Comparar la deriva con la combinación equivocada.** El límite se comprueba con la combinación sísmica que exige la norma, no con la envolvente de todas las combinaciones.
15. **No registrar el archivo de datos normativo.** Un resultado sin `source`/`edition`/`verified_on` no es auditable y no debe poder emitirse.

## Interfaz de salida

- Procedimiento usado y verificación de sus límites de uso, con artículo y archivo de datos; procedimientos descartados y por qué.
- \(W\), \(C_s\), \(V\), \(k\), \(T_1\), \(T\) aproximado; tabla de \(F_x\) y \(V_x\).
- Modal y torsión: \(V_t\), \(\eta\) acumulada y su umbral, \(f_s\) con \(V\) y \(V_t\) (o constancia de que no se escaló); \(M_{ta}\) por nivel con el signo de cada corrida, \(A_x\) por nivel con su cita y marca de niveles amplificados.
- Direccional y P-Δ: regla aplicada (100/30 o SRSS); \(P_x\), \(V_x\), \(\delta_{xe}\), \(\theta\) y \(\theta_{\max}\) por entrepiso, con el factor \(1/(1-\theta)\) aplicado o su constancia de no aplicación.
- Derivas: \(\delta_{xe}\), \(\delta_x\), \(\Delta_x\), \(\Delta_x/h_{sx}\) y el límite con su cita; veredicto por entrepiso.
- Historia: registros con `source`, factores de escala, espectro medio escalado contra el objetivo, regla de reducción usada y respuesta reducida.
- Pushover: \(\Gamma\), \(m^{*}\), curva \(S_a\)–\(S_d\), iteraciones, punto de desempeño \((S_d^{*}, S_a^{*})\) y demanda en ese punto.
- Trazabilidad por paso (entrada, salida, combinación, edición y archivo con `verified_on`) y advertencias por cada `VERIFICAR` que afecte al veredicto.

## Referencias

1. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures*, capítulos 12 y 16.
2. ASCE/SEI 41-17, *Seismic Evaluation and Retrofit of Existing Buildings* — análisis estático no lineal y criterios de desempeño.
3. ATC-40, *Seismic Evaluation and Retrofit of Concrete Buildings*, 1996 — método del espectro de capacidad.
4. FEMA 440, *Improvement of Nonlinear Static Seismic Analysis Procedures*, 2005 — procedimiento equivalente linealizado.
5. EN 1998-1:2004, *Eurocode 8: Design of structures for earthquake resistance*, §3.3 y anexo B — método N2.
6. A. Der Kiureghian, "A response spectrum method for random vibration analysis of MDF systems", *Earthquake Engineering and Structural Dynamics*, 9(5), 1981 — coeficiente \(\rho_{ij}\).
7. A. K. Chopra, *Dynamics of Structures*, 5.ª ed., Pearson, 2017 — caps. 12–13 (modal espectral y combinación) y cap. 20 (pushover).
8. E. L. Wilson, *Three-Dimensional Static and Dynamic Analysis of Structures*, 3.ª ed., 2002 — combinación direccional y modos próximos.
9. PEER NGA-West2 / NGA-Sub, *Ground Motion Database* — selección y formato de registros.
10. OpenSeesPy 3.8.0.0, documentación de `eigen`, `responseSpectrum`, `DisplacementControl` y `UniformExcitation` (versión instalada).

## Registro de verificación

- **Verificado**: la forma de \(V = C_sW\) y de \(C_{vx}\); los valores de \(k\) y su interpolación; la expresión de \(\rho_{ij}\) y su uso en `core/modal_combination.py`; la torsión accidental del 5 %; la forma de \(A_x\) y su cota inferior 1; la combinación 100/30 y SRSS; la forma de \(\theta\), su equivalencia con \(P_x\delta_{xe}/(V_xh_{sx})\) y la amplificación \(1/(1-\theta)\); \(\delta_x = C_d\delta_{xe}/I_e\); el cierre \(\sum M_i^{\text{ef}} = M_{\text{tot}}\); y todos los valores numéricos de la tabla de casos (recalculados con NumPy el 2026-02-14).
- **Pendiente**: límites de uso por SDC, altura y regularidad; umbral \(\eta_{\text{norma}}\); factor \(\alpha\) del escalado del cortante modal y su artículo; \(A_{x,\max}\) y sus excepciones; tabla de límites de deriva; \(N_{\min}\), regla de los 7 registros y rango de escalado; y \(\zeta_{\text{eq}}(\mu)\) del punto de desempeño. Todos requieren la edición impresa o licenciada de la norma aplicable.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia licenciada del código de la jurisdicción; hasta entonces la skill permanece en `status: draft` y el programa lee cada valor de `data/<code>/*.json` y `data/seismic/*.json`.
