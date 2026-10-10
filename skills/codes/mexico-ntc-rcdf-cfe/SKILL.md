---
name: mexico-ntc-rcdf-cfe
description: >-
  Implementa y audita el análisis y el diseño sísmico conforme a las NTC del RCDF
  (sismo, concreto y acero; edición 2020 de la Ciudad de México) y al capítulo de
  Diseño por Sismo del MDOC/CFE: zonificación, espectro del SASID o paramétrico
  (a0, c, Ta, Tb, k, Ts), reducción por comportamiento sísmico Q' y por
  sobre-resistencia R, importancia, torsión accidental, segundo orden, distorsiones
  límite, regularidad y análisis estático, modal y no lineal. Úsala cuando el predio
  esté en México, el proyecto declare `code = NTC-RCDF` o `MDOC/CFE`, o los datos
  traigan Q, Q', R, a0, c, Ts o γmax y haya que auditarlos contra el capítulo 3.
metadata:
  track: codes
  jurisdiction: MEX
  edition: "NTC-RCDF (sismo, concreto y acero) y MDOC/CFE 2020"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# México — NTC-RCDF (sismo, concreto, acero) y MDOC/CFE 2020

## Cuándo usar esta skill

- El predio está en México y el proyecto declara `code = NTC-RCDF` (Ciudad de México) o `code = MDOC/CFE` (República Mexicana, obras civiles de CFE).
- Hay que construir el espectro de diseño desde el SASID o desde los parámetros básicos \(a_0, c, T_a, T_b, k, T_s\), o reproducir un espectro entregado en una memoria de cálculo de terceros.
- Hay que decidir el procedimiento de análisis (estático cap. 7, modal espectral cap. 6.1, no lineal paso a paso cap. 6.2), comprobar sus límites de altura y de regularidad, o resolver discrepancias entre dos programas que reportan \(Q\), \(Q'\), \(R\), \(\gamma_{max}\), \(K_s\), \(T_s\), \(a_{min}\) o \(e_a\).

**No usar** para códigos de otros países: ver `codes/asce7-22-seismic-design`, `codes/nicaragua-rnc07-nscm22`, `codes/colombia-nsr10`, `codes/peru-e030`, `codes/chile-nch433-nch2369`. El dimensionamiento de secciones y el detallado viven en las NTC de concreto y de acero y en las skills de `design/`; esta skill produce acciones y verifica estados límite globales.

## Alcance y límites

Cubre de las **NTC para Diseño por Sismo, RCDF, Gaceta Oficial de la Ciudad de México, 9 de junio de 2020 (con comentarios)**: zonificación (§1.3), clasificación por grupos (§1.4), cortante basal mínimo (§1.7), revisión de desplazamientos (§1.8), separación de colindancias (§1.9), métodos de análisis y límites de altura (§2.1), torsión (§2.2), segundo orden (§2.3), efectos bidireccionales (§2.4), comportamiento asimétrico (§2.5), péndulos invertidos (§2.6), diafragmas y contenidos (§2.7), espectros (§§3.1 a 3.5), \(Q\) y \(\gamma_{max}\) (§4.2), regularidad (§5), análisis dinámico (§6), análisis estático (§7) e interacción suelo-estructura (§8).

**No cubre**: dimensionamiento de elementos (NTC-Concreto y NTC-Acero 2020), diseño geotécnico y de cimentación (NTC-Cimentaciones), peligro de sitios con estudio específico (Apéndice A) ni aislamiento y disipadores (§§9 a 14). Fuera de la Ciudad de México aplica el MDOC/CFE; ambos cuerpos normativos **no** se mezclan en el mismo modelo.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Ubicación del predio (latitud/longitud o manzana) | sí | bloquear: el espectro proviene del SASID y no se interpola a mano |
| Zona geotécnica I, II o III (§1.3) y periodo \(T_s\) (s) | sí | bloquear; \(T_s\) se lee del SASID, no de tablas de otra edición |
| Grupo y subgrupo A1, A2 o B (Art. 139 RCDF) | sí | bloquear (define 1.5 / 1.3 / 1.0) |
| Sistema estructural, clase de ductilidad y número de crujías en ambas direcciones | sí | bloquear: de aquí salen \(Q\), \(\gamma_{max}\) y \(k_1\) |
| Clasificación de regularidad (§§5.1 a 5.4) | sí | evaluar los 13 requisitos con el modelo; no asumir "regular" |
| Pesos \(W_i\), masas por nivel y alturas \(h_i\) | sí | bloquear |
| Tipo de diafragma (rígido o flexible, §2.7.1) | sí | verificarlo con el criterio de deflexión en el plano |
| Unidades | sí | SI coherente (N, m, kg, s, Pa); aceleraciones espectrales en \(g\), declaradas |

## Fundamento y formulación

### 1. Zonificación y peligro

La Ciudad de México se divide en tres zonas geotécnicas —I o Lomas, II o Transición, III o Lago— (NTC-Sismo 2020, §1.3). La edición 2020 **abandona la microzonificación por coeficientes zonales**: la demanda se obtiene del **SASID** (`https://sasid.unam.mx/webNormasCDMX/`) para el sitio específico (§3.1.1). La zona geotécnica sigue gobernando límites de aplicabilidad, separación de colindancias y requisitos de revisión. En la República, el MDOC/CFE regionaliza el peligro en **zonas A, B, C y D**, de menor a mayor intensidad; fuera de la Ciudad de México su espectro es el aplicable y no coincide con el del SASID.

> ⚠️ VERIFICAR: no se pudo leer la tabla de parámetros por zona y subzona (\(a_0\), \(c\), \(T_a\), \(T_b\), \(r\), factor de sitio) de la edición 2020 del MDOC/CFE, ni el detalle de las subzonas B1/B2, C1/C2 y D1–D4 de ediciones anteriores de la NTC. Se comprueba en el ejemplar oficial del MDOC/CFE 2020 (capítulo C.1.3, Diseño por Sismo) y en el mapa de regionalización vigente. Mientras tanto el programa **lee estas tablas de archivos de datos versionados** (`data/mexico-ntc/mdoc_zonas.json`) con campos `source` y `verified_on`; no se escriben en el código.

### 2. Espectro elástico de pseudo-aceleraciones

Ordenadas \(a\) como fracción de \(g\) en función del periodo \(T\) (s), con \(p=k+(1-k)(T_b/T)^{2}\) (NTC-Sismo 2020, ecs. 3.1.2 y 3.1.3):

$$a(T)=a_0+(\beta c-a_0)\frac{T}{T_a}\ (T<T_a);\qquad a(T)=\beta c\ (T_a\le T<T_b);\qquad a(T)=\beta c\,p\left(\frac{T_b}{T}\right)^{2}\ (T\ge T_b)$$

\(a_0\) = ordenada espectral en \(T=0\), aceleración máxima del terreno (en \(g\)); \(c\) = ordenada de la meseta espectral (adimensional, en \(g\)); \(T_a, T_b\) = periodos característicos de la meseta (s); \(k\) = cociente entre el desplazamiento máximo del suelo y el desplazamiento espectral máximo (adimensional); \(p\) = factor de modulación de la rama de periodo largo (ec. 3.1.3); \(\beta\) = factor de reducción por amortiguamiento suplementario, igual a 1 cuando \(\delta=0.05\) (ec. 3.1.4):

$$\beta=1-\left[1-\left(\tfrac{0.05}{\delta}\right)^{\lambda}\right]\frac{T}{T_a}\ (T\le T_a);\quad \beta=\left(\tfrac{0.05}{\delta}\right)^{\lambda}\ (T_a<T<\tau T_b);\quad \beta=1+\left[\left(\tfrac{0.05}{\delta}\right)^{\lambda}-1\right]\left(\frac{\tau T_b}{T}\right)^{\varepsilon}\ (T\ge\tau T_b)$$

\(\delta\) = fracción de amortiguamiento crítico del espectro. El espectro de diseño para prevención de colapso es \(a_d(T)=F_I\,a(T)/(Q'R)\). Tabla 3.1.1 de NTC-Sismo 2020 (§3.1.2), parámetros de la rama de periodo largo:

| \(T_s\) (s) | \(\lambda\) | \(\varepsilon\) | \(\tau\) |
|---|---|---|---|
| \(T_s\le 0.5\) | 0.40 | 0.80 | 2.50 |
| \(0.5<T_s\le 1.0\) | 0.45 | 0.20 | 1.00 |
| \(1.0<T_s\le 1.5\) | 0.45 | 0.30 | 1.00 |
| \(1.5<T_s\le 2.0\) | 0.50 | 1.20 | 1.00 |
| \(2.0<T_s\le 2.5\) | 0.50 | 1.80 | 1.00 |
| \(2.5<T_s\le 3.0\) | 0.55 | 3.00 | 1.00 |
| \(3.0<T_s\le 4.0\) | 0.50 | 4.00 | 1.00 |

Las ediciones anteriores a 2020 y el MDOC/CFE usan el exponente \(r\) en la rama descendente, \(a=c\,(T_b/T)^{r}\); **no** es intercambiable con el par \((k,p)\) de la ec. 3.1.2 y el programa debe declarar cuál formulación usó.

### 3. Reducción de ordenadas: \(Q'\), \(Q\), \(R\) y factor de importancia

Factor de reducción por comportamiento sísmico (ec. 3.4.1), con \(Q\) de las Tablas 4.2.1 y 4.2.2:

$$Q'=1+(Q-1)\frac{\beta T}{k\,T_a}\ (T\le T_a);\qquad Q'=1+(Q-1)\frac{\beta}{k}\ (T_a<T\le T_b);\qquad Q'=1+(Q-1)\frac{\beta p}{k}\ (T>T_b)$$

Factor de sobre-resistencia (ec. 3.5.1): \(R=k_1R_0+k_2\), con \(k_2=0.5\left[1-(T/T_a)^{1/2}\right]\ge 0\), \(R_0=2.0\) para mampostería y para sistemas de concreto, acero o compuestos a los que se asigne \(Q\ge 3\), y \(R_0=1.75\) cuando se asigne \(Q<3\). \(k_1=0.8\) con menos de tres crujías resistentes en la dirección de análisis y dos o menos en la normal; \(k_1=1.0\) con tres o más crujías en ambas direcciones y para mampostería; \(k_1=1.25\) para los sistemas duales de las Tablas 4.2.1 y 4.2.2. Se usa \(R=1\) cuando la resistencia lateral la aportan elementos distintos de los tabulados. Factores de importancia (§3.3): \(F_I=1.5\) para el Subgrupo A1, \(1.3\) para el A2 y \(1.0\) para el Grupo B.

Subconjunto verificado de las Tablas 4.2.1 (concreto) y 4.2.2 (acero y compuestas); el programa lee la tabla completa del archivo de datos:

| Sistema | Ductilidad | \(Q\) | \(\gamma_{max}\) |
|---|---|---|---|
| Marcos de concreto o de acero | alta / media / baja | 4.0 / 3.0 / 2.0 | 0.030 / 0.020 / 0.015 |
| Sistema dual marcos + muros o contravientos | alta / media / baja | 4.0 / 3.0 / 2.0 | 0.020 / 0.015 / 0.010 |
| Contravientos concéntricos que trabajan sólo en tensión | baja | 1.5 | 0.005 |
| Columnas de acero compactas en voladizo | media / baja | 1.5 / 1.0 | 0.012 / 0.009 |

Penalización por irregularidad (§5.5): \(Q'\) se multiplica por 0.8 si la estructura es irregular (§5.2) y por 0.7 si es muy irregular (§5.3), sin bajar de 1.0. En **planta baja débil o blanda** (§5.4) el primer entrepiso se diseña con \(Q'=1\) y su distorsión máxima no excede 0.006 (§5.5).

### 4. Métodos de análisis y límites

**Modal espectral** (cap. 6.1): válido en general, con modelo tridimensional elástico y modos hasta que la suma de pesos efectivos alcance 90 % del peso total en cada dirección. **Estático** (cap. 7.1): regulares de hasta 30 m e irregulares de hasta 20 m; en Zona I, 40 m y 30 m; prohibido para el Grupo A y para estructuras muy irregulares. **No lineal paso a paso** (cap. 6.2): obligatorio por encima de las alturas de la Tabla 2.1.1 —Zonas II y III: 120 m regular, 100 m irregular, 80 m muy irregular—. Pesos modales efectivos (ec. 6.1.1), con \(\{\phi_i\}\) el vector de amplitudes del modo \(i\), \([W]\) la matriz de pesos y \(\{J\}\) el vector de unos en los grados de libertad de traslación de la dirección de análisis:

$$W_{ei}=\frac{\left(\{\phi_i\}^{\mathsf T}[W]\{J\}\right)^{2}}{\{\phi_i\}^{\mathsf T}[W]\{\phi_i\}}$$

Combinación modal: SRSS (ec. 6.1.2) sólo si los periodos difieren al menos 10 % entre sí; en caso contrario CQC (ec. 6.1.3) con \(\rho_{ij}\) de la ec. 6.1.4. Cortante basal mínimo (§1.7 y §6.3): \(V_0/W_0\ge a_{min}\), con \(a_{min}=0.04/R\) si \(T_s<0.5\) s, \(0.06/R\) si \(T_s\ge 1.0\) s e interpolación lineal entre ambos; los desplazamientos **no** se corrigen por este incremento. La revisión se hace después de la combinación modal y antes del diseño de los elementos.

### 5. Torsión, segundo orden, bidireccional y asimetría

- **Excentricidad accidental** (ec. 2.2.3), en el entrepiso \(i\) de \(n\) pisos, medida perpendicularmente a la acción sísmica, con \(b_i\) la dimensión del piso en esa dirección (m): \(e_{a,i}=\left[0.05+0.05\,(i-1)/(n-1)\right]b_i\).
- **Momento torsionante de diseño** por elemento vertical: el más desfavorable de \(1.5e_s+e_a\) y \(e_s-e_a\) (ecs. 2.2.1 y 2.2.2), con \(e_s\) la excentricidad torsional; el factor 1.5 sólo aplica al análisis estático (en dinámico se toma 1.0). Momentos por nivel para la torsión accidental: \(M_{0i}=\pm\left(M_{ai}-M_{a(i+1)}\right)\) con \(M_{ai}=V_i\,e_{a,i}\) (ec. 2.2.4).
- **Segundo orden** (ec. 2.3.1): pueden despreciarse en los entrepisos donde la distorsión de prevención de colapso no exceda \(0.08\,V_i/W_p\), con \(V_i\) el cortante de diseño del entrepiso y \(W_p\) el peso de la parte superior **sin** factor de carga.
- **Bidireccional** (§2.4): 100 % de una componente más 30 % de la ortogonal, con los signos más desfavorables. **Asimetría en fluencia** (§2.5): \(F_a\) de las ecs. 2.5.1 y 2.5.2 divide los factores de resistencia del material, con \(\alpha_{sd}=\left(V_b^{f}-V_b^{d}\right)/(2W_0)\) (ec. 2.5.3) y los parámetros de la Tabla 2.5.1.

### 6. Distorsiones, estados límite y regularidad

La distorsión de entrepiso es \(\gamma=\Delta u/h_{ei}\). La sección 1.8 exige dos revisiones: (1) **prevención de colapso**, donde las distorsiones del análisis con el espectro de diseño multiplicadas por \(QR\) no deben exceder \(\gamma_{max}\) de las Tablas 4.2.1, 4.2.2 o 4.2.3; y (2) **limitación de daños**, con distorsiones \(\le 0.002\), o \(\le 0.004\) si todos los elementos no estructurales toleran deformaciones apreciables o están separados de la estructura. Estas últimas se obtienen del análisis con el espectro reducido y el factor \(K_s\) (ec. 3.1.1): \(K_s=1/6\) si \(T_s<0.5\) s; \(K_s=1/[6-4(T_s-0.5)]\) si \(0.5\le T_s<1.0\) s; \(K_s=1/4\) si \(T_s\ge 1.0\) s. Separación con colindancias (§1.9): no menor de 50 mm ni del desplazamiento lateral de prevención de colapso; si no se modela giro ni corrimiento de la base, el desplazamiento se aumenta en \(0.003\) (Zona II) o \(0.006\) (Zona III) veces la altura sobre el terreno.

Regularidad (§5.1): 13 requisitos con umbrales numéricos —paralelismo dentro de 15°, esbeltez y relación largo/ancho \(\le 4\), entrantes y salientes \(\le 20\,\%\), aberturas \(\le 20\,\%\) del área, peso de nivel \(\le 120\,\%\), dimensión en planta \(\le 110\,\%\) de la del piso inferior, columnas restringidas en todos los pisos, altura de columnas constante, rigidez de entrepiso con diferencia \(\le 20\,\%\), desplazamiento lateral de algún punto \(\le 1.2\) veces el promedio de los extremos y cociente capacidad/demanda \(\ge 0.8\) cuando se diseñe con \(Q=4\)—. Es **irregular** si incumple los requisitos 5, 6, 9, 10, 11, 12 o 13, o dos o más de los 1, 2, 3, 4, 7 y 8; es **muy irregular** si incumple dos o más de los 5, 6, 9, 10, 11, 12 y 13, o si el desplazamiento de un punto excede 30 % el promedio, o si la rigidez o resistencia de un entrepiso excede 40 % la del inferior, o si más de 30 % de las columnas incumplen el requisito 9.

### 7. Método estático

Fuerzas laterales (ec. 7.2.1), con \(W_i\) el peso del nivel \(i\) (N) y \(h_i\) su altura sobre el desplante (m): \(F_i=\dfrac{c}{Q'R}\cdot\dfrac{W_i h_i}{\sum_j W_j h_j}\cdot\sum_j W_j\), con \(V_0/W_0=c/(Q'R)\) y además \(V_0/W_0\ge a_0/R\). \(Q'\) se evalúa con la ec. 3.4.1 en el intervalo \(T_a\le T\le T_b\), y \(c\) se obtiene del SASID. Periodo fundamental aproximado (ec. 7.3.1): \(T=2\pi\sqrt{\sum_i W_iX_i^{2}/\left(g\sum_i F_iX_i\right)}\), con \(X_i\) el desplazamiento del nivel \(i\) relativo al desplante en la dirección de la fuerza y \(g=9.80665\ \text{m/s}^{2}\). Si \(T>T_b\), las fuerzas se reparten con \(F_i=W_i\left(k_3h_i+k_4h_i^{2}\right)a/(Q'R)\) (ec. 7.3.2), con \(k_3=p\,\Sigma W_i/\Sigma W_ih_i\) (ec. 7.3.3) y \(k_4=1.5(1-p)\,\Sigma W_i/\Sigma W_ih_i^{2}\) (ec. 7.3.4), y \(a\ge a_0\).

## Procedimiento

1. Localizar el predio y resolver la zona geotécnica (§1.3) y el cuerpo normativo aplicable: NTC-Sismo 2020 en la Ciudad de México, MDOC/CFE en el resto de la República. Registrar la fuente.
2. Obtener del SASID, o del archivo de datos de zona, los parámetros \(a_0, c, T_a, T_b, k, T_s\) y el espectro elástico del sitio. Si \(T_s\) medido en el estudio geotécnico difiere más de 25 % del del SASID, aplica el estudio específico del Apéndice A (§3.1.3).
3. Clasificar la estructura en Grupo A1, A2 o B (§1.4) y fijar \(F_I\) (§3.3).
4. Elegir el sistema estructural y la clase de ductilidad; leer \(Q\) y \(\gamma_{max}\) de la Tabla 4.2.1 o 4.2.2 desde el archivo de datos.
5. Calcular \(R\) con la ec. 3.5.1 a partir de \(k_1\) (crujías y dualidad) y \(R_0\).
6. Evaluar los 13 requisitos de §5.1 y clasificar la estructura como regular, irregular, muy irregular o de planta baja débil; aplicar la penalización a \(Q'\) (§5.5).
7. Seleccionar el método de análisis con §2.1 y la Tabla 2.1.1; comprobar los límites de altura del método estático (§7.1).
8. Construir \(a_d(T)=F_I\,a(T)/(Q'R)\) y verificar \(a(0)=a_0\), la continuidad en \(T_a\), \(T_b\) y \(\tau T_b\), y la monotonía de la rama descendente.
9. Analizar (estático o modal espectral con los modos del 90 % de peso efectivo), combinar con SRSS o CQC y aplicar la torsión accidental.
10. Aplicar el cortante basal mínimo (§§1.7 y 6.3), la torsión de diseño, los efectos bidireccionales (§2.4), \(F_a\) si hay asimetría en fluencia (§2.5) y el incremento de 25 % por concentración de sismo-resistencia (§5.6).
11. Revisar las distorsiones de los dos estados límite (§1.8), los efectos de segundo orden (§2.3) y la separación de colindancias (§1.9).
12. Emitir el informe con trazabilidad completa y advertencias activas.

## Implementación en la plataforma

```python
# opensees_studio/core/codes/mexico_ntc.py   (core puro: sin Qt, sin openseespy)
def elastic_spectrum(params: NtcSpectrumParams, T: float) -> float:
    """a(T) en g, ecs. 3.1.2 a 3.1.4. params trae a0, c, Ta, Tb, k, Ts, delta."""
def beta_damping(T: float, delta: float, ts: float, params: NtcSpectrumParams) -> float:
    """Beta de amortiguamiento (ec. 3.1.4) con lambda/epsilon/tau de la Tabla 3.1.1."""
def q_reduction(T: float, q: float, params: NtcSpectrumParams, irregularity: str) -> float:
    """Q' de la ec. 3.4.1 con la penalizacion 0.8/0.7 de la seccion 5.5, nunca menor que 1."""
def overstrength(T: float, q: float, n_bays: tuple[int, int], dual: bool, params) -> float:
    """R de la ec. 3.5.1: R0, k1 y k2 con las reglas de la seccion 3.5."""
def accidental_eccentricity(i: int, n: int, b_i: float) -> float:
    """ea,i de la ec. 2.2.3, en m."""
def static_forces(levels: Sequence[Level], params, q_prime: float, r: float) -> list[float]:
    """Fi de la ec. 7.2.1 y, si T > Tb, de las ecs. 7.3.2 a 7.3.4. Fuerzas en N."""
def drift_check(drifts, gamma_max, q, r, ks, limit_service) -> DriftReport:
    """Revision de las secciones 1.8 y 3.1.1 para los dos estados limite."""
def effective_modal_weight(phi: np.ndarray, w: np.ndarray, direction: int) -> float:
    """Wei de la ec. 6.1.1; direction selecciona el vector J."""
```

Reglas de arquitectura:

- El módulo vive en `core/codes/` y **no** importa Qt ni OpenSeesPy; espectro, \(Q'\), \(R\), \(e_a\), fuerzas estáticas y revisiones son funciones puras con prueba unitaria.
- Los coeficientes normativos viven en `data/mexico-ntc/*.json` con campos `value`, `source` (norma, edición, sección o tabla) y `verified_on`: `q_gamma_max.json`, `tabla_3_1_1.json`, `mdoc_zonas.json`, `factores_carga.json`. Nunca dentro de la lógica.
- La consulta al SASID es E/S de red y vive en `services/sasid_client.py` (sin Qt), que devuelve una `SiteSpectrum` de `core/`; el núcleo nunca abre un socket y las pruebas usan un archivo grabado.
- El `Project` guarda solo referencias (zona, grupo, sistema, ductilidad y ruta al archivo de espectro); el número de crujías se cuenta del modelo para \(k_1\), no se teclea.
- Errores que debe lanzar: `MissingSiteSpectrum` sin SASID ni archivo; `UnsupportedSystem` si el sistema no está en la tabla; `MethodNotAllowed` si el método excede §2.1 o §7.1; `MissingIrregularitySurvey` si no se evaluaron los 13 requisitos.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Espectro \(a(T)\), \(p=k+(1-k)(T_b/T)^{2}\), \(\beta\) y Tabla 3.1.1 | NTC-Sismo 2020, ecs. 3.1.2 a 3.1.4 | sí |
| \(Q'\) (ec. 3.4.1); \(R=k_1R_0+k_2\) (ec. 3.5.1) | NTC-Sismo 2020, §§3.4 y 3.5 | sí |
| \(F_I=1.5\) (A1), 1.3 (A2), 1.0 (B) | NTC-Sismo 2020, §3.3 | sí |
| \(e_{a,i}\), \(1.5e_s+e_a\), \(e_s-e_a\), \(M_{0i}\) | NTC-Sismo 2020, ecs. 2.2.1 a 2.2.4 | sí |
| Umbral de segundo orden \(0.08V_i/W_p\) | NTC-Sismo 2020, ec. 2.3.1 | sí |
| \(a_{min}=0.04/R\) (\(T_s<0.5\) s), \(0.06/R\) (\(T_s\ge 1\) s) y \(K_s\) | NTC-Sismo 2020, §§1.7 y 3.1.1 | sí |
| Distorsión de limitación de daños 0.002 / 0.004 | NTC-Sismo 2020, §1.8 | sí |
| \(Q\) y \(\gamma_{max}\) de concreto y de acero | NTC-Sismo 2020, Tablas 4.2.1 y 4.2.2 | parcial: subconjunto |
| Penalización de \(Q'\) 0.8 / 0.7 y \(Q'=1\) en planta baja débil | NTC-Sismo 2020, §§5.4 y 5.5 | sí |
| Alturas 120/100/80 m y límites del método estático 30/20 m (40/30 m en Zona I) | NTC-Sismo 2020, Tabla 2.1.1 y §7.1 | sí |
| Tablas por zona A–D y subzonas del MDOC/CFE 2020 | MDOC/CFE 2020, cap. C.1.3 | no — `VERIFICAR` |
| Factores de carga de las NTC-Criterios y Acciones y factores de resistencia del material | NTC-Criterios y Acciones 2020; NTC de concreto y de acero 2020 | no — `VERIFICAR` |

> ⚠️ VERIFICAR: los factores de carga de las combinaciones que incluyen acciones accidentales y los factores de resistencia de las NTC de concreto y de acero vigentes no se pudieron confirmar contra la edición 2020 publicada; la copia consultada corresponde a la edición anterior. Se comprueban en las NTC sobre Criterios y Acciones para el Diseño Estructural de las Edificaciones (2020) y en las NTC del material. El programa debe leerlos de `data/mexico-ntc/factores_carga.json` y `data/mexico-ntc/factores_resistencia.json`.

> ⚠️ VERIFICAR: la malla de periodos y los parámetros por sitio del SASID los sirve una aplicación web; no se transcriben. El programa debe consumir el archivo de espectro descargado y versionado del sitio, con su fecha de consulta.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Rama ascendente | \(a_0=0.10,\ c=0.40,\ T_a=0.6,\ T_b=2.0,\ \beta=1,\ T=0.3\) s | \(a=0.25\,g\) | 1e-9 |
| Meseta | los mismos datos, \(T=1.0\) s | \(a=0.40\,g\) | 1e-9 |
| Rama de periodo largo | \(k=0.5,\ T=4.0\) s | \(p=0.625\), \(a=0.0625\,g\) | 1e-9 |
| Continuidad y \(\beta\) | \(T=T_a\) y \(T=T_b\) por ambos lados; \(\delta=0.05\) | salto nulo; \(\beta=1\) en todo \(T\) | 1e-9 |
| \(Q'\) con \(T\le T_a\) | \(Q=4,\ \beta=1,\ k=0.5,\ T=0.3,\ T_a=0.6\) | \(Q'=4.0\) | 1e-9 |
| \(Q'\) con \(T_a<T\le T_b\) | \(Q=4,\ \beta=1,\ k=0.5\) | \(Q'=7.0\) (\(>Q\), permitido por §3.4) | 1e-9 |
| \(Q'\) con \(T>T_b\) | \(Q=4,\ \beta=1,\ k=0.5,\ T=4,\ T_b=2\) | \(Q'=4.75\) | 1e-9 |
| \(R\) | \(Q=4,\ k_1=1.0,\ R_0=2.0,\ T/T_a=0.25\) | \(R=2.25\); dual (\(k_1=1.25\)): 2.75 | 1e-9 |
| \(e_a\) | \(n=10,\ b=20\) m, \(i=1\) e \(i=10\) | 1.0 m y 2.0 m | 1e-9 |
| \(a_{min}\) | \(T_s=0.3,\ R=2.25\) | 0.017778 | 1e-9 |
| \(K_s\) | \(T_s=0.3;\ T_s=1.0;\ T_s=1.5\) | 0.166667; 0.25; 0.25 | 1e-9 |
| Fuerzas estáticas | \(c=0.40,\ Q'=2,\ R=2.25,\ W_1=W_2=1.0\) MN, \(h_1=3,\ h_2=6\) m | \(F_1=59.26\) kN, \(F_2=118.52\) kN, \(V_0=177.78\) kN | 0.1 % |
| Periodo aproximado | ec. 7.3.1 con \(X_i\) de un análisis estático | \(T=\sqrt{\sum W_iX_i^{2}/(g\sum F_iX_i)}\) | 1e-6 s |
| Pesos efectivos | modelo de 3 GDL, ec. 6.1.1 | \(\sum_e W_{ei}=W_{tot}\) en la dirección | 0.1 % absoluto |
| Distorsiones | modelo resuelto, \(\gamma=\Delta u/h_{ei}\) | valor a mano del pórtico | 1 % relativo |
| Deriva de colapso | \(\gamma_{max}=0.020,\ Q=4,\ R=2.25\) | \(QR\gamma\) contra 0.020 | 1e-9 |

Además: contraste obligatorio del espectro generado contra el que entrega el SASID para el mismo predio (mismos \(a_0, c, T_a, T_b, k, T_s\)) y contra al menos un ejemplo resuelto de las NTC o del MDOC/CFE.

## Errores frecuentes y trampas

1. **Usar las tablas zonales de la edición 2004/2017 con las NTC 2020.** La edición vigente en la Ciudad de México exige el espectro del SASID; sustituir \(a_0, c, T_a, T_b\) por valores de zona produce demandas que no corresponden.
2. **Intercambiar \(R\) y \(Q\).** Las fuerzas se dividen entre \(Q'R\), mientras que la distorsión de prevención de colapso se multiplica por \(QR\) (§1.8); usar \(Q\) en vez de \(Q'\) en las fuerzas duplica la corrección.
3. **Suponer \(Q'=Q\).** Con \(k<1\) (suelo blando) el cociente \(\beta p/k\) hace \(Q'>Q\); el caso \(Q'=7\) con \(Q=4\) es legítimo y no un error del programa.
4. **Olvidar \(p\) en la rama \(T\ge T_b\)** y reemplazar el par \((k,p)\) por el exponente \(r\) de la edición anterior: cambia la ordenada de periodo largo, el cortante de los edificios altos y el \(a_{min}\).
5. **Mezclar \(g\) con m/s².** \(a_0\) y \(c\) son fracciones de \(g\); las masas y \(W_i\) entran al solver en kg y N. Convertir una sola vez y en un único punto del flujo.
6. **Calcular \(e_a\) constante en altura.** La ec. 2.2.3 crece de \(0.05b\) en el primer nivel a \(0.10b\) en el último; usar un solo valor subestima el nivel crítico.
7. **Aplicar el 1.5 de la ec. 2.2.1 en análisis dinámico.** Ese factor aproxima el paso de estático a dinámico y vale 1.0 cuando el análisis ya es dinámico.
8. **Corregir desplazamientos por el cortante basal mínimo.** §1.7 indica que se incrementan las fuerzas de diseño, no los desplazamientos.
9. **Evaluar \(Q'\) con el periodo del modo en el método estático.** La ec. 7.2.1 exige \(Q'\) calculado para \(T_a\le T\le T_b\).
10. **Incluir la carga viva completa en el peso sísmico.** El peso que entra en masas y en \(W_p\) es sin factor de carga y con la fracción de carga viva de las NTC-Criterios y Acciones.
11. **Leer \(\gamma_{max}\) de la fila equivocada de la Tabla 4.2.1 o 4.2.2.** Depende del sistema, de la clase de ductilidad y, en sistemas duales, de la relación de aspecto de muros o contravientos (la nota 4 de la Tabla 4.2.2 incrementa \(\gamma_{max}\) en 0.005).
12. **Confundir irregular con muy irregular.** La penalización es 0.8 contra 0.7 y el límite de altura para el análisis no lineal cambia (100 m contra 80 m).

## Interfaz de salida

El programa debe reportar, por dirección de análisis y por estado límite:

- Zona geotécnica, cuerpo normativo aplicable, edición, ruta y fecha de consulta del archivo de espectro del sitio.
- \(a_0, c, T_a, T_b, k, T_s, \delta, \beta\), cada uno con la sección que lo define.
- \(F_I\), \(Q\), \(Q'\) con la penalización aplicada y su motivo, \(k_1, R_0, k_2, R\), y el sistema estructural con la cita de la tabla.
- Método de análisis y comprobación de sus límites (§2.1, §7.1 y Tabla 2.1.1), con número de modos y suma de pesos efectivos; \(V_0/W_0\), \(a_{min}\) y si se aplicó el incremento.
- Distorsiones por entrepiso, \(\gamma_{max}\), la comparación \(QR\gamma\) y el veredicto de ambos estados límite con el artículo aplicable.
- \(e_{a,i}\) por nivel, el momento torsionante de diseño y los elementos que gobiernan; avisos de segundo orden y de separación de colindancias.
- Advertencias activas, incluidos los `VERIFICAR` abiertos y los datos leídos de archivos no verificados.

## Referencias

1. NTC para Diseño por Sismo, Reglamento de Construcciones para el Distrito Federal, Gaceta Oficial de la Ciudad de México, 9 de junio de 2020 (con comentarios). Capítulos 1 a 8 y Apéndice A.
2. NTC para el Diseño y Construcción de Estructuras de Concreto, RCDF, edición 2020 (con comentarios).
3. NTC para el Diseño y Construcción de Estructuras de Acero, RCDF, edición 2020 (con comentarios).
4. NTC sobre Criterios y Acciones para el Diseño Estructural de las Edificaciones, RCDF, edición 2020.
5. NTC para el Diseño y Construcción de Cimentaciones, RCDF, edición 2020 (zonificación geotécnica de la Ciudad de México).
6. Reglamento de Construcciones para el Distrito Federal, Artículo 139 (grupos y subgrupos de las construcciones).
7. CFE, *Manual de Diseño de Obras Civiles, Diseño por Sismo*, Comisión Federal de Electricidad, edición 2020, capítulo C.1.3 — regionalización sísmica de la República Mexicana y espectros de diseño.
8. SASID, *Sistema de Acciones Sísmicas de Diseño*, UNAM–SMIE, `https://sasid.unam.mx/webNormasCDMX/` — espectros elásticos y de diseño y acelerogramas por sitio.
9. Ordaz, M. y Pérez-Rocha, L. E. (1998), *Estimation of strength-reduction factors for elastoplastic systems*, Earthquake Engineering and Structural Dynamics — origen de la forma de \(Q'\) (comentario C-3.4.1).

## Registro de verificación

- **Verificado** contra el texto publicado de las NTC-Sismo 2020 (Gaceta Oficial de la Ciudad de México, 9 de junio de 2020): zonificación geotécnica (§1.3); espectro de las ecs. 3.1.2 a 3.1.4 y Tabla 3.1.1; \(Q'\) (ec. 3.4.1); \(R\) (ec. 3.5.1) con \(R_0\), \(k_1\) y \(k_2\); factores de importancia (§3.3); torsión accidental y sus momentos (ecs. 2.2.1 a 2.2.4); umbral de segundo orden (ec. 2.3.1); \(a_{min}\) (§1.7); \(K_s\) (ec. 3.1.1); distorsiones (§1.8); separación de colindancias (§1.9); Tablas 4.2.1 y 4.2.2 (subconjunto); regularidad (§§5.1 a 5.6); análisis modal (§6.1); límites de altura (Tabla 2.1.1); método estático (§§7.1 a 7.3).
- **Pendiente**: tabla de parámetros por zona y subzona del MDOC/CFE 2020; factores de carga de las NTC-Criterios y Acciones 2020; factores de resistencia y resistencias esperadas de las NTC de concreto y de acero 2020; confirmación con la tabla publicada del SASID de los extremos de la interpolación lineal de \(a_{min}\) entre \(T_s=0.5\) y \(1.0\) s.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia oficial de las NTC 2020 de la Gaceta Oficial de la Ciudad de México y del MDOC/CFE 2020. Próxima revisión: al publicarse una actualización de las NTC o del MDOC.
