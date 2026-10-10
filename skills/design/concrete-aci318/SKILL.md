---
name: concrete-aci318
description: >-
  Diseña y revisa elementos de concreto reforzado conforme a ACI 318-19: diseño por resistencia y factores de reducción phi; flexión (cuantías balanceada, mínima y máxima; sección rectangular y T); cortante con el efecto de la cuantía de acero y de la carga axial; torsión; columnas con diagrama de interacción P-M, esbeltez y magnificación de momentos; losas en una y dos direcciones; zapatas; adherencia, longitud de desarrollo, anclajes y empalmes; y requisitos sismorresistentes de los sistemas especiales, intermedios y ordinarios a momento. Úsala cuando el proyecto declare ACI 318-19, cuando haya que convertir demandas del solver en relaciones demanda/capacidad por sección y combinación, o cuando se audite el módulo de diseño de concreto.
metadata:
  track: design
  jurisdiction: USA
  edition: "ACI 318-19"
  status: draft
  verified_on: "2026-02-14"
  scope: [design, qa]
---

# ACI 318-19 — Diseño y revisión de concreto reforzado

## Cuándo usar esta skill
- El proyecto declara `code = ACI 318-19` (o IBC 2024, que lo adopta) y el material de la sección es concreto reforzado con barras corrugadas.
- Hay que convertir envolventes de demanda del solver (\(M_u\), \(V_u\), \(T_u\), \(P_u\); N·m y N) en comprobaciones \(\phi R_n \ge R_u\) y relaciones \(D/C\).
- Hay que dimensionar o revisar armadura: cuantía mínima y máxima, estribos, confinamiento, longitud de desarrollo, ganchos y empalmes.
- Hay que verificar el detallado sismorresistente de un pórtico a momento (especial, intermedio u ordinario), de un muro estructural o de un nudo viga-columna.
- Síntomas típicos en código existente: \(\phi = 0.90\) constante, límite \(\varepsilon_t \ge 0.005\) de ACI 318-14, \(V_c\) sin el factor de tamaño \(\lambda_s\), o \(f'_c\) capturado en kg/cm².
- **No usar** para acero estructural (→ `design/steel-aisc360-341`), suelo, capacidad de carga y pilotes (→ `design/foundations-and-soil-structure`), peligro sísmico, \(R\), \(C_d\), \(\Omega_0\), SDC y combinaciones de carga (→ `codes/asce7-22-seismic-design`, `seismic/load-combinations-and-limit-states`), mampostería, madera, presforzado con pérdidas dependientes del tiempo ni evaluación por desempeño (ASCE 41).

## Alcance y límites
Cubre los capítulos 6 (análisis), 7–8 (losas), 9 (vigas), 10–16 (cortante en losas, zapatas, muros y diafragmas), 17 (anclaje al concreto), 18 (sismorresistente), 19–20 (materiales), 21 (\(\phi\)), 22 (resistencia de elementos) y 25 (detallado del refuerzo) de ACI 318-19.
Supuestos de partida: concreto de peso normal salvo declaración explícita (\(\lambda \ne 1\)); barras corrugadas de grado 420 MPa salvo declaración; análisis elástico lineal con diafragma rígido; demandas ya factorizadas por LRFD según `seismic/load-combinations-and-limit-states`.
**No cubre**: pérdidas dependientes del tiempo en presforzado, concreto reforzado con fibras, losas sobre terreno con criterios de pavimento, empalmes soldados o mecánicos sin certificación del dispositivo, ni la evaluación sísmica por desempeño de edificios existentes.

## Entradas y supuestos
Todos los datos son obligatorios dentro de su bloque: si falta uno, el motor devuelve `NOT_VERIFIED` con la razón en lugar de un valor por defecto.

| Dato | Unidad | Si falta |
|---|---|---|
| \(f'_c\), tipo de concreto (\(\lambda\)) y peso específico | Pa, — | bloquear el bloque completo |
| \(f_y\), \(f_{yt}\), diámetro, grado y superficie de la barra | Pa, m | bloquear |
| Geometría: \(b_w\), \(h\), \(d\), \(d'\), recubrimiento libre | m | bloquear |
| Armadura dispuesta: número, diámetro, capas, \(s\), número de ramas | —, m | bloquear; no se asume |
| Envolventes \(P_u, M_u, V_u, T_u\) por combinación | N, N·m | bloquear |
| Sistema resistente (SMF/IMF/OMF/muro) y SDC | — | bloquear solo el detallado del cap. 18 |
| Luces y luces libres \(\ell\), \(\ell_n\); \(M_1/M_2\); \(k\ell_u\) | m, — | bloquear esbeltez y losas |
| Condiciones de adherencia: \(\psi_t,\psi_e,\psi_s,\psi_g\), \(c_b\), \(A_{tr}\), \(s\), \(n\) | —, m | bloquear anclajes; nunca 1.0 por defecto |
| Carga sostenida para \(\beta_{dns}\) | N | bloquear magnificación; no usar 0 |
| Tablas de \(\phi\), cortante, torsión, losas y detallado sísmico | — | leer de `data/usa/aci318/*.json` |

Unidades: la interfaz pública trabaja en **N y m** (SI coherente, tensiones en Pa). El núcleo de ACI trabaja internamente en **N y mm** con \(f'_c\) en MPa, porque las constantes empíricas están calibradas en esas unidades; la conversión es única, centralizada y con prueba unitaria. Nunca se acepta \(f'_c\) en kg/cm² ni en psi.

## Fundamento y formulación
### 1. Formato de comprobación
$$\phi R_n \ge R_u, \qquad D/C = \frac{\lvert R_u \rvert}{\phi R_n} \le 1.0$$
\(R_u\) = resistencia requerida de la combinación gobernante (N o N·m); \(R_n\) = resistencia nominal del mismo tipo; \(\phi\) = factor de reducción de ACI 318-19, Tabla 21.2.1 (\(\phi = 0.90\) flexión, 0.75 cortante y torsión, 0.65 compresión con estribos, 0.75 con espiral, 0.65 aplastamiento). \(D/C\) se evalúa por sección, combinación y componente, y se reporta la envolvente.

### 2. Flexión
Hipótesis: secciones planas, \(\varepsilon_{cu} = 0.003\) en la fibra extrema a compresión y bloque rectangular equivalente de intensidad \(0.85f'_c\) con \(a = \beta_1 c\) (ACI 318-19, §22.2.2.1 y §22.2.2.4.3).
$$\beta_1 = 0.85 \ \ (f'_c \le 28\ \text{MPa}), \qquad \beta_1 = 0.85 - 0.05\frac{f'_c - 28}{7} \ge 0.65 \ \ (f'_c > 28\ \text{MPa})$$
$$C_c = 0.85 f'_c\, a\, b_w, \qquad T = A_s f_y, \qquad a = \frac{A_s f_y}{0.85 f'_c b_w}, \qquad M_n = A_s f_y \left(d - \frac{a}{2}\right)\ \text{[N·mm]}$$
\(C_c, T\) en N; \(a, c, d, b_w\) en mm; \(f'_c, f_y\) en MPa; \(A_s\) en mm². Con \(\varepsilon_{ty} = f_y/E_s\), \(E_s = 200\,000\) MPa, la cuantía balanceada es \(\rho_b = 0.85\beta_1 (f'_c/f_y)\,\varepsilon_{cu}/(\varepsilon_{cu}+\varepsilon_{ty})\), y con \(\rho = A_s/(b_w d)\):
$$\rho_{max} = 0.85\beta_1\frac{f'_c}{f_y}\frac{0.003}{0.003 + \varepsilon_{ty} + 0.003}, \qquad A_{s,min} = \max\!\left(\frac{0.25\sqrt{f'_c}}{f_y},\ \frac{1.4}{f_y}\right) b_w d$$
ACI 318-19 **eliminó** \(\rho \le 0.75\rho_b\): el techo lo fija \(\varepsilon_t \ge \varepsilon_{ty} + 0.003\) para poder usar \(\phi = 0.90\) (ACI 318-19, Tabla 21.2.2); para grado 420 MPa (\(\varepsilon_{ty} = 0.0021\)) eso es \(\varepsilon_t \ge 0.0051\), no \(0.005\) de 318-14. \(\sqrt{f'_c}\) va en MPa y \(A_{s,min}\) en mm² (ACI 318-19, §9.6.1.2).
Acero a compresión: si \(A_s > \rho_{max} b_w d\), la compresión adicional se equilibra con \(A'_s\), \(f'_s = E_s\varepsilon_{cu}(c-d')/c \le f_y\) y
$$M_n = (A_s f_y - A'_s f'_s)\left(d - \frac{a}{2}\right) + A'_s f'_s (d - d')$$
El modelo de dos capas exige \(a \ge 2d'\); si no se cumple, se resuelve por compatibilidad de fibras. Sección T (ala en compresión): se calcula como rectangular de ancho efectivo \(b\) y, si \(a > h_f\), se descuenta el ala:
$$M_n = 0.85 f'_c (b - b_w) h_f \left(d - \frac{h_f}{2}\right) + 0.85 f'_c b_w a \left(d - \frac{a}{2}\right)$$
con \(b\) limitado por \(8h_f\) a cada lado del alma, la mitad de la distancia libre al alma vecina y \(\ell_n/8\) (\(\ell_n/12\) con ala a un solo lado) (ACI 318-19, Tabla 6.3.2.1; \(h_f\) en mm).

### 3. Cortante
ACI 318-19 reorganizó §22.5: \(V_c\) depende de \(A_v\) frente a \(A_{v,min}\), de \(\rho_w\) y de la carga axial. Para miembros sin presfuerzo, con \(\rho_w = A_s/(b_w d)\), \(N_u > 0\) en compresión, \(d\) en mm y \(f'_c\) en MPa (ACI 318-19, Tabla 22.5.5.1):

| Caso | \(V_c\) [N] |
|---|---|
| \(A_v \ge A_{v,min}\), alternativa (a) | \(\left(0.17\lambda\sqrt{f'_c} + \dfrac{N_u}{6A_g}\right) b_w d\) |
| \(A_v \ge A_{v,min}\), alternativa (b) | \(\left(0.66\lambda\,\rho_w^{1/3}\sqrt{f'_c} + \dfrac{N_u}{6A_g}\right) b_w d\) |
| \(A_v < A_{v,min}\), única válida (c) | \(\left(0.66\lambda_s\lambda\,\rho_w^{1/3}\sqrt{f'_c} + \dfrac{N_u}{6A_g}\right) b_w d\) |

$$\lambda_s = \sqrt{\frac{2}{1 + d/250}} \le 1.0, \qquad A_{v,min} = \max\!\left(0.062\sqrt{f'_c},\ 0.35\right)\frac{b_w s}{f_{yt}}, \qquad V_s = \frac{A_v f_{yt} d}{s}$$
\(A_g = b_w h\) en mm²; \(A_v\), \(A_{v,min}\) en mm²; \(s\) en mm; \(f_{yt}\) en MPa; \(N_u\) en N (negativo en tracción, y reduce \(V_c\)). Límites: \(V_c \le 0.42\lambda\sqrt{f'_c}\,b_w d\) y \(V_s \le 0.66\sqrt{f'_c}\,b_w d\), de donde \(V_u \le \phi(V_c + 0.66\sqrt{f'_c}b_w d)\) con \(\phi = 0.75\) (ACI 318-19, §22.5.1.2). Espaciamiento: \(s \le \min(d/2,\ 600\ \text{mm})\) y, si \(V_s > 0.33\sqrt{f'_c}b_w d\), \(s \le \min(d/4,\ 300\ \text{mm})\) (ACI 318-19, §9.7.6.2.2).

### 4. Torsión
Umbral de negligencia y de fisuración, con \(A_{cp}\) en mm², \(P_{cp}\) en mm, \(f'_c\) en MPa y resultado en N·mm (ACI 318-19, §22.7.4.1 y §22.7.5.1):
$$T_{th} = 0.083\lambda\sqrt{f'_c}\,\frac{A_{cp}^2}{P_{cp}}, \qquad T_{cr} = 0.33\lambda\sqrt{f'_c}\,\frac{A_{cp}^2}{P_{cp}}$$
Se desprecia la torsión si \(T_u < \phi T_{th}\); si \(T_u \ge \phi T_{th}\) se provee refuerzo y debe cumplirse \(T_u \le \phi T_n\). Con \(A_o = 0.85 A_{oh}\), \(p_h\) el perímetro del estribo cerrado y \(\theta = 45^\circ\) (no presforzado) o \(37.5^\circ\) (presforzado):
$$T_n = \frac{2 A_o A_t f_{yt} \cot\theta}{s}, \qquad A_{l,min} = 0.42\sqrt{f'_c}\,\frac{A_{cp}}{f_{yl}} - \frac{A_t}{s}\,p_h\frac{f_{yt}}{f_{yl}}$$
\(A_t\) = área de una rama del estribo de torsión (mm²); \(A_l\) = refuerzo longitudinal total (mm²), distribuido dentro de \(0.85A_{oh}\). Interacción con cortante (ACI 318-19, §22.7.7.1): la sección se dimensiona para \(V_u/V_n + T_u/T_n \le 1\) con las mismas \(A_t\) y \(\theta\).

> ⚠️ VERIFICAR: la forma exacta de la interacción cortante–torsión de §22.7.7.1 (lineal frente a raíz cuadrada), las condiciones de aplicabilidad de las alternativas (b) y (c) de la Tabla 22.5.5.1 (límite superior de \(\sqrt{f'_c}\), secciones circulares) y el tratamiento de \(N_u\) en tracción no se contrastaron con la edición oficial. Se comprueban en ACI 318-19, cap. 22 impreso, y se transcriben a `data/usa/aci318/torsion.json` y `shear.json`; el motor **no** codifica esos criterios.

### 5. Columnas: P-M, esbeltez y magnificación
$$P_o = 0.85 f'_c (A_g - A_{st}) + f_y A_{st}, \qquad P_{n,max} = 0.80 P_o\ (\text{estribos}), \qquad 0.85 P_o\ (\text{espiral})$$
\(P_o\) en N; \(A_{st}\) en mm² (ACI 318-19, §22.4.2). El diagrama de interacción se construye por compatibilidad de fibras variando \(c\) desde tracción pura hasta \(P_{n,max}\), con \(\phi\) **interpolado a lo largo de la superficie**: 0.65 (estribos) o 0.75 (espiral) en la zona controlada por compresión, 0.90 cuando \(\varepsilon_t \ge \varepsilon_{ty} + 0.003\), e interpolación lineal entre \(\varepsilon_{ty}\) y \(\varepsilon_{ty}+0.003\) (ACI 318-19, Tabla 21.2.2). El punto balanceado usa \(c_b = \varepsilon_{cu}d/(\varepsilon_{cu}+\varepsilon_{ty})\).
Esbeltez (ACI 318-19, §6.2.5): se desprecian los efectos de segundo orden si \(k\ell_u/r \le 22\) en columnas que contribuyen a la estabilidad lateral, o si \(k\ell_u/r \le 34 + 12(M_1/M_2) \le 40\) en columnas arriostradas contra desplazamiento lateral, con \(M_1/M_2 > 0\) en curvatura simple y \(r\) el radio de giro de la sección bruta (mm).
Magnificación de momentos (ACI 318-19, §6.6.4):
$$M_c = \delta_{ns} M_2, \qquad \delta_{ns} = \frac{C_m}{1 - P_u/(0.75 P_c)} \ge 1.0, \qquad P_c = \frac{\pi^2 (EI)_{eff}}{(k\ell_u)^2}, \qquad C_m = 0.6 + 0.4\frac{M_1}{M_2} \ge 0.4$$
\((EI)_{eff} = 0.4E_cI_g/(1+\beta_{dns})\), \(E_c = 4700\sqrt{f'_c}\) MPa para peso normal (ACI 318-19, §19.2.2.1), \(\beta_{dns}\) = relación entre la carga axial sostenida máxima y la total de la combinación. Excentricidad mínima \(M_{2,min} = P_u(15 + 0.03h)\), con \(h\) en mm y \(P_u\) en N. Si \(P_u/(0.75P_c) \ge 1.0\) la columna es inestable y se emite error, nunca un número.

### 6. Losas
Una dirección: \(h_{min} = \ell/20\) (simple), \(\ell/24\) (un extremo continuo), \(\ell/28\) (dos extremos continuos), \(\ell/10\) (voladizo) para \(f_y = 420\) MPa, multiplicado por \((0.4 + f_y/700)\) para otro grado (ACI 318-19, Tabla 7.3.1.1).
Dos direcciones, método directo (DDM): válido solo si hay al menos 3 vanos por dirección, luz larga/corta \(\le 2\), vanos adyacentes que no difieran en más de un tercio, carga gravitacional uniforme y los límites de rigidez relativa de §8.10.2. Momento estático total por vano \(M_o = w_u\ell_2\ell_n^2/8\) (N·m), repartido entre franjas de columna y centrales según las fracciones tabuladas; \(\ell_n\) es la luz libre entre caras de apoyo.
Punzamiento: \(v_u = V_u/(b_o d)\) con perímetro crítico \(b_o\) a \(d/2\) de la cara del apoyo más la transferencia de momento desbalanceado con la fracción \(\gamma_v\) (ACI 318-19, §22.6.5).
Método de los coeficientes: no es un método vigente de ACI 318-19 (procede de ACI 318-63 y se reproduce en manuales de referencia tipo PCA Notes); solo sirve para revisar losas existentes dimensionadas con esa práctica.

> ⚠️ VERIFICAR: las fracciones de reparto del DDM (§8.10.4 y §8.10.6), los espesores mínimos de losa en dos direcciones sin vigas interiores (§8.3.1), los coeficientes del método de los coeficientes y las expresiones de \(v_c\) con \(\lambda_s\) y \(\gamma_v\) (§22.6.5) no se leyeron del documento oficial. Se transcriben a `data/usa/aci318/slab.json` y `punching.json`; el programa lee la tabla y falla con `CODE_DATA_MISSING` si la entrada no existe.

### 7. Zapatas
Presión de contacto \(q_u = P_u/A \pm M_u c/I\) (Pa), comparada con la capacidad admisible del estudio geotécnico, que no proviene de esta skill. Se revisa como voladizo: flexión en la cara del apoyo; cortante de una dirección con \(V_c\) de la Tabla 22.5.5.1 sobre la franja de ancho \(b_w\) (no sobre el ancho total \(B\)); punzamiento a \(d/2\) de la cara de la columna. Aplastamiento columna–zapata: \(\phi P_n = \phi\,0.85f'_cA_1\) con \(\phi = 0.65\) y amplificación por \(\sqrt{A_2/A_1} \le 2\) (ACI 318-19, §22.8). La armadura inferior necesita \(\ell_d\) completo desde la sección de momento máximo; si no cabe, se ancla con gancho (\(\ell_{dh}\)) y estribos.

### 8. Adherencia, desarrollo, anclaje y empalmes
$$\frac{\ell_d}{d_b} = \frac{f_y\,\psi_t\,\psi_e\,\psi_s\,\psi_g}{\kappa_d\,\lambda\sqrt{f'_c}\left(\dfrac{c_b + K_{tr}}{d_b}\right)}, \qquad \frac{c_b + K_{tr}}{d_b} \le 2.5, \qquad \ell_d \ge 300\ \text{mm}, \qquad K_{tr} = \frac{40 A_{tr}}{s\,n}$$
$$ \ell_{dh} \ge \max(8 d_b,\ 150\ \text{mm}), \qquad \ell_{dc} \ge 200\ \text{mm}, \qquad \text{empalme Clase A} = 1.0\ell_d, \qquad \text{Clase B} = 1.3\ell_d $$
\(c_b\) = menor recubrimiento o mitad del espaciamiento centro a centro (mm); \(A_{tr}\) = área total de estribos que cruzan el plano de hendimiento (mm²); \(n\) = número de barras desarrolladas en ese plano; \(A_{tr}/(sn)\) en mm. Factores: \(\psi_t = 1.3\) para barras con más de 300 mm de concreto fresco por debajo, 1.0 en otro caso; \(\psi_e = 1.0\) sin recubrimiento epóxico; \(\psi_s = 0.8\) para \(d_b \le\) D19 y 1.0 para D22 y mayores; \(\psi_g\) = factor de grado de ACI 318-19 (1.0 para 420 MPa, 1.15 para 550 MPa, 1.3 para 690 MPa). La clase del empalme la gobiernan \(A_{s,prov}/A_{s,req}\) y el porcentaje de barras empalmadas dentro de la longitud requerida (ACI 318-19, §25.5.2).

> ⚠️ VERIFICAR: las constantes numéricas del cap. 25 en su edición **SI**. ACI 318-19 se publica también en unidades inglesas y las constantes no son intercambiables; el análisis dimensional de la forma general da \(\kappa_d \approx 0.075\ \text{in/psi}^{0.5} \to 22.9\ \text{mm/MPa}^{0.5}\), valor que debe confirmarse contra ACI 318-19 edición SI junto con la Tabla 25.4.2.5 completa (\(\psi_t,\psi_e,\psi_s,\psi_g\)) y las constantes de \(\ell_{dh}\) y \(\ell_{dc}\). Se guardan en `data/usa/aci318/development.json`; el motor lee \(\kappa_d\) del archivo y una prueba unitaria comprueba que la forma general y la simplificada coinciden al 0.1 % en \((c_b+K_{tr})/d_b = 2.5\).

### 9. Requisitos sismorresistentes (cap. 18)
- **Sistemas a momento.** Los **especiales** (SMF) exigen vigas con \(\ell_n \ge 4h\), \(b_w \ge \max(0.3h,\ 250\ \text{mm})\), momento positivo en la cara del nudo \(\ge\) la mitad del negativo allí y \(\ge\) un cuarto del máximo momento de la viga en cualquier sección, con el primer estribo a \(\le 50\) mm de la cara del apoyo. Los **intermedios** (IMF) relajan el confinamiento pero conservan los requisitos de resistencia; los **ordinarios** (OMF) solo exigen el detallado general.
- **Viga fuerte / columna fuerte:** en cada nudo de un SMF, \(\sum M_{nc} \ge (6/5)\sum M_{nb}\), con \(M_n\) calculado con \(f_y^{prob} = 1.25f_y\) y \(\phi = 1.0\), sumando columnas por encima y por debajo del nudo y vigas a izquierda y derecha (ACI 318-19, §18.7.3.2; excepciones en §18.7.3.3).
- **Confinamiento de columnas SMF:** \(A_{sh}/s\) es el mayor de \(0.3(A_g/A_{ch}-1)f'_c/f_{yt}\) y \(0.09f'_c/f_{yt}\) (mm²/mm), con espaciamiento en la zona de articulación plástica \(s \le \min(b_{min}/4,\ 6d_b,\ s_o)\), \(s_o = 100 + (350-h_x)/3\) y \(100 \le s_o \le 150\) mm.
- **Zona de articulación plástica:** longitud \(2h\) desde la cara del apoyo en vigas; el cortante de diseño allí se obtiene por capacidad a partir de \(M_{pr}\) con \(f_y^{prob} = 1.25f_y\), no de la combinación gravitacional.
- **Nudos viga-columna:** estribos de confinamiento en el nudo de un SMF y verificación de que \(\ell_{dh}\) del gancho de la viga cabe dentro de la columna.

> ⚠️ VERIFICAR: la numeración exacta de los artículos del cap. 18 (OMF, IMF, SMF, muros especiales, diafragmas) y los límites de \(s_o\), \(h_x\) y las excepciones de §18.7.3.3 no se contrastaron con el texto oficial. El programa guarda la cadena de cita por requisito en `data/usa/aci318/seismic_detailing.json` (`clause`, `value`, `unit`, `source`, `verified_on`) y **no** incrusta números de artículo en el código.

### 10. Módulo de revisión automática y relación demanda/capacidad
Cada componente produce un `CheckResult` con \(R_u\), \(R_n\), \(\phi\), \(D/C\), la cita y los pasos intermedios; la envolvente por sección es \(\max_k D/C_k\) sobre combinaciones y componentes, identificando la combinación y el componente gobernantes. Reglas: (i) toda longitud se normaliza a mm antes de entrar al núcleo; (ii) \(\phi\) y los coeficientes se resuelven en una única función `factors()`; (iii) ninguna comprobación devuelve un número si falta un dato: devuelve `CheckStatus.NOT_VERIFIED` con la razón; (iv) el orden de reporte es flexión, cortante, torsión, P-M, aplastamiento, desarrollo y detallado sísmico.

## Procedimiento
1. Normalizar unidades y validar materiales (\(f'_c\), \(f_y\), \(f_{yt}\), \(\lambda\), grado de barra).
2. Cargar \(\phi\) y las tablas de cortante, torsión, desarrollo, losas y detallado sísmico desde `data/usa/aci318/*.json`; abortar si falta una entrada citada.
3. Construir las envolventes \(P_u, M_u, V_u, T_u\) por combinación sobre los resultados del solver (no sobre la envolvente global: se pierde la correlación entre \(M\) y \(V\)).
4. **Flexión:** calcular \(a\), \(\varepsilon_t\), \(\phi\), \(\rho\), \(A_{s,min}\), \(\rho_{max}\); decidir entre sección simplemente armada, doblemente armada y T; emitir \(D/C\).
5. **Cortante:** clasificar \(A_v \ge A_{v,min}\), calcular \(\lambda_s\), las alternativas de \(V_c\) aplicables, \(V_s\) y los topes; verificar \(s\).
6. **Torsión:** comparar \(T_u\) con \(\phi T_{th}\); si aplica, dimensionar \(A_t/s\) y \(A_l\) y comprobar la interacción con cortante.
7. **Columnas:** construir el diagrama P-M con \(\phi\) variable, aplicar \(P_{n,max}\), evaluar esbeltez y, si aplica, magnificar \(M_2\) con la excentricidad mínima.
8. **Losas:** elegir el método según sus límites de aplicación (DDM solo si cumple §8.10.2) y verificar punzamiento en los apoyos.
9. **Zapatas:** presión de contacto, flexión, cortante de una dirección, punzamiento y aplastamiento.
10. **Desarrollo y anclaje:** calcular \(\ell_d\), \(\ell_{dh}\), \(\ell_{dc}\) y la clase de empalme; comparar con la longitud disponible.
11. **Detallado sísmico:** aplicar los requisitos del sistema declarado y la comprobación viga fuerte/columna fuerte; emitir avisos.
12. Emitir el informe con \(D/C\) por sección, combinación gobernante, citas y advertencias; marcar `NOT_VERIFIED` en lo que no se pudo comprobar.

## Implementación en la plataforma
```python
# core/design/aci318/            (núcleo puro: sin Qt, sin OpenSeesPy)
#   materials.py  Concrete(fc, lambda_, wc) ; Rebar(fy, db, grade)
#   factors.py    phi_flexure(eps_t, transverse) -> float ; lambda_s(d) ; load_factors(data)
#   flexure.py    nominal_moment(section, As) -> FlexureResult ; required_steel(section, Mu)
#                 t_beam_moment(section, As) -> FlexureResult
#   shear.py      vc_alternatives(section, Av, s, Nu, fyt) -> tuple[float, ...]
#                 shear_design(section, Vu, stirrup, s) -> ShearResult
#   torsion.py    torsion_threshold(section) ; torsion_design(section, Tu, Vu, At, s)
#   column.py     interaction_surface(section, layout, n_points) -> PMSurface
#                 slender_check(column, k, lu, M1, M2) ; magnified_moment(column, Pu, M2, ...)
#   slab.py       ddm_applicability(system) -> bool ; static_moment(wu, l2, ln)
#                 punching_shear(slab, Vu, Munbal, gamma_v) -> PunchingResult
#   footing.py    bearing_pressure(footing, Pu, Mu) ; one_way_shear(...) ; punching_shear(...)
#   development.py ld(...) ; ldh(...) ; ldc(...) ; splice_class(As_prov, As_req, pct) -> str
#   seismic.py    strong_column_weak_beam(joint, fy_prob=1.25) ; confinement_ash(column, fyt)
#                 hoop_spacing(column, hx, db)
#   check.py      run_design_checks(member, envelopes, code_data) -> DesignReport

# services/design/aci318_service.py   (único punto que toca el solver)
def design_report(results: Results, project: Project, code_data: CodeData) -> DesignReport:
    """Extrae envolventes de result_store y llama a core.design.aci318.check."""
```
Reglas de arquitectura: `core/design/aci318/**` no importa Qt ni `openseespy` y se ejecuta en un script o CLI sin GUI; ningún coeficiente regulado vive en el código (se lee de `data/usa/aci318/{phi,shear,torsion,development,slab,punching,seismic_detailing}.json` con `value`, `unit`, `source` y `verified_on`); el núcleo recibe dataclasses planas (`Section`, `RebarLayout`, `Demands`) y nunca objetos vivos de OpenSees, que solo circulan por `services/design/`; cambiar de edición (318-19 → 318-25) es cambiar el directorio de datos y el identificador de edición, no el motor.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(\varepsilon_{cu} = 0.003\); \(a = \beta_1 c\) | ACI 318-19, §22.2.2.1 y §22.2.2.4.3 | sí |
| \(\beta_1 = 0.85\) para \(f'_c \le 28\) MPa; \(-0.05(f'_c-28)/7 \ge 0.65\) | ACI 318-19, §22.2.2.4.3 | sí |
| \(A_{s,min} = \max(0.25\sqrt{f'_c}/f_y,\ 1.4/f_y)b_w d\) | ACI 318-19, §9.6.1.2 | sí |
| Control por tracción: \(\varepsilon_t \ge \varepsilon_{ty}+0.003 \Rightarrow \phi = 0.90\) | ACI 318-19, Tabla 21.2.2 | sí |
| \(\phi\): 0.90 flexión; 0.75 cortante y torsión; 0.65 compresión con estribos y aplastamiento; 0.75 espiral | ACI 318-19, Tabla 21.2.1 | subconjunto |
| \(V_c\): 0.17 y 0.66; \(A_{v,min}\): 0.062 y 0.35; topes 0.42 y 0.66 | ACI 318-19, Tabla 22.5.5.1 y §22.5.1.2 | sí (derivadas por análisis dimensional desde la edición inglesa) |
| \(\lambda_s = \sqrt{2/(1+d/250)} \le 1.0\) | ACI 318-19, §22.5.5.1 | sí |
| \(T_{th} = 0.083\lambda\sqrt{f'_c}A_{cp}^2/P_{cp}\); \(T_{cr} = 0.33\lambda\sqrt{f'_c}A_{cp}^2/P_{cp}\) | ACI 318-19, §22.7.4.1 y §22.7.5.1 | sí (misma derivación) |
| \(T_n = 2A_oA_tf_{yt}\cot\theta/s\); \(A_o = 0.85A_{oh}\) | ACI 318-19, §22.7.6.1 | sí |
| \(P_o = 0.85f'_c(A_g-A_{st}) + f_yA_{st}\); \(P_{n,max} = 0.80P_o\) | ACI 318-19, §22.4.2 | sí |
| Esbeltez despreciable: \(22\) y \(34+12M_1/M_2 \le 40\) | ACI 318-19, §6.2.5 | sí |
| \(\delta_{ns} = C_m/(1-P_u/(0.75P_c)) \ge 1.0\); \((EI)_{eff} = 0.4E_cI_g/(1+\beta_{dns})\) | ACI 318-19, §6.6.4 | sí |
| \(E_c = 4700\sqrt{f'_c}\) MPa (peso normal) | ACI 318-19, §19.2.2.1 | sí |
| \(\sum M_{nc} \ge (6/5)\sum M_{nb}\) | ACI 318-19, §18.7.3.2 | expresión sí; numeración en `VERIFICAR` |
| Tablas 21.2.1 y 21.2.2 completas | ACI 318-19 | no — `VERIFICAR` |
| Tabla 22.5.5.1 completa (aplicabilidad, secciones circulares) | ACI 318-19 | no — `VERIFICAR` |
| §22.6.5 (punzamiento: \(v_c\), \(\lambda_s\), \(\gamma_v\)) | ACI 318-19 | no — `VERIFICAR` |
| §8.3.1 y §8.10 (losas: espesores y fracciones del DDM) | ACI 318-19 | no — `VERIFICAR` |
| Cap. 25 completo en edición SI (\(\kappa_d\), Tabla 25.4.2.5) | ACI 318-19 | no — `VERIFICAR` |
| Numeración y excepciones del cap. 18 | ACI 318-19 | no — `VERIFICAR` |

## Verificación y casos de prueba

| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| \(M_n\) rectangular | \(b_w = 300\), \(d = 450\), \(f'_c = 28\), \(f_y = 420\) MPa, \(A_s = 942.48\) mm² | \(a = 55.44\) mm; \(M_n = 167.16\) kN·m; \(\phi M_n = 150.44\) kN·m | 0.1 % | mano, §22.2 |
| Frontera de \(\phi\) (318-19) | mismo \(d\), grado 420 (\(\varepsilon_{ty} = 0.0021\)) | control por tracción desde \(\varepsilon_t = 0.0051\): \(c = 166.67\) mm, \(A_s = 2408.3\) mm² | 0.5 % | Tabla 21.2.2 |
| Arrastre de edición | el mismo caso con \(\varepsilon_t = 0.005\) | \(A_s = 2438.4\) mm²; debe diferir y emitir `EDITION_MISMATCH` | 0.5 % | Tabla 21.2.2 vs. 318-14 |
| \(A_{s,min}\) | \(b_w = 300\), \(d = 450\), \(f'_c = 28\), \(f_y = 420\) MPa | 450.0 mm² (gobierna \(1.4/f_y\)) | 0.1 % | §9.6.1.2 |
| \(V_c\) alternativa (a) | \(b_w = 300\), \(d = 450\), \(f'_c = 28\) MPa, \(N_u = 0\), \(\lambda = 1\) | \(V_c = 121.44\) kN | 0.1 % | Tabla 22.5.5.1 |
| \(V_c\) alternativa (b) | igual, \(\rho_w = 0.006981\ (= 942.48/(300\cdot450))\) | \(V_c = 90.11\) kN | 0.1 % | Tabla 22.5.5.1 |
| \(\lambda_s\) | \(d = 450\) mm | 0.84515 | 1e-6 | §22.5.5.1 |
| \(A_{v,min}\) | \(b_w = 300\), \(s = 150\), \(f_{yt} = 420\) MPa | 37.5 mm² (gobierna 0.35) | 0.1 % | §9.6.3.3 |
| \(\phi(V_c+V_s)\) | 2 ramas D10 (\(A_v = 157.08\) mm²), \(s = 150\) mm, alternativa (a) | \(V_s = 197.92\) kN; \(\phi V_n = 239.5\) kN | 0.1 % | Tabla 22.5.5.1 |
| \(P_o\) y \(P_{n,max}\) | 400×400, \(f'_c = 28\), \(f_y = 420\) MPa, \(A_{st} = 2513.27\) mm² | \(P_o = 4803.8\) kN; \(P_{n,max} = 3843.0\) kN | 0.1 % | §22.4.2 |
| Punto balanceado | 400×400, \(d' = 60\), \(d = 340\), 3+3+2 barras D20, \(\varepsilon_{ty} = 0.0021\) | \(c_b = 200\) mm; \(P_n = 1595.97\) kN; \(M_n = 517.25\) kN·m | 0.5 % | compatibilidad de deformaciones |
| Esbeltez límite | \(M_1/M_2 = 0.5\), arriostrada | \(k\ell_u/r \le 40\) | 1e-9 | §6.2.5 |
| \(\delta_{ns}\) | \(C_m = 0.8\), \(P_u = 2000\) kN, \(P_c = 3491.3\) kN | \(\delta_{ns} = 3.387\) | 0.5 % | §6.6.4 |
| Coherencia de \(\ell_d\) | \((c_b+K_{tr})/d_b = 2.5\), grado 420, \(f'_c = 28\) MPa | forma general y simplificada coinciden | 0.1 % | `development.json` |
| Mínimos de anclaje | cualquier barra | \(\ell_d \ge 300\) mm; \(\ell_{dh} \ge \max(8d_b, 150)\) mm; \(\ell_{dc} \ge 200\) mm | 1e-9 | §25.4 |
| Clase de empalme | \(A_{s,prov}/A_{s,req} = 1.5\), 40 % empalmado | Clase A (\(1.0\ell_d\)) | 1e-9 | §25.5.2.1 |
| Viga fuerte/columna fuerte | nudo con \(\sum M_{nb} = 400\) kN·m a \(1.25f_y\) | exige \(\sum M_{nc} \ge 480\) kN·m | 0.1 % | §18.7.3.2 |

Contraste obligatorio adicional: un pórtico espacial completo contra un programa de referencia reconocido (ETABS o SAP2000 con ACI 318-19), comparando \(\phi M_n\), \(\phi V_n\) y \(D/C\) por sección, más una regresión de la envolvente de \(D/C\) contra los resultados del solver para detectar desalineación entre la sección del elemento y la sección usada en el diseño.

## Errores frecuentes y trampas
1. **Mezclar las ediciones SI e inglesa de ACI 318-19:** copiar \(2\sqrt{f'_c}\) (psi) dentro de una fórmula con MPa da un resultado casi 19 veces mayor. El archivo de datos declara `unit_system: "SI"` y el motor rechaza constantes de otro sistema.
2. **Usar \(\varepsilon_t \ge 0.005\)** (ACI 318-14) en vez de \(\varepsilon_t \ge \varepsilon_{ty} + 0.003\) (Tabla 21.2.2): para grado 420 la frontera es 0.0051 y con 0.005 se sobreestima \(\phi M_n\) en secciones ya en transición.
3. **Reintroducir \(\rho_{max} = 0.75\rho_b\):** ese límite no existe en ACI 318-19; la ductilidad la gobierna \(\varepsilon_t\).
4. **Omitir \(\lambda_s\)** en \(V_c\) para \(d > 250\) mm: con \(d = 450\) mm el factor es 0.845 y la resistencia baja cerca del 15 %.
5. **Usar la fórmula (a) con \(A_v < A_{v,min}\):** en ese caso solo aplica la expresión (c), que además lleva \(\lambda_s\) y \(\rho_w^{1/3}\).
6. **Valor absoluto de \(N_u\)** en \(V_c\): el término \(N_u/(6A_g)\) es negativo en tracción y reduce \(V_c\); usar \(\lvert N_u \rvert\) lo aumenta indebidamente.
7. **\(\lambda = 1.0\) por defecto** con concreto liviano declarado en el modelo: todas las resistencias quedan sobrestimadas.
8. **\(f'_c\) en kg/cm²:** un valor de 210 kg/cm² (21 MPa) tratado como 210 MPa produce una sección ficticia diez veces más resistente.
9. **\(\phi\) constante en columnas:** aplicar 0.65 a todo el diagrama recorta el extremo de flexión pura (donde \(\phi = 0.90\)) y omitir \(P_{n,max} = 0.80P_o\) deja pasar axiales excesivos.
10. **Magnificar antes de aplicar la excentricidad mínima:** \(M_{2,min} = P_u(15+0.03h)\) se compara con \(M_2\) antes de magnificar (o se magnifica el mayor de los dos), nunca después.
11. **\(\beta_{dns} = 0\) por omisión:** infla \((EI)_{eff}\), subestima \(\delta_{ns}\) y falla justo en el caso que importa (columnas con carga sostenida alta).
12. **Viga fuerte/columna fuerte con \(\phi M_n\):** la comparación usa \(M_n\) con \(f_y = 1.25f_y\) y \(\phi = 1\); además los momentos de columna se suman por encima y por debajo del nudo, no su diferencia.
13. **Confinamiento mal parametrizado:** usar \(s_o\) sin el tope \(100 \le s_o \le 150\) mm, o trasladar el espaciamiento de estribos de viga a la columna.
14. **Olvidar \(\psi_t = 1.3\)** en barras superiores con más de 300 mm de concreto por debajo: subestima \(\ell_d\) un 30 % en las vigas de mayor canto.
15. **Punzamiento con el perímetro de la columna** en vez del perímetro crítico a \(d/2\), y sin \(\gamma_v\) cuando hay momento desbalanceado.
16. **Zapatas con el ancho total \(B\)** en el cortante de una dirección, que se calcula por franja de ancho \(b_w\) (típicamente 1 m).
17. **Torsión con \(A_o = A_{oh}\)** en vez de \(0.85A_{oh}\), y con el perímetro exterior en vez del perímetro del estribo cerrado \(p_h\).
18. **Calcular \(\varepsilon_t\) con \(A_{s,req}\) y \(\phi M_n\) con \(A_{s,prov}\)** (o al revés): ambas comprobaciones deben usar la armadura realmente dispuesta.
19. **Redondear \(a\), \(f'_c\) o \(\phi M_n\) antes de la comprobación final:** rompe la trazabilidad entre la memoria de cálculo y el resultado del programa.

## Interfaz de salida
El programa debe exponer, por elemento y por combinación: identificación (elemento, sección, \(f'_c\), \(f_y\), \(f_{yt}\), \(\lambda\), edición de la norma y ruta del archivo de datos con su `verified_on`).
Por componente (flexión, cortante, torsión, P-M, aplastamiento, desarrollo y detallado sísmico): \(R_u\) con signo y unidad, \(R_n\), \(\phi\), \(D/C\), veredicto y **cita** (norma, edición, tabla o sección).
Intermedios reproducibles a mano: \(a\), \(c\), \(\varepsilon_t\), \(\rho\), \(A_{s,min}\), \(\rho_{max}\); \(V_c\) con la alternativa usada, \(V_s\), \(A_{v,min}\), \(s\); \(A_t/s\), \(A_l\), \(\theta\); \(P_o\), \(P_{n,max}\), \(k\ell_u/r\), \(\delta_{ns}\); \(\ell_d\), \(\ell_{dh}\) y la clase de empalme.
Envolvente de \(D/C\) con la combinación y el componente gobernantes, y listado de todas las combinaciones que superan 1.0.
Avisos: `NOT_VERIFIED`, `CODE_DATA_MISSING`, `SLENDERNESS_UNSTABLE` (\(P_u/(0.75P_c) \ge 1\)), `EDITION_MISMATCH`, `DEFLECTION_MIN_THICKNESS`.
Unidades explícitas en cada campo: fuerzas en N, momentos en N·m, longitudes en m, tensiones en Pa; el informe puede formatear a kN y kN·m, pero el valor almacenado es SI coherente y sin redondeo previo a la comprobación.

## Referencias
1. ACI Committee 318, *Building Code Requirements for Structural Concrete (ACI 318-19) and Commentary (ACI 318R-19)*, American Concrete Institute, 2019.
2. ACI Committee 318, *ACI 318-19 en unidades SI* (edición métrica del código y su comentario), American Concrete Institute, 2019.
3. ACI Committee 318, *Building Code Requirements for Structural Concrete (ACI 318-14)*, 2014 — solo para detectar arrastres de edición.
4. ACI, *SP-17(14) The Reinforced Concrete Design Handbook*, vols. 1–2.
5. PCA, *Notes on ACI 318-19 with Design Applications*.
6. ACI Committee 408, *408R-03 Bond and Development of Straight Reinforcing Bars in Tension*.
7. ACI-ASCE Committee 352, *352R-02 Recommendations for Design of Beam-Column Connections in Monolithic Reinforced Concrete Structures*.
8. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures* — combinaciones de carga y \(D/C\) sísmico.

## Registro de verificación
- **Verificado:** \(\varepsilon_{cu}\), \(\beta_1\), \(A_{s,min}\) de §9.6.1.2, la frontera de \(\phi\) por \(\varepsilon_{ty}+0.003\) de la Tabla 21.2.2, el subconjunto de \(\phi\) de la Tabla 21.2.1, las constantes SI de \(V_c\) y \(A_{v,min}\) (derivadas por análisis dimensional desde la edición inglesa), \(\lambda_s\), \(T_{th}\), \(T_{cr}\), \(T_n = 2A_oA_tf_{yt}\cot\theta/s\), \(P_o\), \(P_{n,max}\), los límites de esbeltez de §6.2.5, \(\delta_{ns}\), \((EI)_{eff}\), \(E_c = 4700\sqrt{f'_c}\) y la expresión \(\sum M_{nc} \ge (6/5)\sum M_{nb}\).
- **Pendiente:** transcripción completa de las Tablas 21.2.1, 21.2.2, 22.5.5.1, 22.6.5, 8.3.1, 8.10 y 25.4.2.5; constantes SI del cap. 25; numeración y excepciones del cap. 18; forma de la interacción cortante–torsión.
- **Responsable de cerrar:** responsable de normativa del proyecto, con copia licenciada de ACI 318-19 en su edición SI. La skill permanece en `status: draft` mientras existan marcas `VERIFICAR`; el programa lee todo valor regulado de `data/usa/aci318/*.json` y nunca lo incrusta en el código.
