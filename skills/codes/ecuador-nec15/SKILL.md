---
name: ecuador-nec15
description: >-
  Implementa y verifica el análisis y el diseño sismorresistente de la NEC-15 de
  Ecuador (NEC-SE-DS, con NEC-SE-HM para hormigón armado y NEC-SE-MP para
  mampostería): Z por zonas I a VI, perfiles de suelo A a F, coeficientes Fa, Fd
  y Fs, espectro elástico con η, T0, Tc, TL y exponente r, espectro de diseño con
  R, I, φP y φE, método estático equivalente (Ta, k, torsión accidental, Ax,
  P-Δ), análisis dinámico modal con ajuste del cortante basal y derivas
  inelásticas ΔM = 0.75 R ΔE. Úsala cuando el proyecto declare NEC-15, cuando haya
  que construir el espectro de una zona sísmica ecuatoriana, cuando se audite un
  módulo que aplique Cd o el 0.7R de otro código, o cuando se verifiquen derivas,
  torsión, P-Δ y el R del sistema estructural.
metadata:
  track: codes
  jurisdiction: ECU
  edition: "NEC-15 (SE-DP y SE-HM)"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Ecuador — NEC-15: peligro sísmico, diseño sismorresistente y hormigón armado

## Cuándo usar esta skill

- El proyecto declara `code = NEC-15` (Ecuador) y hay que fijar \(Z\), el perfil de suelo, el espectro \(S_a(T)\) de la zona I–VI y el cortante basal \(V\).
- Hay que ejecutar el DBF (diseño basado en fuerzas): estático, obligatorio como mínimo para toda estructura, o dinámico espectral, obligatorio en irregulares, con el ajuste del cortante basal.
- Hay que verificar derivas inelásticas \(\Delta_M = 0.75R\Delta_E\), la amplificación torsional \(A_x\), el índice de estabilidad \(Q_i\) y la torsión accidental del 5 %.
- Hay que auditar un módulo ya escrito: el defecto típico es arrastrar \(C_d\), \(\Omega_0\), el 0.7R o la rama \(1/T^2\) posterior a \(T_L\) de otro código a un modelo ecuatoriano.
- Hay que aplicar los requisitos de NEC-SE-HM o NEC-SE-MP que condicionan el \(R\) elegido y los límites de pisos.

**No usar** para otro país (→ `codes/code-crosswalk-and-extension`), para el DBD de desplazamientos (§7 de NEC-SE-DS), para cargas no sísmicas (NEC-SE-CG), acero estructural (NEC-SE-AC), estructuras existentes (NEC-SE-RE), ni para puentes, puertos y tanques (§9, que remiten a AASHTO y PIANC).

## Alcance y límites

Cubre NEC-SE-DS: peligro sísmico (§3.1–3.2), espectros elásticos de aceleraciones y desplazamientos (§3.3), componente vertical y combinación direccional (§3.4–3.5), categoría de edificio y coeficiente \(I\) (§4.1), límites de deriva (§4.2.2), irregularidades \(\phi_P\) y \(\phi_E\) (§5.2.3) y el método 1 DBF completo (§6) con sus procedimientos dinámicos (§6.2.2). De NEC-SE-HM cubre el diseño sísmico del hormigón armado (§2.3, §2.4, §6.1) y de NEC-SE-MP la mampostería estructural (§2.1, §3.2, §4.1).

**Nomenclatura**: el módulo sísmico se publica como **NEC-SE-DS** ("Peligro sísmico y diseño sismo resistente"); el rótulo `SE-DP` del catálogo del proyecto no corresponde a ningún documento de la edición 2015, y la mampostería no está en `SE-HM` sino en **NEC-SE-MP**.

> ⚠️ VERIFICAR: la equivalencia entre los rótulos internos (`SE-DP`, `SE-HM`) y los códigos oficiales de los documentos 2015, y la existencia de una edición posterior que renumere los módulos. Se comprueba en el listado oficial de módulos NEC vigente (MIDUVI/MIT) y en la tabla de datos habilitantes de cada PDF. El programa lee el mapeo de `data/ecuador/nec15/meta.json` (`code_id`, `documents[]`, `verified_on`).

Queda fuera la microzonificación municipal (que **sustituye** \(F_a, F_d, F_s\) y \(S_a\) cuando existe, §10.5.3), el aislamiento y los disipadores (§8), el DBD (§7) y NEC-SE-VIVIENDA.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Provincia, cantón, parroquia y microzonificación vigente | sí | bloquear: \(Z\) no se estima a ojo del mapa |
| Zona sísmica I–VI, valor de \(Z\) y región para \(\eta\) | sí | leer de la tabla de poblaciones o del polígono versionado; sin dato, bloquear |
| Perfil de suelo A–F con \(V_s\), \(N\) o \(S_u\) de los 30 m superiores | sí | bloquear; perfil F exige estudio de sitio |
| Categoría de uso e \(I\); sistema estructural y su \(R\) (Tablas 15/16) | sí | bloquear: definen \(V\) y los límites de pisos |
| Regularidad en planta y elevación (\(\phi_P,\phi_E\)) | sí | evaluar con Tablas 13/14; nunca suponer 1.0 |
| Masas y alturas por piso; carga reactiva \(W\) | sí | bloquear |
| Inercias agrietadas de vigas, columnas y muros | sí en HA y mampostería | bloquear: sin ellas la deriva no es verificable |

Ningún dato faltante se sustituye por un valor por defecto silencioso (`codes/code-crosswalk-and-extension`).

## Fundamento y formulación

### 1. Peligro sísmico: \(Z\), \(\eta\) y perfiles de suelo

\(Z\) es la aceleración máxima en roca esperada para el sismo de diseño, como fracción de \(g\), con 10 % de probabilidad de excedencia en 50 años (\(T_r = 475\) años). Zonas I a VI: \(Z = 0.15, 0.25, 0.30, 0.35, 0.40\) y \(\ge 0.50\), saturada en el litoral (NEC-SE-DS, §3.1.1, Tabla 1). La zona se fija con la tabla de poblaciones del apéndice 10.2 (población/parroquia/cantón/provincia) o con el polígono del mapa (Figura 1).

Perfiles de suelo (Tabla 2): A roca competente \(V_s \ge 1500\ \text{m/s}\); B roca de rigidez media \(1500 > V_s \ge 760\ \text{m/s}\); C muy densos o roca blanda \(760 > V_s \ge 360\ \text{m/s}\), o \(N \ge 50\), o \(S_u \ge 100\ \text{kPa}\); D suelos rígidos \(360 > V_s \ge 180\ \text{m/s}\), o \(50 > N \ge 15\), o \(100 > S_u \ge 50\ \text{kPa}\); E suelos blandos \(V_s < 180\ \text{m/s}\), o \(IP > 20\) con \(w \ge 40\%\) y \(S_u < 50\ \text{kPa}\) en \(H > 3\ \text{m}\); F suelos especiales (F1 licuables, F2 turba, F3 arcillas \(IP > 75\), F4 gran espesor, F5 contraste de impedancia, F6 relleno no controlado), **sin coeficientes tabulados** y con estudio de sitio obligatorio (§10.5.4).

\(\eta\) es la **razón espectral regional** \(S_a(T = 0.1\ \text{s})/\text{PGA}\), no un factor de sitio: 1.80 en la Costa (excepto Esmeraldas), 2.48 en la Sierra, Esmeraldas y Galápagos y 2.60 en el Oriente (§3.3.1).

> ⚠️ VERIFICAR: la geometría de los polígonos de la Figura 1 y la tabla completa de poblaciones del apéndice 10.2 no se transcriben aquí. Se comprueban en el documento oficial y el programa los lee de `data/ecuador/nec15/zones.json` (`polygons`, `localities[]`, cada entrada con `source` y `verified_on`).

### 2. Coeficientes de sitio y espectro elástico de aceleraciones (§3.2.2, §3.3.1)

Perfiles A y B: \(F_a = 0.9\) y \(1.0\); \(F_d = 0.9\) y \(1.0\); \(F_s = 0.75\) en ambos, en todas las zonas. Perfiles C, D y E, con las zonas entre paréntesis:

| Perfil | I (0.15) | II (0.25) | III (0.30) | IV (0.35) | V (0.40) | VI (\(\ge0.50\)) |
|---|---|---|---|---|---|---|
| C: \(F_a\)/\(F_d\)/\(F_s\) | 1.40/1.36/0.85 | 1.30/1.28/0.94 | 1.25/1.19/1.02 | 1.23/1.15/1.06 | 1.20/1.11/1.11 | 1.18/1.06/1.23 |
| D: \(F_a\)/\(F_d\)/\(F_s\) | 1.60/1.62/1.02 | 1.40/1.45/1.06 | 1.30/1.36/1.11 | 1.25/1.28/1.19 | 1.20/1.19/1.28 | 1.12/1.11/1.40 |
| E: \(F_a\)/\(F_d\)/\(F_s\) | 1.80/2.10/1.50 | 1.40/1.75/1.60 | 1.25/1.70/1.70 | 1.10/1.65/1.80 | 1.00/1.60/1.90 | 0.85/1.50/2.00 |

\(F_a\) amplifica las ordenadas de período corto, \(F_d\) las del espectro de desplazamientos y \(F_s\) corrige el comportamiento no lineal del subsuelo y la degradación del período del sitio; para un \(PGA\) entre \(0.15\,g\) y \(0.50\,g\) distinto de los tabulados se interpola linealmente con \(PGA = Z\). \(S_a\) se publica **como fracción de \(g\)** (se declara: no se mezcla con \(\text{m/s}^2\)) y \(T\) va en s:

$$S_a(T) = \eta Z F_a \quad (0 \le T \le T_c); \qquad S_a(T) = \eta Z F_a \left(\frac{T_c}{T}\right)^{r} \quad (T > T_c)$$

$$T_0 = 0.11\,F_s\frac{F_d}{F_a}, \qquad T_c = 0.55\,F_s\frac{F_d}{F_a}, \qquad T_L = 2.4\,F_d \quad (\le 4.0\ \text{s en perfiles D y E})$$

con \(r = 1.0\) y \(r = 1.5\) **solo en perfil E**. El espectro **solo tiene dos ramas**: meseta \(\eta Z F_a\) hasta \(T_c\) y decaimiento \((T_c/T)^r\) después; no existe rama \(1/T^2\) posterior a \(T_L\) ni rampa inicial de meseta. La rampa de período corto \(S_a = ZF_a[1+(\eta-1)T/T_0]\) para \(T \le T_0\) se usa **únicamente** en análisis dinámico y para modos distintos del fundamental; en \(T = T_0\) empalma con la meseta (\(ZF_a\eta\)).

Espectro elástico de desplazamientos (m): \(S_d = S_a g (T/2\pi)^2\) para \(0 \le T \le T_L\) y \(S_d = S_a g (T_L/2\pi)^2\) para \(T > T_L\) (§3.3.2). Amortiguamiento de referencia 5 % del crítico; \(g = 9.80665\ \text{m/s}^2\).

### 3. Cortante basal de diseño y factor \(R\) (§6.3.2, §6.3.4)

$$V = \frac{I\,S_a(T_a)}{R\,\phi_P\,\phi_E}\,W$$

\(W\) es la carga reactiva (\(W = D\) en el caso general; \(W = D + 0.25L_i\) en bodegas y almacenaje, §6.1.7), expresada como fuerza. \(R\) reduce la demanda por sistema estructural (Tablas 15 y 16) y \(\phi_P = \phi_{PA}\phi_{PB}\), \(\phi_E = \phi_{EA}\phi_{EB}\) son coeficientes de configuración que **reducen** \(R\) y por tanto **aumentan** la demanda: cada irregularidad tipificada vale 0.9 y la estructura regular 1.0 (§5.2.3). Con varios sistemas se toma el menor \(R\); los sistemas de ductilidad limitada no se admiten si \(I > 1\) ni por encima de sus límites de pisos.

| Sistema estructural (Tablas 15 y 16) | \(R\) |
|---|---|
| Dúctiles: pórticos especiales de HA con vigas descolgadas; pórticos especiales de acero laminado en caliente o de placas; pórticos con columnas de HA y vigas de acero; sistemas duales (pórticos especiales + muros de HA o diagonales) | 8 |
| Dúctiles: pórticos especiales de HA con vigas banda, con muros o diagonales | 7 |
| Dúctiles: muros estructurales dúctiles de HA; pórticos especiales de HA con vigas banda | 5 |
| Ductilidad limitada: HA con secciones menores a NEC-SE-HM (viviendas \(\le2\) pisos, luces \(\le5\) m); mampostería reforzada o confinada \(\le2\) pisos; muros de HA \(\le4\) pisos | 3 |
| Ductilidad limitada: HA con armadura electrosoldada; acero conformado en frío, aluminio o madera \(\le2\) pisos | 2.5 |
| Ductilidad limitada: mampostería no reforzada, 1 piso | 1 |

La tabla completa, con los textos literales de cada tipología y sus límites de altura, se lee de `data/ecuador/nec15/systems.json`.

### 4. Período, distribución de fuerzas y torsión (§6.3.3, §6.3.5–6.3.7)

Método 1: \(T = C_t h_n^{\alpha}\), con \(h_n\) la altura máxima en m desde la base; \(C_t\) y \(\alpha\): acero sin arriostramientos 0.072 y 0.80; acero con arriostramientos 0.073 y 0.75; pórticos especiales de HA sin muros ni diagonales rigidizadoras 0.055 y 0.90; con muros estructurales o diagonales, y otras estructuras basadas en muros y mampostería, 0.055 y 0.75. Método 2: análisis modal o la fórmula de Rayleigh \(T_a = 2\pi\sqrt{\sum w_i\delta_i^2/(g\sum f_i\delta_i)}\), con \(f_i\) una distribución racional de fuerzas y \(\delta_i\) las deflexiones elásticas correspondientes; el método 2 **no puede exceder en 30 %** al método 1 y, una vez dimensionada la estructura, se repite el cálculo hasta que la variación entre iteraciones sea \(\le 10\) %.

$$F_x = \frac{w_x h_x^k}{\sum_i w_i h_i^k}\,V, \qquad k=\begin{cases}1 & T \le 0.5\ \text{s}\\ 0.75+0.50\,T & 0.5 < T \le 2.5\ \text{s}\\ 2 & T > 2.5\ \text{s}\end{cases}$$

**Torsión accidental** (§6.3.6): la masa de cada nivel se concentra en el centro de masas y se desplaza el **5 % de la máxima dimensión del piso medida perpendicularmente a la dirección de aplicación** de las fuerzas; el efecto entra en la distribución del cortante de piso y en los momentos torsionales, en estructuras regulares e irregulares (en modelos 3D, re-localización de masas). **Amplificación torsional** (§6.3.7), con irregularidad torsional: \(A_x = (\delta_{max}/(1.2\,\delta_{prom}))^2 \le 3.0\), con \(\delta_{prom}\) el promedio de los desplazamientos de los puntos extremos del nivel y \(\delta_{max}\) el máximo; amplifica la torsión accidental de cada nivel.

### 5. P-Δ y control de derivas (§6.3.8, §6.3.9, §4.2.2, §6.1.6-b)

\(Q_i = P_i\Delta_i/(V_i h_i)\), con \(P_i\) la carga vertical **sin mayorar** del piso \(i\) y todos los superiores, \(\Delta_i\) la deriva del piso en el centro de masas, \(V_i\) el cortante sísmico y \(h_i\) la altura. Debe cumplirse \(Q_i \le 0.30\): por encima hay inestabilidad potencial y se rigidiza o se demuestra estabilidad por procedimientos más estrictos. Si \(0.1 < Q_i < 0.3\), derivas, fuerzas internas y momentos por cargas laterales se multiplican por \(f_{P\Delta} = 1/(1-Q_i)\).

\(\Delta_M = 0.75\,R\,\Delta_E\), con \(\Delta_E\) la deriva elástica de las fuerzas de diseño ya reducidas por el DBF, incluyendo efectos traslacionales, torsionales y P-Δ. Límites (Tabla 7): \(\Delta_M \le 0.02\) en hormigón armado, estructuras metálicas y madera; \(\Delta_M \le 0.01\) en mampostería; se verifican en **todas** las columnas del edificio. Rigideces (§6.1.6-b): \(0.5I_g\) en vigas (con la losa si es monolítica), \(0.8I_g\) en columnas y \(0.6I_g\) en muros estructurales —dos primeros pisos, más el primer subsuelo si existe, y nunca en una altura menor que la longitud en planta del muro—; en mampostería, \(0.5I_g\) si altura/longitud \(> 3\), sin reducción si es \(< 1.5\) e interpolación lineal entre ambos.

### 6. Análisis dinámico modal (§6.2.2)

Se usa el espectro **elástico** de §3.3.1 y se incluyen todos los modos que aporten al menos el **90 % de la masa modal acumulada** en cada dirección horizontal principal; en modelos 3D la combinación debe considerar la interacción modal (CQC). Al reducir las fuerzas dinámicas elásticas para diseño se aplican \(R\), \(I\), \(\phi_P\) y \(\phi_E\), sin bajar del cortante elástico dividido por \(R\) (§6.2.2-e). El cortante dinámico total en la base no debe ser menor que el **80 %** del cortante estático \(V\) en estructuras regulares ni que el **85 %** en irregulares (§6.2.2-b), y el factor se aplica a **toda** la respuesta (fuerzas, momentos y derivas).

> ⚠️ VERIFICAR: la referencia exacta del cociente 80 %/85 % (si compara el cortante dinámico ya reducido por \(I/(R\phi_P\phi_E)\) contra el \(V\) de §6.3.2, o el cortante elástico contra ese \(V\)) no es unívoca entre §6.2.2-b y §6.2.2-e. Se comprueba en el texto oficial y en una memoria de cálculo de contraste; el programa lee `modal_scale_reference` (`"design"` o `"elastic"`) de `data/ecuador/nec15/modal.json` y reporta ambos cortantes.

### 7. Requisitos de NEC-SE-HM y NEC-SE-MP que condicionan el análisis

**Hormigón armado (NEC-SE-HM, §2.3, §2.4, §3.3, §5.7, §6.1).** Los elementos cumplen el ACI 318 más reciente y su capítulo 21; el diseño sísmico sigue NEC-SE-DS con **diseño por capacidad**: rótulas plásticas en extremos de vigas, base de columnas del primer piso y base de muros, con columna fuerte, nudo fuerte y viga fuerte a corte pero débil en flexión. \(f'_c \ge 21\ \text{MPa}\) en hormigón normal (máximo 35 MPa en liviano); \(f_y\) de diseño \(\le 550\ \text{MPa}\) y, si \(f_y > 420\ \text{MPa}\), la fluencia se toma en \(\varepsilon_t = 0.0035\); \(\rho_{min} = f'_c/(4f_y) > 1.4/f_y\); \(\beta_1 = 0.85\) para \(f'_c \le 28\ \text{MPa}\), decreciendo 0.05 cada 7 MPa y nunca bajo 0.65. Vigas banda con peralte \(\ge 25\ \text{cm}\); los muros con \(M/(V l_w) \ge 2\) se diseñan a flexión con una envolvente bilineal de momentos amplificada por la sobrerresistencia de la rótula en la base.

> ⚠️ VERIFICAR: los coeficientes literales de la envolvente de muros \(M^\circ_{0.5H} = C_{1,T}\phi^\circ M_B\), con \(C_{1,T} = 0.4 + 0.0?\,T_i(\mu/\phi^\circ-1) \ge 0.4\) (NEC-SE-HM §6.1.2), no se leyeron sin ambigüedad del PDF. Se comprueban en el ejemplar oficial; hasta entonces el programa lee `wall_moment_envelope` de `data/ecuador/nec15/hm_walls.json` con `source` y `verified_on` y **no** lo codifica.

**Mampostería (NEC-SE-MP, §2.1, §3.2, §3.3, §4.1).** Alcance: mampostería simple, armada y confinada de hasta 4 pisos. Morteros de pega M20, M15, M10, M5 y M2.5 por resistencia mínima a 28 días (MPa) y dosificación en volumen; mortero de relleno con \(1.2f'_m \le f'_cr \le 1.5f'_m\) y \(f'_cr \ge 10\ \text{MPa}\). Refuerzo longitudinal en celdas: diámetro \(\ge 10\ \text{mm}\) (\(\le 25\ \text{mm}\) si el muro tiene \(\ge 200\ \text{mm}\) nominales, \(\le 20\ \text{mm}\) si menos), una barra por celda salvo celdas \(> 140\ \text{mm}\) (dos barras \(\le 16\ \text{mm}\)); recubrimiento de mortero \(\ge 13\ \text{mm}\); refuerzo de tendel \(\ge 4\ \text{mm}\) y \(\le\) la mitad del espesor del tendel. Diseño por estado límite de resistencia o por esfuerzos admisibles.

## Procedimiento

1. Resolver ubicación → zona sísmica y \(Z\) con la tabla de poblaciones o el polígono versionado; usar la microzonificación cuando exista.
2. Clasificar el perfil A–F con \(V_s\), \(N\) y \(S_u\) de los 30 m superiores; detener si es F.
3. Leer \(F_a\), \(F_d\), \(F_s\) (interpolando en \(Z\) si el \(PGA\) no coincide con la tabla), fijar \(\eta\) por región y \(r\) por perfil, calcular \(T_0\), \(T_c\) y \(T_L\) con el tope de 4 s en D y E, y construir \(S_a(T)\) comprobando la continuidad en \(T_0\) y \(T_c\).
4. Asignar \(I\), \(R\) y \(\phi_P,\phi_E\); verificar que los sistemas de ductilidad limitada cumplen sus límites de pisos y \(I = 1\).
5. Calcular \(T_a\) (método 1 o período modal) con el tope del 30 % respecto del método 1.
6. Calcular \(V\), distribuirlo con \(F_x\) y \(k\), y aplicar la torsión accidental del 5 % y \(A_x\).
7. Resolver. Si la estructura es irregular, ejecutar además el análisis dinámico espectral y ajustar el cortante basal (80 %/85 %) sobre toda la respuesta.
8. Iterar secciones y recalcular \(T\) hasta variación \(\le 10\) % entre iteraciones.
9. Calcular \(Q_i\), aplicar \(f_{P\Delta}\) donde corresponda y verificar \(\Delta_M\) contra 0.02 o 0.01 en todas las columnas.
10. Emitir el informe con la envolvente, la cita de cada coeficiente y las advertencias activas.

## Implementación en la plataforma

```python
# opensees_studio/core/codes/ecuador_nec15.py   (core puro: sin Qt, sin OpenSeesPy)
def zone_factor(location, code_data) -> "ZoneFactor":        # Z: Tabla 19 o microzonificacion
def site_coefficients(z, profile, code_data) -> tuple[float, float, float]:
    """(Fa, Fd, Fs) de data/ecuador/nec15/site_factors.json (Tablas 3-5); F -> SiteStudyRequired."""
def spectrum_periods(fa, fd, fs, profile) -> tuple[float, float, float]:   # (T0, Tc, TL); tope 4 s en D/E
def elastic_spectrum(z, fa, fd, fs, eta, r, t=None, *, higher_mode=False) -> "Spectrum":
    """Sa(T) como fraccion de g; higher_mode=True usa la rampa T <= T0 (3.3.1)."""
def base_shear(sa_ta, w, r, i=1.0, phi_p=1.0, phi_e=1.0) -> float:        # V = I*Sa*W/(R*phiP*phiE)
def approximate_period(ct, alpha, hn) -> float: ...
def vertical_exponent(t) -> float: ...                        # k (6.3.5)
def accidental_torsion(floor, direction) -> float: ...        # 0.05 x dimension perpendicular (6.3.6)
def torsional_amplification(d_max, d_prom) -> float: ...      # Ax <= 3.0 (6.3.7)
def stability_index(p_i, delta_i, v_i, h_i) -> float: ...     # Qi (6.3.8)
def drift_amplification(qi) -> float: ...                     # 1/(1-Qi) si 0.1 < Qi < 0.3
def inelastic_drift(r, delta_e) -> float: ...                 # 0.75*R*dE (6.3.9)
def modal_base_shear_scale(v_static, v_modal, regular) -> float: ...   # 0.80/0.85 sobre toda la respuesta
def cracked_inertia(element, material) -> float: ...          # 0.5 / 0.8 / 0.6 Ig (6.1.6-b)
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):

- El módulo vive en `core/codes/` e implementa el protocolo `SeismicCode` (`code_id = "ecu-nec15"`, `edition`, `documents`); **no** importa Qt ni OpenSeesPy.
- Todos los coeficientes regulados (\(Z\), \(\eta\), \(F_a\), \(F_d\), \(F_s\), \(I\), \(R\), \(\phi\), \(C_t\), \(\alpha\), \(k\), límites de deriva, tope de \(T_L\)) vienen de `data/ecuador/nec15/*.json` (`zones`, `site_factors`, `systems`, `irregularities`, `drift`, `torsion`, `modal`, `materials`); cada entrada lleva `value`, `unit`, `source` (norma, edición, tabla o sección) y `verified_on`.
- El espectro, \(R\) y \(\Delta_M\) son funciones puras; las inercias agrietadas se aplican en el modelo antes de resolver, no se corrigen después sobre los desplazamientos.
- Solo `services/` habla con el solver: `services/spectrum.py` consume estas funciones y el caso modal corre en el proceso hijo de `run.py` (un único `ops.eigen` ARPACK por proceso).
- Errores tipificados: `MissingHazardData`, `MissingSiteProfile`, `SiteStudyRequired` (perfil F), `MissingCodeData`, `ForbiddenSystemForImportance`, `StabilityIndexExceeded`; ninguno se degrada a un valor por defecto.
- Unidades: NEC-15 publica \(W\) en kN y \(M\) en kN·m; la plataforma usa SI coherente (N, m, kg, s, Pa) y convierte en la frontera. \(S_a\) permanece como fracción de \(g\) y solo se multiplica por \(g = 9.80665\ \text{m/s}^2\) al pasar a \(S_d\).

## Datos normativos

| Dato | Origen | Estado |
|---|---|---|
| Zonas I–VI y \(Z\) (0.15 … \(\ge0.50\)); saturación a 0.50 g del litoral; \(T_r=475\) años | NEC-SE-DS, §3.1.1, Tabla 1 | verificado en el PDF |
| Perfiles A–F y umbrales de \(V_s\), \(N\), \(S_u\); \(F_a\) (Tabla 3), \(F_d\) (Tabla 4), \(F_s\) (Tabla 5) | NEC-SE-DS, §3.2.1 y §3.2.2 | verificado, valor por valor |
| \(\eta = 1.80/2.48/2.60\) y \(r=1.0\)/\(1.5\) en E; \(T_0=0.11F_sF_d/F_a\), \(T_c=0.55F_sF_d/F_a\), \(T_L=2.4F_d\) (\(\le4\) s en D y E); dos ramas, rampa solo para modos superiores y \(S_d=S_ag(T/2\pi)^2\) | NEC-SE-DS, §3.3.1 y §3.3.2 | verificado |
| \(E_v \ge \tfrac{2}{3}E_h\); \(F_{rev}=\tfrac{2}{3}I(\eta ZF_a)W_p\); \(E_h=\mp\sqrt{E_x^2+E_y^2}\); \(I\): 1.5 esencial, 1.3 ocupación especial, 1.0 otras | NEC-SE-DS, §3.4.2, §3.4.4, §3.5 y §4.1 (Tabla 6) | verificado |
| \(\Delta_M\) máxima 0.02 (HA, acero, madera) y 0.01 (mampostería); \(\phi_{Pi} = \phi_{Ei} = 0.9\) por tipo y \(\phi_P=\phi_{PA}\phi_{PB}\), \(\phi_E=\phi_{EA}\phi_{EB}\) | NEC-SE-DS, §4.2.2 (Tabla 7) y §5.2.3 (Tablas 13 y 14) | verificado en el texto; Figuras → `irregularities.json` |
| \(W=D\) y \(W=D+0.25L_i\) en bodegas; \(C_t\), \(\alpha\) y tope \(1.3T_{m1}\); \(V=I S_a(T_a)W/(R\phi_P\phi_E)\); \(F_x\) con \(k=1\) / \(0.75+0.5T\) / \(2\); \(R\) dúctiles 8, 8, 8, 8, 7, 5, 5 | NEC-SE-DS, §6.1.7, §6.3.2–§6.3.5, Tablas 15 y 16 | verificado; tabla literal → `systems.json` |
| Torsión accidental del 5 % de la máxima dimensión perpendicular; \(A_x=(\delta_{max}/1.2\delta_{prom})^2\le3.0\); \(Q_i\le0.30\); \(f_{P\Delta}=1/(1-Q_i)\) si \(0.1<Q_i<0.3\); \(\Delta_M=0.75R\Delta_E\); inercias 0.5/0.8/0.6 \(I_g\) | NEC-SE-DS, §6.3.6–§6.3.9 y §6.1.6-b | verificado |
| 90 % de masa modal; reducción dinámica no menor que \(V_{el}/R\); ajuste 80 %/85 % | NEC-SE-DS, §6.2.2 | verificado salvo la referencia del 80 %/85 % → `VERIFICAR` |
| ACI 318 vigente y cap. 21; \(f'_c\ge21\) MPa; \(f_y\le550\) MPa; \(\rho_{min}\); \(\beta_1\) | NEC-SE-HM, §2.3.1, §3.3 y §4.2 | verificado |
| Morteros M20–M2.5; \(1.2f'_m\le f'_cr\le1.5f'_m\); diámetros y recubrimientos | NEC-SE-MP, §3.2, §3.3 y §4.1 | verificado |
| Polígonos del mapa y tabla de poblaciones completa; coeficiente \(C_{1,T}\) de muros | NEC-SE-DS, Figura 1 y apéndice 10.2; NEC-SE-HM, §6.1.2 | **VERIFICAR** → `zones.json`, `hm_walls.json` |

## Verificación y casos de prueba

| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Períodos, perfil D, zona V | \(F_a=1.2\), \(F_d=1.19\), \(F_s=1.28\) | \(T_0=0.1396267\) s, \(T_c=0.6981333\) s, \(T_L=2.856\) s | 1e-9 | §3.3.1 |
| Meseta | \(Z=0.40\), perfil D, \(\eta=2.48\), \(T=0.30\) s | \(S_a=1.1904\,g\) | 1e-9 | §3.3.1 |
| Empalme rampa–meseta | Rampa evaluada en \(T=T_0\) | \(S_a=0.40\times1.2\times2.48=1.1904\,g\) | 1e-9 | §3.3.1 |
| Rama descendente | \(T=1.0\) s, mismos datos | \(S_a=0.83105792\,g\) | 1e-6 rel. | §3.3.1 |
| Perfil E con \(r=1.5\) | Zona V, E (\(F_a=1.0\), \(F_d=1.6\), \(F_s=1.9\)), \(T=2.0\) s | \(T_c=1.672\) s; \(S_a=0.7582651362\,g\) | 1e-6 rel. | §3.3.1 |
| Tope de \(T_L\) | Zona I, perfil E, \(F_d=2.1\) | \(2.4F_d=5.04\ \text{s} \to T_L=4.00\ \text{s}\) | 1e-9 | §3.3.1 |
| Perfil F | Cualquier \(Z\), perfil F | `SiteStudyRequired`, sin \(F_a,F_d,F_s\) | exacto | §3.2.2, §10.5.4 |
| Período aproximado | Pórtico especial de HA sin muros, \(h_n=24\) m | \(T_a=0.055\times24^{0.9}=0.9606226\) s | 1e-6 rel. | §6.3.3 |
| Cortante basal | \(S_a=0.8310579\), \(W=10\,000\) kN, \(R=8\), \(I=\phi=1\) | \(V=1038.8224\) kN; con \(\phi_P=\phi_E=0.9\), \(V=1282.4968\) kN | 1e-6 rel. | §6.3.2 |
| Torsión accidental y \(A_x\) | Planta de 20 m × 12 m, fuerza en \(x\); \(\delta_{max}=0.012\) m, \(\delta_{prom}=0.008\) m | \(e_{acc}=0.05\times12=0.60\) m; \(A_x=(0.012/0.0096)^2=1.5625\le3\) | 1e-9 / 1e-6 | §6.3.6, §6.3.7 |
| \(Q_i\) y \(f_{P\Delta}\) | \(P=15\,000\) kN, \(\Delta=0.02\) m, \(V=900\) kN, \(h=3\) m | \(Q_i=0.111111\); \(f_{P\Delta}=1.125\) | 1e-6 | §6.3.8 |
| Derivas | \(R=8\) con \(\Delta_E=0.0025\) y con \(\Delta_E=0.0035\); \(R=3\) con \(\Delta_E=0.0035\) | \(\Delta_M=0.015\) (cumple), \(0.021\) (no cumple), \(0.007875\) (mampostería, cumple) | 1e-6 | §6.3.9, Tabla 7 |
| Ajuste modal | \(V_{est}=1000\) kN, \(V_{din}=700\) kN, regular | \(f=0.80\times1000/700=1.142857\), sobre toda la respuesta | 1e-6 | §6.2.2-b |

Contraste externo obligatorio: reproducir un espectro publicado de un proyecto ecuatoriano con zona y perfil conocidos, y un edificio de pórticos con \(T_c\) y deriva verificables a mano. La tabla de poblaciones se prueba valor por valor contra el apéndice 10.2.

## Errores frecuentes y trampas

1. **Inventar ramas o exponentes.** La rama \(1/T^2\) posterior a \(T_L\) (forma ASCE) no existe y subestima \(S_a\) en períodos largos; usar \(r=1\) en perfil E, donde \(r=1.5\), sobreestima \(S_a\) entre \(T_c\) y \(T_L\).
2. **Aplicar la rampa de \(T_0\) al modo fundamental.** \(S_a=ZF_a[1+(\eta-1)T/T_0]\) solo vale para modos distintos del fundamental con \(T\le T_0\); el fundamental usa la meseta \(\eta ZF_a\) hasta \(T_c\).
3. **Confundir \(\eta\) con un factor de sitio.** Depende de la **región** (Costa 1.80, Sierra/Esmeraldas/Galápagos 2.48, Oriente 2.60), no del perfil ni de \(Z\), y no se interpola con el perfil.
4. **Usar \(C_d\), \(\Omega_0\) o un factor de redundancia \(\rho\).** NEC-15 no los tiene: la deriva se amplifica con \(\Delta_M=0.75R\Delta_E\). Importar la mecánica de ASCE 7 produce derivas y fuerzas equivocadas.
5. **Multiplicar \(V\) por \(\phi_P\phi_E\)** en vez de dividir: los coeficientes de configuración penalizan, \(R_{ef}=R\phi_P\phi_E < R\), y el cortante **sube**.
6. **Verificar la deriva con desplazamientos sin \(0.75R\), o con rigidez bruta \(I_g\).** Sin inercias agrietadas (0.5/0.8/0.6) la deriva se subestima 30–40 % y el control pierde sentido.
7. **Usar la dimensión paralela en la torsión accidental.** El desplazamiento del centro de masas es el 5 % de la máxima dimensión **perpendicular** a la dirección de la fuerza, y esa dimensión puede cambiar piso a piso.
8. **Usar \(A_x\) en lugar de la torsión accidental**, sin el tope 3.0, o en estructuras sin irregularidad torsional: es un amplificador de la torsión accidental, no un sustituto.
9. **Manejar mal el análisis modal:** escalar únicamente el cortante basal (el 80 %/85 % va sobre toda la respuesta) o reducir el espectro modal por \(R\) dos veces, o por debajo de \(V_{el}/R\).
10. **Aplicar \(f_{P\Delta}\) cuando \(Q_i<0.1\) o aceptar \(Q_i>0.30\) con amplificación.** Con \(Q_i>0.30\) la norma exige rigidizar o demostrar estabilidad por métodos más estrictos. Asignar \(R\) de sistema dúctil a una estructura de ductilidad limitada, o usar la Tabla 16 con \(I>1\) o por encima de sus límites de pisos (2 pisos en vivienda, 4 en muros de HA), es el mismo tipo de error: elegir el \(R\) sin comprobar sus condiciones.
11. **Mezclar masa con peso.** \(W\) es una carga (fuerza): en OpenSees la masa entra en kg; pasar \(W\) en kN a `mass` sin dividir por \(g\) multiplica el cortante por 9.8.
12. **Leer \(Z\) del mapa a ojo o usar las tablas de sitio donde hay microzonificación.** La zona se fija con la tabla de poblaciones (parroquia/cantón/provincia) y la microzonificación vigente **sustituye** \(F_a,F_d,F_s\) y \(S_a\) (§10.5.3); la zona VI es \(\ge0.50\), saturada.

## Interfaz de salida

Para cada dirección de análisis el programa debe exponer:

- Provincia, cantón y parroquia; zona sísmica, \(Z\) en fracción de \(g\) y su fuente (tabla de poblaciones, polígono o microzonificación), con aviso si la microzonificación sustituye las tablas.
- Perfil de suelo, los parámetros usados para clasificarlo (\(V_s\), \(N\), \(S_u\), profundidad) y su cita; aviso explícito si es F o si la población exige espectro de sitio.
- \(\eta\), \(r\), \(F_a\), \(F_d\), \(F_s\), \(T_0\), \(T_c\) y \(T_L\) con `accel_unit = "g"`, `damping = 0.05` y la tabla de origen de cada valor.
- Categoría de uso e \(I\); sistema estructural, \(R\) y la fila citada de la Tabla 15 o 16; cada irregularidad detectada con su tipo, su \(\phi\) y los \(\phi_P,\phi_E\) resultantes.
- Método de análisis y la comprobación de sus condiciones; si es dinámico, número de modos, masa participante por dirección, regla de combinación y los cortantes estático y dinámico con el factor de ajuste aplicado.
- \(T_a\) por cada método, \(k\), \(V\) en N y kN, la distribución \(F_x\), la excentricidad accidental por piso en m, \(A_x\), \(Q_i\) y \(f_{P\Delta}\) por piso; \(\Delta_E\) y \(\Delta_M\) por piso con el límite aplicable (0.02 o 0.01) y el veredicto con el artículo.
- La envolvente de las combinaciones (NEC-SE-CG), el régimen de \(R\) y las advertencias activas (perfil F, microzonificación, coeficientes pendientes de cotejo, versión de los datos).

## Referencias

1. NEC-SE-DS, *Peligro Sísmico y Diseño Sismo Resistente*, MIDUVI, Acuerdo Ministerial 0028 (19-08-2014), Registro Oficial 319 (26-08-2014); actualización Acuerdo Ministerial 0047 (15-12-2014), Registro Oficial 413 (10-01-2015).
2. NEC-SE-HM, *Estructuras de Hormigón Armado*, MIDUVI, misma edición y mismos actos habilitantes.
3. NEC-SE-MP, *Mampostería Estructural*, MIDUVI, misma edición.
4. NEC-SE-CG, *Cargas No Sísmicas*, MIDUVI, misma edición (combinaciones de carga).
5. NEC-SE-VIVIENDA — requisitos de vivienda a los que remiten los sistemas de ductilidad limitada.
6. ACI 318, *Building Code Requirements for Structural Concrete*, edición más reciente adoptada por NEC-SE-HM §2.3.1 (capítulo 21 para sismorresistencia).
7. ASCE/SEI 7 y NSR-10 — documentos referidos por NEC-SE-DS §1.4.2 y §6.3.4 para la definición del factor \(R\).
8. Copia digital de los documentos NEC consultada para este borrador (repositorio público de la Cámara de la Industria de la Construcción), 2026-02-14: suficiente para fórmulas, tablas y secciones; pendiente de cotejo con el Registro Oficial.

## Registro de verificación

- **Comprobado (2026-02-14)**, leyendo el texto completo de los PDF de NEC-SE-DS, NEC-SE-HM y NEC-SE-MP: zonas I–VI y valores de \(Z\); perfiles A–F y sus umbrales; tablas \(F_a\), \(F_d\) y \(F_s\) valor por valor; \(\eta\) por región y \(r=1.5\) en perfil E; \(T_0\), \(T_c\), \(T_L\) y el tope de 4 s; las dos ramas del espectro y la restricción de la rampa a modos superiores; \(S_d\); \(I\) (1.5/1.3/1.0); límites \(\Delta_M\) (0.02/0.01); \(\phi=0.9\) y sus productos; \(W\); \(C_t\), \(\alpha\) y el tope del 30 %; \(V\); \(R\) de las Tablas 15 y 16; \(k\); torsión accidental del 5 %; \(A_x\le3\); \(Q_i\le0.30\) y \(f_{P\Delta}\); \(\Delta_M=0.75R\Delta_E\); inercias agrietadas; 90 % de masa modal y ajuste 80 %/85 %; \(f'_c\), \(f_y\), \(\rho_{min}\) y \(\beta_1\) de NEC-SE-HM; morteros, mortero de relleno y diámetros de NEC-SE-MP.
- **Pendiente**: cotejo con el Registro Oficial; digitalización de los polígonos de la Figura 1 y de la tabla completa de poblaciones (apéndice 10.2); lectura inequívoca de \(C_{1,T}\) en NEC-SE-HM §6.1.2; interpretación de la referencia del 80 %/85 % entre §6.2.2-b y §6.2.2-e; espectros de microzonificación municipal vigentes; edición de ACI 318 adoptada.
- **Responsable de cerrar**: responsable de normativa del proyecto, con los PDF oficiales publicados en el Registro Oficial. La skill permanece en `status: draft` mientras existan marcas VERIFICAR, y el programa lee cada valor de `data/ecuador/nec15/*.json`.
