---
name: foundations-and-soil-structure
description: >-
  Cubre cimentaciones e interacción suelo-estructura: capacidad de carga por
  Terzaghi y Meyerhof con excentricidad e inclinación, asentamientos elásticos y
  por consolidación, asentamiento diferencial admisible, zapatas aisladas,
  combinadas, corridas y losas, pilotes y pilas (fuste, punta, grupo, eficiencia,
  asentamiento), muros de contención (Rankine, Coulomb, Mononobe-Okabe) con
  estabilidad al volcamiento, deslizamiento y capacidad portante, y resortes
  Winkler con calibración de k_s, rigidez de interfaz y longitud de empotramiento.
  Úsala al dimensionar o auditar una cimentación, al calibrar k_s o curvas p-y, al
  añadir resortes de suelo al modelo, o al revisar los requisitos sísmicos de
  cimentación y amarras de ASCE 7-22 §12.13 y cap. 19, NSR-10 Título H, RNE E.050
  y NCh2369.
metadata:
  track: design
  jurisdiction: agnostic
  edition: "n/a (remite a ASCE 7-22 cap. 12.13 y cap. 19, NSR-10 Título H, RNE E.050, NCh2369)"
  status: draft
  verified_on: "2026-02-14"
  scope: [design, analysis, qa]
---

# Cimentaciones e interacción suelo-estructura

## Cuándo usar esta skill
- Hay que dimensionar o revisar una zapata aislada, combinada, corrida o una losa de cimentación con carga axial y momentos en una o dos direcciones.
- Hay que estimar asentamiento inmediato, por consolidación primaria, total y diferencial, y compararlo con un límite admisible.
- Hay que calcular capacidad axial de pilotes o pilas por fuste y punta, la capacidad del grupo, su eficiencia y su asentamiento.
- Hay que obtener empujes de suelo estáticos (Rankine, Coulomb) o sísmicos (Mononobe-Okabe) sobre un muro y verificar volcamiento, deslizamiento y capacidad portante.
- Hay que añadir o calibrar resortes de suelo: Winkler vertical, curvas p-y, t-z, q-z, rigidez rotacional de la interfaz y longitud de empotramiento.
- Hay que comprobar requisitos sísmicos de cimentación: amarras entre zapatas, capacidad a tracción de pilotes, empotramiento e interacción suelo-estructura.
- Señales de disparo: `zeroLength` con `PySimple1`, `TzSimple1`, `QzSimple1` o `ElasticPP` como resortes de terreno; parámetros `k_s`, `subgrade`, `p-y`, `q_ult`, `FS_deslizamiento`; consultas del tipo «la zapata se levanta», «el grupo de pilotes no da», «el muro vuelca».
- **No usar** para peligro sísmico y coeficientes \(R\), \(C_d\), \(\Omega_0\) (→ `codes/asce7-22-seismic-design` y códigos nacionales), diseño estructural del elemento (→ `design/concrete-aci318`, `design/steel-aisc360-341`), formulación de elementos finitos (→ `core/fem-formulation-core`) ni ubicación de módulos (→ `platform/platform-architecture-and-services`).

## Alcance y límites
Cubre estados límite de capacidad (portante, deslizamiento, volcamiento, capacidad axial y lateral de pilotes) y de servicio (asentamiento total, diferencial y rotación) de cimentaciones superficiales y profundas, empujes del terreno sobre muros y modelado de la interfaz suelo-estructura.
**No cubre**: exploración y ensayos de campo o laboratorio (consume el perfil geotécnico del estudio); estabilidad de taludes; licuación y densificación; mejora de suelos; refuerzo del elemento estructural; interacción dinámica con impedancias dependientes de la frecuencia (aquí solo rigidez estática equivalente y amortiguamiento declarado).
Supuestos: capas horizontales y homogéneas dentro de cada capa; parámetros drenados (\(\varphi'\), \(c'\)) o no drenados (\(c_u\)) declarados por el usuario y nunca deducidos en silencio; cimentación rígida salvo declaración contraria; cargas de servicio para estados límite de servicio y mayoradas solo donde se exija.

## Entradas y supuestos
| Dato | Obligatorio | Si falta |
|---|---|---|
| Perfil estratigráfico con \(\gamma\), \(\gamma'\), \(\varphi'\), \(c'\), \(c_u\), \(E_s\), \(\nu_s\) | sí | **bloquear**: no se inventan parámetros de suelo |
| Nivel freático | sí | suponerlo en superficie (conservador) y avisar |
| Tipo, \(D_f\), \(B\), \(L\) de la cimentación | sí | bloquear |
| Cargas por combinación (\(P\), \(M_B\), \(M_L\), \(V\)) con su punto de aplicación | sí | bloquear |
| Método de cálculo (Terzaghi, Meyerhof, Hansen, Vesić) | sí | bloquear: los resultados no son comparables entre métodos |
| \(k_h\), \(k_v\) del sismo y sentido del empuje | sí si hay sismo | bloquear; se leen del código |
| Coeficientes de seguridad y asentamientos admisibles | sí | leer del archivo de datos versionado; no usar valores internos |
| Unidades del modelo | sí | SI coherente; se rechaza mezclar kPa, kN/m³ y m sin declarar la conversión |

Presentación en kPa, MN/m³, kN·m/m y mm declarando la conversión; almacén interno SI coherente (N, m, kg, s, Pa), \(g = 9.80665\ \text{m/s}^2\).

## Fundamento y formulación
### 1. Capacidad de carga
Terzaghi, falla general, zapata corrida con carga vertical centrada (\(q_{ult}\) en Pa; \(c'\), \(q\) en Pa; \(\gamma\) en N/m³; \(B\), \(D_f\) en m; \(N\) adimensionales), con \(q = \gamma D_f\):
$$q_{ult} = c' N_c + q N_q + \tfrac{1}{2}\gamma B N_\gamma,\qquad N_q = \frac{a^{2}}{2\cos^{2}\!\left(45^\circ + \varphi'/2\right)},\quad a = e^{\left(\frac{3\pi}{4} - \frac{\varphi'}{2}\right)\tan\varphi'},\quad N_c = (N_q - 1)\cot\varphi'$$
Falla local: reemplazar \(c'\) y \(\tan\varphi'\) por \(\tfrac{2}{3}\) de sus valores. Meyerhof (forma general, \(B' = B - 2e_B\), \(L' = L - 2e_L\), \(e_B = M_L/P\), \(e_L = M_B/P\), presión uniforme sobre \(A' = B'L'\)):
$$q_{ult} = c' N_c s_c d_c i_c + q N_q s_q d_q i_q + \tfrac{1}{2}\gamma B' N_\gamma s_\gamma d_\gamma i_\gamma,\qquad N_q = e^{\pi\tan\varphi'}\tan^{2}\!\left(45^\circ + \varphi'/2\right)$$
$$N_c = (N_q-1)\cot\varphi',\qquad N_\gamma = (N_q-1)\tan(1.4\,\varphi')$$
Modo no drenado (\(\varphi = 0\)): \(q_{ult} = c_u N_c s_c d_c + q\). Los factores de forma, profundidad e inclinación cambian entre autores (Meyerhof, Hansen, Vesić) y son la fuente principal de discrepancia entre programas.
> ⚠️ VERIFICAR: los valores tabulados de \(N_\gamma\) de Terzaghi (1943), sin forma cerrada y distintos de \(2(N_q+1)\tan\varphi'\) y de \((N_q-1)\tan(1.4\varphi')\), y los juegos completos \(s\), \(d\), \(i\) de cada autor se transcriben de una edición impresa a `data/geotech/capacity_factors.json` con `source` y `verified_on`. El programa no incrusta estas tablas en el código.

### 2. Asentamientos
Inmediato (teoría elástica): \(s_e = q_0 B' (1-\nu_s^{2}) I_s I_f / E_s\), con \(s_e\) en m, presión neta \(q_0 = q_{contacto} - \gamma D_f\) en Pa, \(E_s\) en Pa, \(I_s\) factor de forma de Steinbrenner (función de \(L/B\) y \(H/B\)) e \(I_f\) factor de profundidad de Fox; en zapata rígida, multiplicar el asentamiento flexible representativo por el factor de rigidez.
Consolidación primaria unidimensional (arcilla normalmente consolidada):
$$s_c = \sum_i \frac{C_{c,i}\,H_i}{1+e_{0,i}}\log_{10}\!\frac{\sigma'_{v0,i}+\Delta\sigma_{v,i}}{\sigma'_{v0,i}}$$
Arcilla preconsolidada con \(\sigma'_p\): si \(\sigma'_{v0}+\Delta\sigma_v \le \sigma'_p\), usar \(C_{s,i}\) en lugar de \(C_{c,i}\); si \(\sigma'_{v0} < \sigma'_p < \sigma'_{v0}+\Delta\sigma_v\),
$$s_c = \sum_i \frac{H_i}{1+e_{0,i}}\left[C_{s,i}\log_{10}\frac{\sigma'_{p,i}}{\sigma'_{v0,i}} + C_{c,i}\log_{10}\frac{\sigma'_{v0,i}+\Delta\sigma_{v,i}}{\sigma'_{p,i}}\right]$$
\(\sigma'_{v0}\) tensión vertical efectiva inicial, \(\Delta\sigma_v\) incremento por la cimentación (Boussinesq o solución elástica de zapata rectangular) evaluado **en el centro de cada subcapa**, \(H_i\) espesor de la subcapa en m. Evolución temporal con \(T_v = c_v t / H_{dr}^{2}\) (\(H_{dr}\) = máxima distancia de drenaje; doble drenaje → \(H/2\)):
$$U = 1 - \sum_{m=0}^{\infty}\frac{2}{M^{2}}e^{-M^{2}T_v},\quad M = \frac{(2m+1)\pi}{2};\qquad T_v \approx \tfrac{\pi}{4}U^{2}\ (U<60\,\%),\quad T_v \approx 1.781 - 0.933\log_{10}(100-U\%)\ (U>60\,\%)$$
Diferencial: distorsión angular \(\beta = \delta/L\) entre puntos separados \(L\).
> ⚠️ VERIFICAR: los admisibles de asentamiento total, diferencial y distorsión angular no se fijan aquí; se transcriben del reglamento aplicable (NSR-10 Título H, RNE E.050, NCh2369 o criterio de proyecto) a `data/geotech/settlement_limits.json`. Los valores de Skempton y MacDonald (1956) y Bjerrum (1963) son literatura, no norma, y así deben rotularse.

### 3. Zapatas y losas
- Aislada centrada: \(q_{max,min} = P/A \pm M_B c/I_B \pm M_L c/I_L\). Excéntrica: si \(e > B/6\) hay despegue; usar área efectiva y comprobar el límite reglamentario de excentricidad.
- Combinada: reparto rectangular o trapezoidal con el centroide del área coincidente con la resultante de las dos columnas. Corrida: por metro de longitud, sin factores de forma en \(B\).
- Losa rígida: \(p = P/A \pm M_x y/I_x \pm M_y x/I_y\). Losa flexible: placa sobre medio elástico con \(k_s\) o elementos finitos sobre resortes; radio de rigidez relativa de Westergaard \(\ell = [E_f h^{3}/(12(1-\nu_f^{2})k_s)]^{1/4}\) (\(E_f\) en Pa, \(h\) en m, \(k_s\) en N/m³) y criterio de viga corta de Hetényi \(L/\ell < \pi/4\).
### 4. Pilotes y pilas
\(Q_{ult} = Q_p + Q_s = q_p A_p + \sum_i f_{s,i} p_i \Delta L_i\), con \(Q\) en N, \(A_p\) área de punta en m², \(p_i\) perímetro en m, \(\Delta L_i\) en m.
- Arcilla: \(f_s = \alpha c_u\); punta \(q_p = N_c^{*} c_u\) con \(N_c^{*} = 9\) para \(L/D \ge 4\) (Skempton, 1951). \(\alpha\) depende de \(c_u\) y del tipo de pilote.
- Arena: \(f_s = \beta\sigma'_v = K\tan\delta\,\sigma'_v\); punta \(q_p = \sigma'_v N_q\) con \(\sigma'_v\) limitada a \(15D\) de profundidad.
- Añadir fricción negativa (*downdrag*) por relleno reciente; en tracción usar solo \(Q_s\) con su factor de seguridad.
Eficiencia de grupo (Converse-Labarre) con \(\theta = \arctan(D/s)\) en grados, \(m\) filas y \(n\) columnas:
$$\eta = 1 - \frac{\theta}{90}\cdot\frac{(n-1)m+(m-1)n}{m\,n},\qquad Q_{g,ult} = \min\left(\eta\,n_{pilotes}Q_{ult},\ Q_{bloque}\right)$$
\(Q_{bloque}\) (falla de bloque del pilote equivalente) se calcula siempre y se toma el menor. Asentamiento del grupo: pilote equivalente con reparto 2:1 desde \(2L/3\), o solución elástica de cimentación profunda.
> ⚠️ VERIFICAR: los rangos tabulados de \(\alpha\) (Tomlinson), \(\beta\) en arena, \(N_q\) de punta, la profundidad crítica y el factor de amplificación de asentamiento del grupo varían entre ediciones y se cargan de `data/geotech/pile_factors.json`; ninguna constante se codifica.
### 5. Empujes del terreno y muros
Rankine con relleno granular de pendiente \(\beta_s\) sobre trasdós vertical:
$$K_a = \cos\beta_s\frac{\cos\beta_s - \sqrt{\cos^{2}\beta_s - \cos^{2}\varphi'}}{\cos\beta_s + \sqrt{\cos^{2}\beta_s - \cos^{2}\varphi'}},\qquad K_p = \tan^{2}\!\left(45^\circ + \varphi'/2\right)$$
Coulomb general (trasdós inclinado \(\alpha\) respecto de la horizontal, fricción muro-suelo \(\delta\), relleno \(\beta_s\)):
$$K_a = \frac{\sin^{2}(\alpha+\varphi')}{\sin^{2}\alpha\,\sin(\alpha-\delta)\left[1+\sqrt{\dfrac{\sin(\varphi'+\delta)\sin(\varphi'-\beta_s)}{\sin(\alpha-\delta)\sin(\alpha+\beta_s)}}\right]^{2}}$$
Mononobe-Okabe con \(\theta = \arctan[k_h/(1-k_v)]\), \(i\) pendiente del relleno y \(\beta\) inclinación del trasdós **respecto de la vertical** (\(\beta = 0\) en muro vertical):
$$K_{AE} = \frac{\cos^{2}(\varphi'-\theta-\beta)}{\cos\theta\,\cos^{2}\beta\,\cos(\delta+\beta+\theta)\left[1+\sqrt{\dfrac{\sin(\varphi'+\delta)\sin(\varphi'-\theta-i)}{\cos(\delta+\beta+\theta)\cos(i-\beta)}}\right]^{2}}$$
$$P_{AE} = \tfrac{1}{2}\gamma H^{2}K_{AE}(1-k_v),\qquad \Delta P_{AE} = P_{AE} - P_A$$
\(P_{AE}\) en N/m, \(H\) altura del muro en m. \(P_A\) se aplica a \(H/3\) desde la base y \(\Delta P_{AE}\) a \(0.6H\) (Seed y Whitman, 1970). Sumar empuje por sobrecarga \(qK_a\) y presión hidrostática si el drenaje es deficiente.
$$FS_{volcamiento} = \frac{\sum M_{res}}{\sum M_{volc}},\qquad FS_{deslizamiento} = \frac{\sum V\tan\delta_b + c_a B_{base}}{\sum H},\qquad FS_{portante} = \frac{q_{ult}}{q_{max}}$$
> ⚠️ VERIFICAR: los \(FS\) mínimos (estáticos y sísmicos) y el tratamiento de la componente vertical del sismo los fija el reglamento aplicable; NCh2369 y RNE E.050 particularizan el caso sísmico. Se leen de `data/geotech/wall_fs.json` con su cita. La práctica geotécnica habitual (≈1.5 volcamiento, ≈1.5 deslizamiento, ≈3 portante en estático) es referencia, no norma.
### 6. Winkler, \(k_s\) y empotramiento
$$k_s = \frac{q}{\delta}\ [\text{N/m}^{3}];\qquad k_s = \frac{0.65\,E_s}{B(1-\nu_s^{2})}\left(\frac{E_s B^{4}}{E_f I_f}\right)^{1/12}\ \text{(Vesić, 1961)}$$
\(E_fI_f\) rigidez flexional del elemento en N·m². \(k_s\) **no es propiedad del suelo**: depende de \(B\) y del tipo de placa de referencia, y la escala de Terzaghi desde una placa de 0.3 m debe recalcularse al ancho real.
Arcilla (Matlock, 1970) con \(J \approx 0.5\), \(p\) en N/m, \(z\) profundidad en m, \(D\) diámetro en m:
$$p_u = \min\left[\left(3+\frac{\gamma' z}{c_u}+J\frac{z}{D}\right)c_u D,\ 9c_u D\right],\qquad p = 0.5\,p_u\left(\frac{y}{y_c}\right)^{1/3},\quad y_c = 2.5\,\varepsilon_c D$$
Arena (API): \(p = A p_u \tanh[k z y/(A p_u)]\) con \(k\) el módulo inicial de reacción.
- Separación de resortes \(\Delta z \le 0.5\ \text{m}\) y \(\Delta z \le D\); refinar y comprobar que la respuesta no cambia más que la tolerancia declarada.
- Resortes verticales bajo zapata: \(k_{nudo} = k_s A_{tributaria}\) en N/m; la rigidez rotacional de la interfaz **emerge** de su distribución y no se impone aparte.
- Longitud de empotramiento: se obtiene del análisis p-y, no de una regla fija; la profundidad de fijación equivalente es donde el momento se anula por segunda vez en pilote de cabeza libre.
- Los resortes de suelo no toman tracción real: usar materiales con gap o no lineales, o verificar \(p \ge 0\) en todos los resortes.

### 7. Requisitos sísmicos
- ASCE 7-22 §12.13: cimentaciones diseñadas con las combinaciones que incluyen sismo y con sobrerresistencia donde el sistema la exija; comprobar tracción y compresión en pilotes y levantamiento de zapatas.
- Amarras entre apoyos individuales: fuerza mínima de tracción o compresión expresada como fracción de la carga axial mayorada de la columna.
- ASCE 7-22 cap. 19: interacción cinemática, amortiguamiento de cimentación y análisis de interacción suelo-estructura.
- Códigos nacionales: NSR-10 Título H, RNE E.050 y NCh2369 fijan parámetros, admisibles y \(FS\) sísmicos propios.
> ⚠️ VERIFICAR: la numeración y el texto exactos de ASCE 7-22 §12.13.x (cargas, requisitos por categoría de diseño, valor de la fuerza de amarra) y §19.2–§19.5 (aplicabilidad del análisis de SSI, amortiguamiento, interacción cinemática), así como los artículos de NSR-10 Título H, RNE E.050 y NCh2369, se copian a `data/geotech/seismic_foundation.json` con artículo y cita; el programa los lee de ahí.

## Procedimiento
1. Clasificar el estado de cálculo (drenado \(\varphi',c'\) o no drenado \(c_u\)) y declarar el método; bloquear si no está declarado.
2. Reunir geometría, \(D_f\), \(B\), \(L\) y cargas por combinación; calcular \(e_B\), \(e_L\), área efectiva y presión de contacto.
3. Calcular \(q_{ult}\), aplicar el \(FS\) del archivo de datos, obtener \(q_{adm}\) y comparar con \(q_{max}\) (\(D/C\)).
4. Calcular \(s_e\), \(s_c\) y \(s_{total}\) en centro y esquinas; obtener asentamiento diferencial y distorsión angular entre apoyos.
5. Si \(D/C>1\) o el asentamiento excede el admisible, cambiar de tipo (losa, pilotes, mejora) y volver al paso 2.
6. Con pilotes: \(Q_{ult}\) por pilote, \(\eta\), \(Q_{g,ult} = \min(\eta n Q_{ult}, Q_{bloque})\) y asentamiento del grupo.
7. Con muro: \(K_a\), \(K_p\), \(K_{AE}\), \(P_{AE}\), puntos de aplicación y las tres verificaciones de estabilidad con el \(FS\) reglamentario.
8. Calibrar \(k_s\) o las curvas p-y/t-z/q-z con el ancho o diámetro reales y emitir los resortes con su geometría.
9. Resolver, extraer reacciones y desplazamientos, comprobar resortes sin tracción y que la profundidad de momento nulo quede dentro del pilote modelado.
10. Aplicar los requisitos sísmicos de cimentación y amarras y emitir el informe con la cita de cada valor regulado.

## Implementación en la plataforma
```python
# core/geotech/soil_profile.py  (core puro: sin Qt, sin OpenSeesPy)
class SoilLayer(BaseModel):
    gamma: float; gamma_sat: float; phi: float | None; c_prime: float | None
    cu: float | None; Es: float; nu: float; thickness: float
    source: str; verified_on: date

# core/geotech/bearing_capacity.py
def bearing_capacity(layer, footing, load, method: Literal["terzaghi", "meyerhof"],
                     factors: CapacityFactors) -> BearingCapacityResult: ...

# core/geotech/settlement.py
def elastic_settlement(profile, footing, q_net, influence) -> SettlementResult: ...
def consolidation_settlement(profile, footing, q_net) -> ConsolidationResult: ...
def differential_settlement(points, limits) -> DifferentialResult: ...

# core/geotech/deep_foundations.py
def pile_axial_capacity(profile, pile, factors: PileFactors) -> PileCapacityResult: ...
def group_efficiency(n_rows: int, n_cols: int, diameter: float, spacing: float) -> float: ...
def group_capacity(piles, block: float) -> GroupResult: ...

# core/geotech/earth_pressure.py
def rankine_active(phi: float, backfill_slope: float) -> float: ...
def coulomb_active(phi: float, delta: float, alpha: float, beta: float) -> float: ...
def mononobe_okabe(phi, delta, beta, i, kh, kv) -> EarthPressureResult: ...
def wall_stability(wall, pressures, fs: WallFactors) -> WallStabilityResult: ...

# core/geotech/springs.py
def winkler_modulus(Es: float, nu: float, B: float, EfIf: float,
                    method: Literal["vesic", "terzaghi"]) -> float: ...
def py_curve_clay(cu, eps50, gamma_eff, z, D, J=0.5) -> list[tuple[float, float]]: ...
def nodal_springs(k_s: float, tributary_area: float, nodes) -> list[SpringSpec]: ...
```
```python
# services/geotech/spring_emitter.py  (única capa que importa OpenSeesPy)
def emit_winkler_springs(ops_model, specs, material="Elastic") -> None:
    """zeroLength + uniaxialMaterial; PySimple1/TzSimple1/QzSimple1 si la
    especificación trae curva no lineal."""
```
Reglas de arquitectura (ver `platform/platform-architecture-and-services`): todo el cálculo geotécnico vive en `core/geotech/` y no importa Qt ni OpenSeesPy, de modo que es verificable desde un script y desde pruebas unitarias; la emisión al solver vive en `services/geotech/` y ninguna vista importa OpenSeesPy; los coeficientes (\(FS\), admisibles, \(N_\gamma\), \(\alpha\), \(\beta\), \(k\) de API) viven en `data/geotech/*.json` con `source` y `verified_on`, cada uno con prueba unitaria; todo resultado arrastra método, \(FS\) aplicado, edición normativa y versión del archivo de datos.

## Datos normativos
| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(N_q\), \(N_c\) de Terzaghi en forma cerrada | Terzaghi (1943); Das, *Principles of Foundation Engineering* | sí (álgebra recomputada) |
| \(N_q\), \(N_c\), \(N_\gamma\) de Meyerhof | Meyerhof (1963) | sí (álgebra recomputada) |
| \(N_\gamma\) tabulado de Terzaghi; \(s\), \(d\), \(i\) por autor | Terzaghi (1943); Meyerhof (1963); Hansen (1970); Vesić (1973) | no — `VERIFICAR`; `data/geotech/capacity_factors.json` |
| \(N_c^{*} = 9\) para \(L/D \ge 4\) | Skempton (1951) | sí |
| \(\alpha\), \(\beta\), profundidad crítica y amplificación de grupo | Tomlinson; literatura de pilotes | no — `VERIFICAR`; `data/geotech/pile_factors.json` |
| \(k_s\) de Vesić (coeficiente 0.65, exponente 1/12) | Vesić (1961) | no — `VERIFICAR` contra la publicación original |
| \(p_u\) de Matlock para arcilla | Matlock (1970) | sí (álgebra recomputada) |
| \(k\) inicial de API para arena | API RP 2GEO / ISO 19901-4 | no — `VERIFICAR`; tabla al archivo de datos |
| \(\Delta P_{AE}\) a \(0.6H\) | Seed y Whitman (1970) | sí |
| \(FS\) de volcamiento, deslizamiento y portante; admisibles de asentamiento | NCh2369; RNE E.050; NSR-10 Título H; criterio de proyecto | no — `VERIFICAR`; `data/geotech/*.json` |
| Requisitos sísmicos de cimentación y amarras | ASCE 7-22 §12.13 y cap. 19 | no — `VERIFICAR` (numeración y valores) |

## Verificación y casos de prueba
| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| \(N_q\), \(N_c\) de Terzaghi | \(\varphi' = 30^\circ\) | \(N_q = 22.46\); \(N_c = 37.16\) | 0.1 % rel. | cálculo a mano (1943) |
| \(N_q\), \(N_c\), \(N_\gamma\) de Meyerhof | \(\varphi' = 30^\circ\) | 18.40; 30.14; 15.67 | 0.1 % rel. | cálculo a mano (1963) |
| Límite \(\varphi \to 0\) | \(\varphi' = 0\) | \((N_q-1)\cot\varphi' \to 5.14\) (no 5.7) | 1e-3 | L'Hôpital; Prandtl |
| Ancho efectivo | \(B=2\ \text{m}\), \(L=1.5\ \text{m}\), \(M_L=60\ \text{kN·m}\), \(P=300\ \text{kN}\) | \(e_B=0.20\ \text{m}\); \(B'=1.60\ \text{m}\); \(A'=2.4\ \text{m}^2\) | 1e-9 | definición |
| \(q_{ult}\) no drenado | \(c_u=50\ \text{kPa}\), \(q=36\ \text{kPa}\), \(s_c=1.2\) | \(344.4\ \text{kPa}\) | 0.1 % rel. | Meyerhof |
| Asentamiento elástico | \(q_0=150\ \text{kPa}\), \(B=2\ \text{m}\), \(\nu=0.30\), \(E_s=30\ \text{MPa}\), \(I_s=1.12\), \(I_f=1.0\) | \(s_e = 10.2\ \text{mm}\) | 0.5 % rel. | teoría elástica |
| Consolidación | \(C_c=0.3\), \(e_0=0.9\), \(H=3\ \text{m}\), \(\sigma'_{v0}=60\ \text{kPa}\), \(\Delta\sigma=40\ \text{kPa}\) | \(s_c = 105.1\ \text{mm}\) | 0.1 % rel. | Terzaghi 1D |
| Grado de consolidación | \(U = 50\ \%\) | \(T_v = 0.197\) | 1e-3 | serie de Terzaghi |
| Eficiencia de grupo | 3×3, \(D=0.4\ \text{m}\), \(s=1.2\ \text{m}\) | \(\eta = 0.7269\) | 1e-4 | Converse-Labarre |
| \(K_a\) de Rankine | \(\varphi'=30^\circ\), \(\beta_s=10^\circ\) | \(K_a = 0.3495\) | 1e-4 | Rankine |
| \(K_a\) de Coulomb | \(\varphi'=30^\circ\), \(\delta=20^\circ\), \(\alpha=90^\circ\), \(\beta_s=0\) | \(K_a = 0.2973\) | 1e-4 | Coulomb |
| \(K_{AE}\) de Mononobe-Okabe | \(\varphi'=30^\circ\), \(\delta=20^\circ\), \(\beta=i=0\), \(k_h=0.2\), \(k_v=0\) | \(K_{AE}=0.4540\); \(\Delta K_{AE}=0.1566\) | 1e-4 | Mononobe-Okabe |
| \(k_s\) de Vesić | \(E_s=30\ \text{MPa}\), \(\nu=0.3\), \(B=2\ \text{m}\), \(E_fI_f=1.0\ \text{GN·m}^2\) | \(10.08\ \text{MN/m}^3\) | 1 % rel. | Vesić (1961) |
| \(p_u\) de Matlock | \(c_u=50\ \text{kPa}\), \(\gamma'=8\ \text{kN/m}^3\), \(z=1.5\ \text{m}\), \(D=0.6\ \text{m}\), \(J=0.5\) | \(134.7\ \text{kN/m}\) (gobierna el primer término; \(9c_uD=270\)) | 0.1 % rel. | Matlock (1970) |
| \(FS\) al deslizamiento | \(\sum V=300\ \text{kN/m}\), \(\sum H=75\ \text{kN/m}\), \(\delta_b=20^\circ\), \(c_a=0\) | \(FS = 1.456\) | 1e-3 | definición |
| Independencia de malla | resortes a \(0.5\ \text{m}\) vs. \(0.25\ \text{m}\) | desplazamiento máximo con diferencia \(<1\ \%\) | 1 % rel. | convergencia numérica |

Contraste adicional obligatorio: un caso de zapata y uno de pilote contra un programa geotécnico de referencia reconocido, y la reproducción de al menos dos ejemplos resueltos del libro de texto adoptado.

## Errores frecuentes y trampas
1. **Mezclar \(N_\gamma\) de un autor con \(N_q\) y \(N_c\) de otro**: los juegos de factores no son intercambiables y el resultado cambia decenas de por ciento; registrar el método en el resultado y bloquear la mezcla.
2. **No reducir el ancho por excentricidad**: calcular la presión con \(B\) y \(L\) totales sobreestima la capacidad; la formulación de Meyerhof exige \(B'\), \(L'\) y presión uniforme sobre \(A'\).
3. **Evaluar \(N_c = (N_q-1)\cot\varphi'\) en \(\varphi'=0\)**: división por cero; el límite es 5.14 (Prandtl) pero el valor tabulado de Terzaghi para base rugosa es 5.7. Hay que codificar la rama.
4. **Sumar el peso propio de la zapata y el término \(q=\gamma D_f\) a la vez** en el asentamiento elástico: \(q_0\) es la presión neta.
5. **Usar el espesor total de arcilla como \(H\) en vez de \(H_{dr}\)**: con doble drenaje el tiempo de consolidación cae por 4; usar \(H\) total lo sobreestima en ese factor.
6. **Evaluar \(\Delta\sigma_v\) en la superficie de la capa** en lugar del centro de cada subcapa; el error crece con el espesor de la subcapa.
7. **Recalcular \(k_s\) con un \(B\) distinto del calibrado**: \(k_s\) no es propiedad del suelo; aplicar el \(k_s\) de una placa de 0.3 m a una zapata de 3 m produce momentos y asentamientos irreales.
8. **Resortes de suelo lineales que toman tracción**: un uniaxial `Elastic` deja al terreno «tirando» del elemento; usar gap/`PySimple1` o comprobar \(p \ge 0\) en todos los resortes.
9. **Tomar la eficiencia de Converse-Labarre como capacidad de grupo** sin calcular la falla de bloque: en grupos pequeños y separados gobierna el bloque.
10. **Confundir \(k_h\) de Mononobe-Okabe con el coeficiente sísmico del código** sin reducirlo al nivel de la cimentación, olvidar \(k_v\) y omitir el factor \((1-k_v)\) en \(P_{AE}\).
11. **Aplicar \(\Delta P_{AE}\) en \(H/3\)**: el incremento dinámico va a \(0.6H\) y repartirlo mal altera el momento de volcamiento.
12. **Usar \(\delta_b = \varphi'\) en el deslizamiento** en vez del valor de interfaz (\(\approx 2\varphi'/3\)) y sumar cohesión adherente sin justificar.
13. **Olvidar la presión hidrostática** en el trasdós cuando el drenaje es deficiente: es la causa más común de muros volcados en obra.
14. **Obtener la longitud de empotramiento con una regla fija** en vez del análisis p-y y no verificar que la profundidad de momento nulo quede dentro del pilote modelado.
15. **Redondear \(q_{ult}\) antes de dividir por el \(FS\)** y antes de comparar con \(q_{max}\).

## Interfaz de salida
- Capacidad: \(q_{ult}\), \(q_{adm}\), \(FS\) aplicado, \(q_{max}\), \(D/C\) y método usado, con cita de la fuente de los factores.
- Presiones de contacto: diagrama con \(q_{max}\), \(q_{min}\), \(e_B\), \(e_L\), área efectiva y aviso de despegue o de kern excedido.
- Asentamientos: \(s_e\), \(s_c\), \(s_{total}\) por punto, diferencial, distorsión angular y comparación con el admisible citado.
- Pilotes: \(Q_p\), \(Q_s\), \(Q_{ult}\), \(Q_{adm}\), \(\eta\), \(Q_{g,ult}\), \(Q_{bloque}\), asentamiento del grupo y verificación de tracción.
- Muros: \(K_a\), \(K_p\), \(K_{AE}\), \(P_A\), \(P_{AE}\), puntos de aplicación, los tres \(FS\) y veredicto.
- Resortes: \(k_s\) o curva p-y usada, coordenadas, área tributaria, rango de validez y desplazamiento máximo alcanzado.
- Trazabilidad: edición normativa, artículo, versión del archivo de datos, `verified_on` y lista de `VERIFICAR` abiertos que afectan al resultado.
- Advertencias activas: resortes en tracción, \(e>B/6\), \(FS\) bajo el mínimo, asentamiento diferencial excedido, empotramiento insuficiente.

## Referencias
1. K. Terzaghi, *Theoretical Soil Mechanics*, Wiley, 1943.
2. G. G. Meyerhof, «Some recent research on the bearing capacity of foundations», *Canadian Geotechnical Journal*, 1(1), 1963.
3. K. Terzaghi, «Evaluation of coefficients of subgrade reaction», *Géotechnique*, 5(4), 1955.
4. A. B. Vesić, «Bending of beams resting on isotropic elastic solids», *Journal of the Engineering Mechanics Division*, ASCE, 87(2), 1961.
5. H. Matlock, «Correlations for design of laterally loaded piles in soft clay», OTC 1204, 1970.
6. H. B. Seed y R. V. Whitman, «Design of earth retaining structures for dynamic loads», *Lateral Stresses in the Ground and Design of Earth-Retaining Structures*, ASCE, 1970.
7. A. W. Skempton, «The bearing capacity of piles», *Proc. 3rd ICSMFE*, 1951.
8. A. W. Skempton y D. H. MacDonald, «The allowable settlements of buildings», *Proc. ICE*, 5(6), 1956.
9. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures*, cap. 12.13 y cap. 19.
10. NSR-10, Reglamento Colombiano de Construcción Sismo Resistente, Título H «Estudios geotécnicos», 2010.
11. RNE E.050, *Suelos y Cimentaciones*, Reglamento Nacional de Edificaciones, Perú.
12. NCh2369, *Diseño sísmico de estructuras e instalaciones industriales*, INN, Chile.
13. API RP 2GEO / ISO 19901-4, curvas p-y para pilotes en arena.
14. B. M. Das, *Principles of Foundation Engineering*, Cengage — edición del catálogo interno (confirmar antes de citar tablas).
15. M. Hetényi, *Beams on Elastic Foundation*, University of Michigan Press, 1946.

## Registro de verificación
- **Verificado (2026-02-14)**: formas cerradas de \(N_q\) y \(N_c\) de Terzaghi y de \(N_q\), \(N_c\), \(N_\gamma\) de Meyerhof, recomputadas a mano para \(\varphi'=30^\circ\); el límite \(\varphi\to 0\); el álgebra de Converse-Labarre; la \(p_u\) de Matlock; las expresiones de Rankine, Coulomb y Mononobe-Okabe y su reducción al caso de muro vertical con relleno horizontal; el punto de aplicación \(0.6H\) de \(\Delta P_{AE}\).
- **Pendiente**: \(N_\gamma\) tabulado de Terzaghi; factores \(s\), \(d\), \(i\) por autor; factores de influencia \(I_s\), \(I_f\); constantes de Vesić; tabla \(k\) de API; \(\alpha\), \(\beta\), profundidad crítica y amplificación de grupo en pilotes; \(FS\) y admisibles de asentamiento por jurisdicción; numeración y texto de ASCE 7-22 §12.13.x y §19.2–§19.5; NSR-10 Título H; RNE E.050; NCh2369; edición del libro de texto adoptado.
- **Cierre**: cada pendiente se transcribe a `data/geotech/*.json` con `source` y `verified_on` y se convierte en prueba unitaria contra la tabla publicada. Responsable: el ingeniero geotécnico del proyecto, con copia licenciada de cada documento.
- **Estado**: `draft` mientras existan marcas `VERIFICAR` en este archivo.
