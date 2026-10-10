---
name: steel-aisc360-341
description: >-
  Implementa y verifica el diseño de acero estructural conforme a AISC 360-22 en
  LRFD y ASD: tracción, compresión, flexión, corte, interacción P-M, placas base
  y conexiones; y los requisitos sismorresistentes de AISC 341-22 (SMF, SCBF,
  BRBF, ancho-espesor, capacidad) con las conexiones precalificadas de AISC
  358-22. Úsala cuando el proyecto declare acero estructural AISC, cuando haya
  que calcular una relación demanda/capacidad φRn o Rn/Ω, o al auditar un módulo
  de diseño de acero existente; se dispara además con errores de An/Ae, Ry o Cb.
metadata:
  track: design
  jurisdiction: USA
  edition: "AISC 360-22, AISC 341-22, AISC 358-22"
  status: draft
  verified_on: "2026-02-14"
  scope: [design, qa]
---

# AISC 360-22 / 341-22 / 358-22 — Diseño de acero estructural

## Cuándo usar esta skill

- El proyecto declara `code = AISC 360` con jurisdicción EE. UU. y hay que dimensionar o revisar perfiles laminados, armados o HSS.
- Aparece una relación demanda/capacidad (\(\phi R_n\), \(R_n/\Omega\), \(P_r/P_c\), \(M_r/M_c\)) y hay que decidir qué estado límite gobierna.
- El sistema sismorresistente es SMF, SCBF, BRBF o EBF y hay que aplicar AISC 341: materiales esperados \(R_yF_y\), ancho-espesor, capacidad y conexiones.
- Hay que seleccionar o auditar una conexión viga–columna precalificada de AISC 358 contra sus límites de precalificación.
- Se audita un módulo existente: los defectos típicos son usar \(A_g\) por \(A_e\), \(d_b\) por \(d_e\) y \(F_y\) por \(R_yF_y\).

**No usar** para concreto (→ `design/concrete-aci318`), cimentaciones (→ `design/foundations-and-soil-structure`) ni peligro sísmico y combinaciones (→ `codes/asce7-22-seismic-design`, `seismic/load-combinations-and-limit-states`).

## Alcance y límites

Cubre AISC 360-22 caps. B (requisitos), C (estabilidad), D (tracción), E (compresión), F (flexión), G (corte), H (combinadas y torsión) y J (conexiones); AISC 341-22 caps. A–F; y AISC 358-22 completo. **Fuera de alcance**: diseño compuesto (360 cap. I), muros de placa de acero (341 cap. I), fatiga y fractura, y el análisis que produce \(P_r\), \(M_r\), \(V_r\) (→ `core/fem-formulation-core`, `seismic/seismic-analysis-procedures`).

Supuestos: acero conforme a AISC 360-22 cap. A y 341-22 cap. A; secciones doblemente simétricas salvo indicación; elementos compactos salvo que esta skill clasifique lo contrario; ejes locales del solver (x axial, y y z de flexión) declarados en el modelo.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Material (\(F_y\), \(F_u\), norma ASTM, \(R_y\), \(R_t\)) | sí | bloquear: no se inventa \(F_y\) ni \(R_y\) |
| Propiedades (\(A_g\), \(Z_x\), \(S_x\), \(r_y\), \(r_{ts}\), \(J\), \(C_w\), \(h_0\), \(t_w\), \(b_f\), \(t_f\), \(d\)) | sí | bloquear o derivar de la biblioteca de perfiles |
| Ley de momentos y \(L_b\) por segmento no arriostrado | sí | bloquear: \(C_b\) y LTB dependen del diagrama real |
| Longitudes efectivas \(K_xL_x\), \(K_yL_y\), \(K_zL_z\) | sí | usar \(K=1.0\) solo tras declararlo |
| Solicitaciones \(P_r\), \(M_{rx}\), \(M_{ry}\), \(V_r\) de 2.º orden | sí | bloquear: no se amplifica a mano lo que exige el cap. C |
| Método LRFD o ASD | sí | bloquear: \(\phi\) y \(\Omega\) no son intercambiables |
| Agujeros (tipo, diámetro) y conectores por línea | sí en tracción | bloquear \(A_e\) |
| Sistema sismorresistente y SDC | sí si hay sismo | bloquear AISC 341 |
| \(f'_c\), \(A_1\), \(A_2\) de la placa base | sí en placas base | bloquear §J8 |

Constantes en SI: \(E = 200\ \text{GPa}\) (AISC publica 29 000 ksi \(= 199.9\ \text{GPa}\)) y \(G = 77.2\ \text{GPa}\) (11 200 ksi). La conversión desde tablas en unidades US se hace una sola vez, en el borde de entrada.

## Fundamento y formulación

### 1. Filosofía de diseño: LRFD y ASD

$$R_u \le \phi R_n\ \text{(LRFD)}, \qquad R_a \le R_n/\Omega\ \text{(ASD)}$$
\(R_n\) resistencia nominal (N); \(\phi\) y \(\Omega\) factores adimensionales; \(R_u\) y \(R_a\) solicitaciones mayorada y de servicio (N). AISC aporta \(R_n\), \(\phi\) y \(\Omega\); las combinaciones vienen de ASCE 7-22 §2.3 (LRFD) y §2.4 (ASD). Los pares publicados cumplen \(\Omega \approx 1.5/\phi\), pero \(\Omega\) se lee publicado y **nunca** se calcula en el código.

### 2. Tracción (cap. D)

$$P_n = F_yA_g\ (\phi_t = 0.90,\ \Omega_t = 1.67); \qquad P_n = F_uA_e\ (\phi_t = 0.75,\ \Omega_t = 2.00)$$
$$A_e = UA_n, \qquad A_n = A_g - \sum d_et + \sum \frac{s^2}{4g}t, \qquad d_e = d_b + 2\ \text{mm (agujero estándar)}$$
\(F_y\), \(F_u\) (Pa); \(A_g\), \(A_n\), \(A_e\) (m²); \(U = 1-\bar{x}/L\) en el caso general, con \(\bar{x}\) excentricidad al plano de la conexión (m) y \(L\) su longitud (m); \(s\) paso y \(g\) gramil (m). Rotura por bloque (§J4.3): \(R_n = 0.6F_uA_{nv} + U_{bs}F_uA_{nt} \le 0.6F_yA_{gv} + U_{bs}F_uA_{nt}\), con \(\phi = 0.75\), \(\Omega = 2.00\), \(U_{bs} = 1.0\) con tensión uniforme y \(0.5\) si no.

### 3. Compresión (cap. E)

$$P_n = F_{cr}A_g, \qquad F_e = \frac{\pi^2E}{(KL/r)^2}, \qquad F_{cr} = \begin{cases} 0.658^{\,F_y/F_e}F_y & KL/r \le 4.71\sqrt{E/F_y} \\ 0.877F_e & KL/r > 4.71\sqrt{E/F_y} \end{cases}$$
\(\phi_c = 0.90\), \(\Omega_c = 1.67\) (§E3); con elementos esbeltos se usa \(A_e\) y \(\phi_c = 0.85\), \(\Omega_c = 1.76\) (§E7). \(KL/r \le 200\) es recomendación de proyecto, no estado límite.
$$F_{ez} = \left(\frac{\pi^2EC_w}{(K_zL_z)^2} + GJ\right)\frac{1}{A_gr_0^2}, \quad H = 1 - \frac{x_0^2+y_0^2}{r_0^2}, \quad F_{cr} = \frac{F_{ey}+F_{ez}}{2H}\left[1-\sqrt{1-\frac{4F_{ey}F_{ez}H}{(F_{ey}+F_{ez})^2}}\right]$$
\(C_w\) constante de alabeo (m⁶); \(J\) torsión (m⁴); \(r_0\) radio polar al centro de cortante (m); \(x_0\), \(y_0\) coordenadas del centro de cortante (m). En secciones asimétricas se toma el menor de los modos de flexión, torsión y flexo-torsión.

### 4. Flexión (cap. F)

$$M_p = F_yZ_x, \quad L_p = 1.76\,r_y\sqrt{E/F_y}, \quad r_{ts}^2 = \frac{\sqrt{I_yC_w}}{S_x}, \quad c = 1\ \text{(doble simetría)}$$
$$L_r = 1.95\,r_{ts}\frac{E}{F_y}\sqrt{\frac{Jc}{S_xh_0}+\sqrt{\left(\frac{Jc}{S_xh_0}\right)^2+6.76\left(\frac{F_y}{E}\right)^2}}$$
$$M_n = M_p\ (L_b \le L_p); \quad C_b\left[M_p-(M_p-0.7F_yS_x)\frac{L_b-L_p}{L_r-L_p}\right]\le M_p\ (L_p<L_b\le L_r); \quad F_{cr}S_x\le M_p\ (L_b>L_r)$$
$$F_{cr} = \frac{C_b\pi^2E}{(L_b/r_{ts})^2}\sqrt{1+0.078\frac{Jc}{S_xh_0}\left(\frac{L_b}{r_{ts}}\right)^2}, \qquad C_b = \frac{12.5M_{max}}{2.5M_{max}+3M_A+4M_B+3M_C}R_m \le 3.0$$
\(\phi_b = 0.90\), \(\Omega_b = 1.67\); \(L_b\) longitud no arriostrada del segmento (m); \(h_0\) distancia entre centros de alas (m); momentos en N·m; \(R_m = 1.0\) en doble simetría (caso monosimétrico: ver *Datos normativos*). Eje débil (§F6): \(M_n = F_yZ_y \le 1.6F_yS_y\). Pandeo local (§F3): interpolación entre \(M_p\) y \(0.7F_yS_x\) con \(\lambda_{pf}\) y \(\lambda_{rf}\) (Tabla B4.1b).

### 5. Corte e interacción flexión–cortante (cap. G)

$$V_n = 0.6F_yA_wC_{v1}, \quad A_w = dt_w, \quad C_{v1} = \begin{cases} 1.0 & h/t_w \le 1.10\sqrt{k_vE/F_y} \\ \dfrac{1.10\sqrt{k_vE/F_y}}{h/t_w} & 1.10\sqrt{k_vE/F_y} < h/t_w \le 1.37\sqrt{k_vE/F_y} \\ \dfrac{1.51Ek_v}{(h/t_w)^2F_y} & h/t_w > 1.37\sqrt{k_vE/F_y} \end{cases}$$
\(\phi_v = 0.90\), \(\Omega_v = 1.67\) (§G2); \(k_v = 5\) sin rigidizadores y \(k_v = 5 + 5/(a/h)^2\) con ellos, \(a\) separación (m). Para \(h/t_w > 1.37\sqrt{k_vE/F_y}\) aplica además la rama de pandeo elástico \(C_{v2}\).
Para secciones compactas AISC 360 evalúa \(M_n\) (§F2) y \(V_n\) (§G2) de forma **independiente**: no hay ecuación general \(M\)–\(V\). La interacción aparece en vigas armadas de alma esbelta, con \(R_{pg} = 1 - \frac{a_w}{1200+300a_w}\left(\frac{h_c}{t_w}-5.7\sqrt{E/F_y}\right)\le 1.0\) y \(a_w = h_ct_w/(b_{fc}t_{fc})\le 10\) (§F4/F5); y en el panel de nudo de pórticos a momento (AISC 341-22, cap. E): \(V_n = 0.6F_yd_ct_{wc}\left(1+\frac{3b_{cf}t_{cf}^2}{d_bd_ct_{wc}}\right)\), con \(\phi_v = 1.00\), multiplicado por \(1.9-1.2P_r/P_c\) si \(P_r > 0.75P_c\).

### 6. Flexión–compresión (caps. C y H)

$$P_r/P_c \ge 0.2:\ \frac{P_r}{P_c}+\frac{8}{9}\left(\frac{M_{rx}}{M_{cx}}+\frac{M_{ry}}{M_{cy}}\right)\le 1.0; \qquad P_r/P_c < 0.2:\ \frac{P_r}{2P_c}+\left(\frac{M_{rx}}{M_{cx}}+\frac{M_{ry}}{M_{cy}}\right)\le 1.0$$
\(P_c = \phi_cP_n\) o \(P_n/\Omega_c\); \(M_c = \phi_bM_n\) o \(M_n/\Omega_b\). Las dos ramas son **discontinuas** en \(P_r/P_c = 0.2\): se elige por condición, nunca por interpolación.
\(P_r\) y \(M_r\) deben ser de segundo orden (cap. C, método de análisis directo: cargas nocionales \(N_i = 0.002\alpha Y_i\), con \(\alpha = 1.0\) en LRFD y \(1.6\) en ASD, más reducción de rigidez \(\tau_b\)).

### 7. Placas base y conexiones (cap. J, DG1)

Aplastamiento sobre concreto (§J8), con \(\phi_c = 0.65\), \(\Omega_c = 2.31\): \(\phi_cP_p = \phi_c\,0.85f'_cA_1\sqrt{A_2/A_1} \le \phi_c\,0.85f'_cA_1(2)\).
Espesor por fluencia en el voladizo (AISC Design Guide 1): \(t_p \ge l\sqrt{2P_u/(0.90F_yBN)}\) (LRFD) y \(t_p \ge l\sqrt{2P_a\Omega/(F_yBN)}\) (ASD), con \(l = \max(m,n)\); \(N\) y \(B\) dimensiones de la placa (m); \(m\), \(n\) voladizos críticos (m). Pernos y soldaduras: §J2–§J3, con \(\phi = 0.75\) en cortante y tracción de pernos y en soldaduras.

> ⚠️ VERIFICAR: el refinamiento por líneas de fluencia \(l = \max(m,n,\lambda n')\) no se transcribió de la DG1; se comprueba en AISC Design Guide 1 y el programa lee \(\lambda\) de `data/aisc/base_plate.json`.

### 8. AISC 341-22: requisitos sismorresistentes

Resistencias esperadas \(F_y \to R_yF_y\) y \(F_u \to R_tF_u\) (Tabla A-3.1): ASTM A992 \(R_y = 1.1\), \(R_t = 1.1\); A36 \(1.5\), \(1.2\); A500 Gr. B/C \(1.4\), \(1.3\).
Ancho-espesor (Tabla D1.1), con \(C_a = P_u/(\phi_cF_yA_g)\): sección I *highly ductile* \(b_f/2t_f \le 0.30\sqrt{E/F_y}\) y \(h/t_w \le 2.45\sqrt{E/F_y}\) para \(C_a \le 0.114\); *moderately ductile* \(0.38\sqrt{E/F_y}\) y \(3.76\sqrt{E/F_y}\).
SMF: viga fuerte–columna débil \(\sum M^*_{pc}/\sum M^*_{pb} > 1.0\); momento probable \(M_{pr} = C_{pr}R_yF_yZ_x\) con \(C_{pr} = (F_y+F_u)/(2F_y)\le 1.2\); cortante de la conexión \(V_u = 2M_{pr}/L_h + V_{grav}\), con \(V_{grav}\) de \(1.2D + f_1L + 0.2S\) (AISC 358-22, §2.4.1). Conexiones precalificadas (RBS, WUF-W, BFP, BUEP, BSEP) válidas solo dentro de sus límites de peralte, peso, luz/peralte y panel.
SCBF: \(KL/r \le 200\) en diagonales, secciones *highly ductile*, conexión dimensionada para \(R_yF_yA_g\) en tracción y vigas y columnas para las solicitaciones de las diagonales en su resistencia esperada, con \(\Omega_0\) de ASCE 7-22 donde aplique. BRBF: \(P_{ysc} = R_yF_{ysc}A_{sc}\), con resistencias ajustadas \(\omega P_{ysc}\) en tracción y \(\beta\omega P_{ysc}\) en compresión, y \(\beta\), \(\omega\) del ensayo de precalificación.

> ⚠️ VERIFICAR: las Tablas A-3.1 y D1.1 completas, la resistencia esperada en compresión de las diagonales SCBF, la definición de \(\beta\) y \(\omega\) de BRBF y los límites de precalificación de AISC 358-22 se comprueban contra las ediciones impresas; el programa los **lee de `data/aisc/` versionado** y bloquea el chequeo si faltan.

## Procedimiento

1. Validar entradas y bloquear si falta material, sección, \(L_b\) o método (LRFD/ASD); cargar los coeficientes de `data/aisc/` y verificar su versión.
2. Clasificar la sección (compacta, no compacta, esbelta) con la Tabla B4.1a/b; calcular \(A_e\) si hay elementos esbeltos.
3. Tracción: \(A_n\) con \(d_e\) y el término \(s^2/4g\); \(U\) de la Tabla D3.1; comparar fluencia bruta contra rotura neta; añadir rotura por bloque si la conexión lo permite.
4. Compresión: \(KL/r\) en ambos ejes, \(F_e\), rama de \(F_{cr}\); contrastar con torsión y flexo-torsión (§E4) y tomar el menor.
5. Flexión: por segmento calcular \(C_b\), \(L_p\), \(L_r\) y la rama de \(M_n\); verificar pandeo local (§F3) y eje débil (§F6).
6. Corte: \(h/t_w\), \(k_v\), \(C_{v1}\) y \(V_n\); aplicar \(R_{pg}\) solo en vigas armadas de alma esbelta.
7. Fuerzas combinadas: evaluar la rama de §H1 que la condición selecciona y registrar el D/C con su estado límite.
8. Conexiones: pernos, soldaduras y placas base (§J8, DG1) y, si hay sismo, precalificación AISC 358 y exigencias de capacidad de AISC 341.
9. Emitir el informe por elemento con envolventes por combinación, avisos y trazabilidad.

## Implementación en la plataforma

```python
# core/design/steel/aisc360.py   (core puro: sin Qt, sin openseespy)
@dataclass(frozen=True)
class LimitStateResult:
    name: str; rn: float; phi: float; omega: float; dc: float
    citation: str; intermediates: dict[str, float]

def tensile_strength(sec, mat, holes, lag, method: str) -> LimitStateResult: ...
def compressive_strength(sec, mat, KL: tuple, method: str) -> LimitStateResult: ...
def flexural_strength(sec, mat, Lb, Cb, method: str) -> LimitStateResult: ...
def shear_strength(sec, mat, stiffener_spacing=None, method: str) -> LimitStateResult: ...
def beam_column_ratio(Pr, Pc, Mrx, Mcx, Mry, Mcy) -> float: ...
def base_plate(loads, geometry, concrete, method: str) -> LimitStateResult: ...

# core/design/steel/aisc341.py y aisc358.py
def expected_strength(sec, mat, ry_rt) -> float: ...
def width_thickness_class(sec, mat, ductility: str) -> str: ...
def smf_connection_demand(sec, mat, Lh, gravity) -> tuple[float, float]: ...
def prequalified_connection(conn_id, geometry, limits) -> PrequalificationReport: ...
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):

- Estos módulos viven en `core/` y **no** importan Qt ni OpenSeesPy: son utilizables desde un script o un cuaderno sin interfaz gráfica.
- El solver y la base de resultados se tocan solo desde `services/` (`services/design_check.py`), que arma \(P_r\), \(M_r\), \(V_r\) por combinación y llama a `core/`; `viewmodels/` solo presenta.
- Todo \(\phi\), \(\Omega\), \(R_y\), \(R_t\), \(U\), límite ancho-espesor y límite de precalificación se lee de `data/aisc/*.json` con `source` y `verified_on`; el código nunca incrusta la tabla.
- Las funciones son puras y devuelven `LimitStateResult`; ninguna escribe en disco ni lanza excepción por falta de dato normativo: devuelven un estado `blocked` con la referencia faltante.
- Si el perfil no está en la biblioteca, el diseño se bloquea; no se interpolan propiedades de sección.

## Datos normativos

| Dato | Valor | Origen | ¿Verificado? |
|---|---|---|---|
| Tracción, fluencia / rotura | \(\phi_t = 0.90\), \(\Omega_t = 1.67\) / \(0.75\), \(2.00\) | AISC 360-22, §D2 | sí |
| Compresión por flexión | \(\phi_c = 0.90\), \(\Omega_c = 1.67\) | AISC 360-22, §E3 | sí |
| Compresión con elementos esbeltos | \(\phi_c = 0.85\), \(\Omega_c = 1.76\) | AISC 360-22, §E7 | sí |
| Flexión | \(\phi_b = 0.90\), \(\Omega_b = 1.67\) | AISC 360-22, §F1 | sí |
| Corte | \(\phi_v = 0.90\), \(\Omega_v = 1.67\) | AISC 360-22, §G2 | sí |
| Aplastamiento sobre concreto | \(\phi_c = 0.65\), \(\Omega_c = 2.31\) | AISC 360-22, §J8 | sí |
| Agujero efectivo estándar | \(d_e = d_b + 2\ \text{mm}\) | AISC 360-22, §D3.2 | sí |
| Invariante de los pares | \(\Omega \approx 1.5/\phi\) | derivada de los valores publicados | sí (contraste interno) |
| \(R_y\), \(R_t\) por norma de acero | tabla | AISC 341-22, Tabla A-3.1 | parcial: A992, A36, A500 |
| Ancho-espesor sismorresistente | tabla | AISC 341-22, Tabla D1.1 | parcial: sección I |
| \(R_m\) monosimétrico y \(\lambda_{pf}\), \(\lambda_{rf}\) | tabla | AISC 360-22, §F1 y Tabla B4.1b | no — `VERIFICAR` |
| \(U\) de retraso de cortante | tabla | AISC 360-22, Tabla D3.1 | no — `VERIFICAR` |

> ⚠️ VERIFICAR: la numeración de artículos de AISC 360-22 y 341-22 cambió en la reorganización de las ediciones 2022 respecto a 360-16/341-16. Las formas de las ecuaciones citadas son las vigentes, pero el número de artículo, las tablas completas y el tratamiento dual \(C_{v1}\)/\(C_{v2}\) de §G2 deben confirmarse contra las ediciones impresas antes de pasar la skill a `ready`.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Fluencia en tracción | \(A_g = 1.0\times10^{-2}\ \text{m}^2\), \(F_y = 345\ \text{MPa}\) | \(P_n = 3.45\ \text{MN}\), \(\phi_tP_n = 3.105\ \text{MN}\) | 1e-9 rel. |
| Rotura en tracción | \(A_e = 8.0\times10^{-3}\ \text{m}^2\), \(F_u = 450\ \text{MPa}\) | \(P_n = 3.60\ \text{MN}\), \(\phi_tP_n = 2.70\ \text{MN}\) | 1e-9 rel. |
| Área neta con agujeros alternados | \(A_g = 5.0\times10^{-3}\ \text{m}^2\), 2 agujeros \(d_e = 0.022\ \text{m}\), \(t = 0.010\ \text{m}\), \(s = g = 0.075\ \text{m}\) | \(A_n = 4.7475\times10^{-3}\ \text{m}^2\) | 1e-9 rel. |
| Área efectiva | \(U = 0.85\) con el \(A_n\) anterior | \(A_e = 4.0354\times10^{-3}\ \text{m}^2\) | 1e-9 rel. |
| Pandeo por flexión | \(KL/r = 80\), \(E = 200\ \text{GPa}\), \(F_y = 345\ \text{MPa}\) | \(F_e = 308.43\ \text{MPa}\), \(F_{cr} = 216.0\ \text{MPa}\) | 0.1 % rel. |
| Continuidad en la transición §E3 | \(F_e = 0.44F_y\) | rama inelástica \(0.3861F_y\) vs. elástica \(0.3859F_y\) | 0.1 % rel. |
| \(L_p\) | \(r_y = 0.05\ \text{m}\), \(E = 200\ \text{GPa}\), \(F_y = 345\ \text{MPa}\) | \(L_p = 2.119\ \text{m}\) | 1e-3 rel. |
| \(C_b\), viga biapoyada con carga repartida | \(M_A = M_C = 3wL^2/32\), \(M_B = M_{max} = wL^2/8\), \(R_m = 1.0\) | \(C_b = 1.1364\) (AISC publica 1.14) | 1e-3 abs. |
| Corte sin rigidizadores | \(A_w = 1.0\times10^{-2}\ \text{m}^2\), \(F_y = 345\ \text{MPa}\), \(h/t_w = 50\), \(k_v = 5\) | \(C_{v1} = 1.0\), \(V_n = 2.07\ \text{MN}\), \(\phi_vV_n = 1.863\ \text{MN}\) | 0.1 % rel. |
| Límite de \(C_{v1}\) | \(E = 200\ \text{GPa}\), \(F_y = 345\ \text{MPa}\), \(k_v = 5\) | \(1.10\sqrt{k_vE/F_y} = 59.22\) | 1e-3 rel. |
| P-M rama de axial alto | \(P_r/P_c = 0.5\), \(M_{rx}/M_{cx} = 0.3\), \(M_{ry}/M_{cy} = 0.1\) | 0.8556 | 1e-6 abs. |
| P-M rama de axial bajo | \(P_r/P_c = 0.1\), \(M_{rx}/M_{cx} = 0.5\) | 0.55 | 1e-6 abs. |
| Discontinuidad en \(P_r/P_c = 0.2\) | \(P_r/P_c = 0.2\), \(\sum M_r/M_c = 0.5\) | rama (a) \(0.6444\); la rama (b) daría \(0.60\) | 1e-6 abs. |
| \(C_{pr}\) | \(F_y = 345\ \text{MPa}\), \(F_u = 450\ \text{MPa}\) | \(C_{pr} = 1.1522 \le 1.2\) | 1e-4 abs. |
| Placa base | \(P_u = 2.0\ \text{MN}\), \(f'_c = 28\ \text{MPa}\), \(A_1 = 0.09\ \text{m}^2\), \(A_2 = 0.36\ \text{m}^2\) | \(\phi_cP_p = 2.7846\ \text{MN}\), D/C \(= 0.718\) | 0.1 % rel. |
| Pares \(\phi\)–\(\Omega\) | \(\phi \in \{0.90,\ 0.85,\ 0.75,\ 0.65\}\) | \(\Omega \in \{1.67,\ 1.76,\ 2.00,\ 2.31\} = 1.5/\phi\) | 1e-2 abs. |

Además: paridad obligatoria contra el AISC *Steel Construction Manual* (16.ª ed.) para tres perfiles W de la biblioteca y contra los ejemplos resueltos del *Seismic Design Manual* para SMF y SCBF.

## Errores frecuentes y trampas

1. Usar \(A_g\) en la rotura y \(A_e\) en la fluencia: la fluencia gobierna sobre la sección **bruta** y la rotura sobre la **neta efectiva**.
2. Calcular \(A_n\) con \(d_b\) en lugar de \(d_e = d_b + 2\ \text{mm}\), u omitir el término \(s^2/4g\) (o aplicarlo con \(s\) y \(g\) de líneas distintas).
3. Aplicar \(U = 1-\bar{x}/L\) con la longitud de toda la barra en vez de la longitud de la conexión.
4. Elegir la rama \(0.877F_e\) por la esbeltez aparente sin comparar \(F_e\) contra \(0.44F_y\) (o \(KL/r\) contra \(4.71\sqrt{E/F_y}\)).
5. Tomar \(C_b > 1.0\) con el diagrama de toda la viga en lugar del segmento entre puntos arriostrados.
6. Calcular \(L_r\) con \(r_y\) en vez de \(r_{ts}\), o con \(c \ne 1.0\) en secciones I doblemente simétricas.
7. Olvidar el tope \(M_n \le 1.6F_yS_y\) en flexión de eje débil.
8. Interpolar entre las dos ramas de §H1 en \(P_r/P_c = 0.2\): son discontinuas y la rama se selecciona por condición.
9. Calcular \(\Omega = 1.5/\phi\) dentro del código en vez de leer el valor publicado (\(\Omega_c = 1.76\) para elementos esbeltos, no \(1.765\)).
10. Mezclar solicitaciones de primer orden con la interacción §H1 sin aplicar el cap. C (cargas nocionales y \(\tau_b\)).
11. Diseñar conexiones sísmicas con \(F_y\) en vez de \(R_yF_y\), o con \(M_p = F_yZ\) en vez de \(M_{pr} = C_{pr}R_yF_yZ\).
12. Usar una conexión precalificada de AISC 358 fuera de sus límites (peralte, peso, luz/peralte, panel) sin recalificación.
13. Reducir el panel de nudo con \(\phi_v = 0.90\) cuando AISC 341 permite \(\phi_v = 1.00\), u omitir el factor \(1.9-1.2P_r/P_c\).
14. Confundir \(C_a\) (relación axial de la Tabla D1.1) con \(C_b\) (coeficiente de pandeo lateral-torsional).
15. Mezclar la biblioteca de perfiles en in/lb con el modelo en SI sin una conversión única en el borde, y redondear \(A_n\) o \(F_{cr}\) antes de la comprobación final.
16. Reportar un D/C sin declarar la combinación, el método (LRFD/ASD) y el nivel de análisis que lo produjo.

## Interfaz de salida

Por elemento y por segmento no arriostrado, el programa reporta:

- Solicitaciones \(P_r\), \(M_{rx}\), \(M_{ry}\), \(V_r\) con su combinación gobernante y el nivel de análisis (primer o segundo orden).
- Estado límite que gobierna, \(R_n\) con unidades, \(\phi\) o \(\Omega\), y la cita (norma, edición, artículo) de cada valor.
- Intermedios auditables: \(A_n\), \(A_e\), \(U\), \(C_b\), \(L_p\), \(L_r\), \(F_e\), \(F_{cr}\), \(C_{v1}\), \(C_{pr}\) y la rama de §H1 utilizada.
- Relación demanda/capacidad y envolvente por combinación, con el elemento crítico resaltado.
- Avisos: \(KL/r > 200\), \(h/t_w\) fuera del rango implementado, sección fuera de los límites de precalificación, dato normativo faltante (chequeo bloqueado) y versión del archivo de datos.
- Trazabilidad: `source` y `verified_on` de cada tabla consumida.

## Referencias

1. AISC 360-22, *Specification for Structural Steel Buildings*, American Institute of Steel Construction, 2022.
2. AISC 341-22, *Seismic Provisions for Structural Steel Buildings*, AISC, 2022.
3. AISC 358-22, *Prequalified Connections for Special and Intermediate Steel Moment Frames for Seismic Applications*, AISC, 2022.
4. AISC, *Steel Construction Manual*, 16.ª ed. (basada en AISC 360-22).
5. AISC Design Guide 1, *Base Plate and Anchor Rod Design*, 2.ª ed.
6. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures* — combinaciones de carga y \(\Omega_0\).
7. T. V. Galambos (ed.), *Guide to Stability Design Criteria for Metal Structures*, 6.ª ed., Wiley, 2010 — respaldo del pandeo lateral-torsional.
8. AISC, *Seismic Design Manual*, 3.ª ed. — ejemplos resueltos de SMF y SCBF usados como contraste.

## Registro de verificación

- **Verificado**: los pares \(\phi\)–\(\Omega\) de tracción, compresión, flexión, corte y aplastamiento sobre concreto con su invariante \(\Omega = 1.5/\phi\); las formas de \(P_n\) por fluencia y rotura, \(A_e = UA_n\) y la rotura por bloque; \(F_e\), \(F_{cr}\) y la transición \(4.71\sqrt{E/F_y}\); \(M_p\), \(L_p\), \(L_r\), \(r_{ts}\), \(c\), las tres ramas de \(M_n\) y \(C_b\); \(V_n = 0.6F_yA_wC_{v1}\); las dos ramas de §H1; \(M_{pr}\) y \(C_{pr}\); \(R_y\), \(R_t\) de A992, A36 y A500; los límites ancho-espesor de sección I; y §J8.
- **Pendiente**: contraste línea a línea contra las ediciones impresas 2022 (numeración de artículos), transcripción de las Tablas D3.1, B4.1a/b, A-3.1 y D1.1 completas, límites de precalificación de AISC 358-22, factores \(\beta\) y \(\omega\) de BRBF y el refinamiento \(\lambda n'\) de la placa base.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia licenciada de AISC 360-22, 341-22 y 358-22; cada valor cerrado se registra en `data/aisc/*.json` con `verified_on` antes de pasar la skill a `ready`.
