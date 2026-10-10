---
name: colombia-nsr10
description: >-
  Implementa y verifica el análisis y el diseño sismorresistente conforme a la
  NSR-10 colombiana: zonificación por Aa y Av, perfiles de suelo A a F,
  coeficientes Fa y Fv, espectro elástico de diseño con T0, Tc y TL, reducción por
  el coeficiente R según el grado de disipación de energía (DMI, DMO, DES) con sus
  factores de irregularidad, coeficiente de importancia I, métodos de análisis
  (fuerza horizontal equivalente y modal espectral), deriva máxima del 1 %,
  efectos P-Delta, combinaciones del Título B y remisión a los Títulos C, F y al
  CCP-14. Úsala cuando el proyecto declare código NSR-10, cuando haya que
  construir el espectro de un municipio colombiano, cuando se audite un módulo con
  formulación ASCE en un modelo colombiano, o al verificar derivas,
  P-Delta y combinaciones B.2.3/B.2.4.
metadata:
  track: codes
  jurisdiction: COL
  edition: "NSR-10 (Títulos A, B, C, F) y CCP-14"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Colombia — NSR-10 (Títulos A, B, C, F) y CCP-14

## Cuándo usar esta skill

- El proyecto declara `code = NSR-10` y hay que fijar amenaza, espectro y sistema estructural.
- Hay que clasificar la zona con \(A_a\) y \(A_v\) de la Tabla A.2.3-2 (capitales) o del Apéndice A-4 (todos los municipios).
- Hay que elegir el método de análisis con A.3.4.2 y ejecutar fuerza horizontal equivalente (A.4) o análisis dinámico espectral (A.5).
- Hay que verificar derivas contra el 1 % (Tabla A.6.4-1), el índice de estabilidad \(Q_i\) (A.6.2.3) y las combinaciones del Título B.
- Se audita un módulo existente: el defecto típico es arrastrar la convención de ASCE 7 (analizar con fuerzas reducidas y amplificar derivas por \(C_d\)) a un modelo colombiano.

**No usar** para otro país (→ `codes/code-crosswalk-and-extension`), para el dimensionamiento de elementos (→ `design/concrete-aci318`, `design/steel-aisc360-341`, recordando que NSR-10 remite a los Títulos C y F) ni para el estudio geotécnico (Título H).

## Alcance y límites

Cubre el Título A (A.2 movimientos sísmicos de diseño, A.3 requisitos generales, A.4 fuerza horizontal equivalente, A.5 análisis dinámico, A.6 derivas, A.7 interacción suelo-estructura como remisión), las combinaciones del Título B y la remisión a los Títulos C, D, E, F, G y H. Los puentes no se rigen por el Título A: se diseñan con el CCP-14. Queda fuera la **microzonificación sísmica municipal** (A.2.9) y el **estudio sísmico particular de sitio** (A.2.10): cuando existen, **sustituyen** A.2.4 y A.2.6 (A.2.1.2.1) y el programa debe consumir el espectro del decreto municipal, no las tablas genéricas. También quedan fuera el aislamiento en la base y los disipadores (A.3.8, A.3.9, que remiten a FEMA 450 o ASCE/SEI 7-05), las edificaciones existentes (A.10) y los elementos no estructurales (A.9).

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Municipio, microzonificación vigente y \(A_a\), \(A_v\) | sí | bloquear: no se asume que no existe ni se asigna por ciudad |
| Perfil de suelo A–F (geotecnista, 30 m superiores) | sí | bloquear; prohibido suponer perfil D |
| Grupo de uso I–IV y coeficiente \(I\) | sí | bloquear (A.2.5) |
| Material, sistema estructural y grado DMI/DMO/DES | sí | bloquear: definen \(R_0\), \(\Omega_0\) y límites de altura |
| Masas, alturas por piso \(h_n\) y configuración regular/irregular | sí | evaluar con A.3.3 y tablas A.3-6/A.3-7 |
| Método de diseño (resistencia o esfuerzos de trabajo) | sí | sin él no se eligen B.2.4 o B.2.3 |

Ningún dato faltante se sustituye por un valor por defecto silencioso (regla de `codes/code-crosswalk-and-extension`).

## Fundamento y formulación

### 1. Amenaza, zonificación y sitio (A.2.2, A.2.3, A.2.4)

\(A_a\) es la aceleración horizontal pico efectiva y \(A_v\) la velocidad horizontal pico efectiva expresada como aceleración, ambas en g y definidas para una probabilidad de excedencia del 10 % en 50 años (NSR-10, A.2.2.1). Se leen de la región de los mapas (figuras A.2.3-2 y A.2.3-3) con la Tabla A.2.2-1.

$$\text{amenaza}=\begin{cases}\text{baja} & \max(A_a,A_v)\le 0.10\\ \text{intermedia} & 0.10<\max(A_a,A_v)\le 0.20\\ \text{alta} & \max(A_a,A_v)>0.20\end{cases}\qquad\text{(NSR-10, A.2.3.1–A.2.3.3)}$$

Subconjunto de referencia de la Tabla A.2.3-2 (capitales; el programa lee la tabla completa del archivo de datos):

| Ciudad | \(A_a\) (g) | \(A_v\) (g) | Zona |
|---|---|---|---|
| Bogotá D. C. | 0.15 | 0.20 | Intermedia |
| Montería (trampa: \(A_a\) solo) | 0.10 | 0.15 | Intermedia |
| Cali / Armenia / Pereira | 0.25 | 0.25 | Alta |
| Quibdó | 0.35 | 0.35 | Alta |

Se definen seis perfiles de suelo: A (roca competente), B (roca de rigidez media), C (suelos muy densos o roca blanda), D (suelos firmes), E (suelos blandos) y F (suelos especiales: licuables, turbas, arcillas de muy alta plasticidad o depósitos de gran espesor), clasificados en los 30 m superiores por \(\bar v_s\), \(\bar N_{60}\) y \(\bar s_u\) (A.2.4.2–A.2.4.5). El perfil F no se clasifica por tabla: exige estudio particular (A.2.10); en depósitos inestables o potencialmente licuables **no aplican** las tablas (A.2.4.1.1). Los coeficientes \(F_a\) (períodos cortos) y \(F_v\) (períodos intermedios) son adimensionales y se interpolan linealmente: \(F_a=F_a(A_a,\text{perfil})\) y \(F_v=F_v(A_v,\text{perfil})\) (NSR-10, Tablas A.2.4-3 y A.2.4-4).

> ⚠️ VERIFICAR: las Tablas A.2.4-3 (\(F_a\)) y A.2.4-4 (\(F_v\)) completas y los umbrales numéricos de \(\bar v_s\), \(\bar N_{60}\) y \(\bar s_u\) de la Tabla A.2.4-1 no se transcriben aquí. Se comprueban en el Título A oficial y el programa debe **leerlos de `data/colombia/nsr10/site_factors.json`**, versionado, con `source` y `verified_on`; nunca se incrustan en el código.

### 2. Espectro elástico de aceleraciones de diseño (A.2.6.1)

Con \(S_a\) como fracción de \(g\) (declarado: NSR-10 publica el espectro en g) y \(T\) en s: \(T_0=0.1A_vF_v/(A_aF_a)\), \(T_c=0.48A_vF_v/(A_aF_a)=4.8T_0\), \(T_L=2.4F_v\).

$$S_a(T)=\begin{cases}2.5\,A_aF_aI\,(0.4+0.6\,T/T_0) & T<T_0\\ 2.5\,A_aF_aI & T_0\le T\le T_c\\ 1.2\,A_vF_vI/T & T_c<T\le T_L\\ 1.2\,A_vF_vT_LI/T^2 & T>T_L\end{cases}$$

La rampa inicial (\(T<T_0\)) solo es utilizable en análisis dinámico y para modos distintos del fundamental; para el período fundamental del método de fuerza horizontal equivalente rige la meseta \(2.5A_aF_aI\) (NSR-10, A.2.6.1). El espectro NSR-10 **no** tiene la rampa tipo ASCE en su forma estática. Las ramas empalman de forma exacta: \(2.5A_aF_aT_c=1.2A_vF_v\), lo que sirve de control de datos. Coeficiente de importancia \(I\) por grupo de uso (NSR-10, Tabla A.2.5-1): grupo I ocupación normal 1.00, II ocupación especial 1.10, III atención a la comunidad 1.25, IV edificaciones indispensables 1.50.

### 3. Reducción por capacidad de disipación de energía (A.3.1.1, A.3.3.3)

La estructura se analiza con las fuerzas **elásticas** \(F_s\) del espectro y se diseña con las fuerzas reducidas \(E\); las derivas se verifican con \(F_s\) sin reducir: \(R=\phi_a\phi_p\phi_rR_0\) y \(E=F_s/R\) (NSR-10, ec. A.3.3-1), donde \(R_0\) es el coeficiente básico del sistema y del grado DMI/DMO/DES (Tablas A.3-1 a A.3-4), \(\phi_p\) y \(\phi_a\) reducen por irregularidad en planta (Tabla A.3-6) y en altura (Tabla A.3-7), \(\phi_r\) por ausencia de redundancia (A.3.3.8) y \(\Omega_0\) es la sobrerresistencia para elementos frágiles (A.3.3.9).

Factores de irregularidad (NSR-10, Tablas A.3-6 y A.3-7). En planta: torsional 1aP \(\phi_p=0.9\), torsional extrema 1bP 0.8, retrocesos en esquinas 2P 0.9, discontinuidad del diafragma 3P 0.9, desplazamiento de planos de acción 4P 0.8, sistemas no paralelos 5P 0.9. En altura: piso flexible 1aA 0.9 y 1bA 0.8, masas 2A 0.9, geométrica 3A 0.9, desplazamiento dentro del plano 4A 0.8, piso débil 5aA 0.9 y 5bA 0.8. Con varias irregularidades del **mismo** tipo se toma el menor \(\phi_p\) y el menor \(\phi_a\), nunca su producto (A.3.3.3). Ausencia de redundancia: \(\phi_r=1.0\) en DMI y \(\phi_r=0.75\) en DMO y DES, salvo las excepciones de A.3.3.8.2. El grado mínimo lo fija la zona: DES en alta, DMO en intermedia, DMI en baja, como regla general (A.3.1.3). Elementos frágiles y conexiones que exigen sobrerresistencia: \(E=\Omega_0F_s/R\pm0.5A_aF_aD\) (NSR-10, ec. A.3.3-2).

> ⚠️ VERIFICAR: las Tablas A.3-1 a A.3-4 (\(R_0\), \(\Omega_0\), límites de altura y prohibiciones por zona), los criterios literales de las Tablas A.3-6 y A.3-7 y la ecuación A.3.3-2 se comprueban en el Título A oficial y se leen de `data/colombia/nsr10/r_factors.json` e `irregularities.json`. Subconjunto de referencia ya contrastado: pórtico de concreto DES \(R_0=7.0\) sin límite de altura; dual de muros y pórticos DES \(R_0=8.0\); muros de carga de concreto DES \(R_0=5.0\), 50 m en zona alta; pórtico losa-columna DMO \(R_0=2.5\), 15 m en zona intermedia y prohibido en zona alta. \(\Omega_0\) varía entre 2.0 y 3.0 según la tabla.

### 4. Métodos de análisis (A.3.4.2, A.4, A.5)

Fuerza horizontal equivalente (Capítulo A.4): permitida en toda edificación en zona baja, en las del grupo I en zona intermedia, en las regulares de hasta 20 niveles y 60 m y en las irregulares de hasta 6 niveles y 18 m; **no** se permite sobre perfiles D, E o F cuando \(T>2T_c\). Es obligatorio el análisis dinámico elástico (A.3.4.2.2) en edificaciones de más de 20 niveles o 60 m, con irregularidades 1aA, 1bA, 2A o 3A, con irregularidades no tipificadas, y cuando cambia el sistema estructural en altura por encima de 5 niveles o 20 m en zona alta, además del caso \(T>2T_c\) en suelos D, E o F (A.5.1.2). Período fundamental (A.4.2): ecuación de Rayleigh o dinámica estructural; \(T_a=C_th_n^{\alpha}\) con \(C_t\), \(\alpha\) de la Tabla A.4.2-1; \(T_a=0.1N\) solo para pórticos de concreto o acero de hasta 12 pisos con altura de piso ≤ 3 m. El período del modelo no puede exceder \(C_uT_a\), con \(C_u=1.75-1.2A_vF_v\ge1.2\) (A.4.2.1); si el período recalculado difiere más del 10 % del estimado, se repite el análisis (A.4.2.3).

$$V_s=S_a(T)\,g\,M,\qquad F_x=\frac{m_xh_x^k}{\sum_i m_ih_i^k}V_s,\qquad k=1.0\ (T\le0.5\ \text{s});\quad k=0.75+0.5T\ (0.5<T<2.5\ \text{s});\quad k=2.0\ (T\ge2.5\ \text{s})$$

\(M\) es masa (kg), no peso: incluye muros divisorios, equipos permanentes y, en depósitos, el 25 % de la masa de la carga viva (NSR-10, A.4.3.1). Análisis dinámico espectral (A.5.4): se incluyen los modos que acumulen al menos el 90 % de la masa participante **en cada dirección**; la combinación modal es CQC en modelos tridimensionales; las derivas se combinan **modo a modo**, nunca restando desplazamientos ya combinados; el cortante dinámico se ajusta contra el estático con \(V_{tj}\ge0.80V_s\) (regular) o \(V_{tj}\ge0.90V_s\) (irregular), calculando \(V_s\) para \(T\le C_uT_a\) y aplicando el factor \(0.80V_s/V_{tj}\) o \(0.90V_s/V_{tj}\) **a toda** la respuesta dinámica: derivas, fuerzas de piso, cortantes y fuerzas internas (A.5.4.5). El análisis cronológico exige \(V_{tj}\ge1.00V_s\) (A.5.5).

### 5. Derivas, P-Delta y separación (A.6)

La deriva se calcula con los desplazamientos del análisis elástico obtenidos de \(F_s\), **sin dividir por \(R\)** (a diferencia de ASCE 7, aquí no hay amplificación por \(C_d\)); en grupos II, III y IV se permite evaluar los desplazamientos con \(I=1.0\) aunque la resistencia use el \(I\) completo (A.6.2.1.2): \(\delta_{tot}=|\delta_{cm}|+|\delta_t|+|\delta_{pd}|\), y \(\Delta_i=(\delta_i-\delta_{i-1})/h_{pi}\) (A.6.2.4, A.6.3). Límites de la Tabla A.6.4-1: **1.0 %** de \(h_{pi}\) en concreto reforzado, estructuras metálicas, madera y mampostería de comportamiento flexional; **0.5 %** en mampostería poco esbelta o gobernada por cortante. Las derivas pueden multiplicarse por 0.7 antes de compararlas si el análisis usó secciones fisuradas (A.6.4.1.1) o si se verificó desempeño inelástico de Protección de la Vida (A.6.4.1.2); las edificaciones de un piso no tienen límite si los elementos no estructurales se diseñan para acomodar la deriva (A.6.4.1.5). Con irregularidad torsional la deriva se verifica en cualquier punto del piso, combinando vectorialmente las dos direcciones en planta (A.6.3.1). Separación sísmica (A.6.5, Tabla A.6.5-1): entre partes de una misma construcción, la suma de los valores absolutos de los desplazamientos totales; entre colindantes, 1 % a 3 % de \(h_n\) según el número de pisos y la coincidencia de losas, nulo en amenaza baja.

Índice de estabilidad y efectos P-Delta (A.6.2.3): \(Q_i=P_i\Delta_{cm}/(V_ih_{pi})\), con \(P_i\) la carga vertical acumulada (coeficientes de carga que no necesitan exceder 1.0). Si \(Q_i\le0.10\) los efectos P-Delta pueden ignorarse; si \(0.10<Q_i\le0.30\) se incluyen \(\delta_{pd}=\delta_{cm}Q_i/(1-Q_i)\) y la amplificación de fuerzas laterales \(1/(1-Q_i)\); si \(Q_i>0.30\) la estructura es potencialmente inestable y debe rigidizarse, salvo el cumplimiento total de C.10.11.6.2(b) del Título C.

### 6. Combinaciones de carga del Título B y remisión a los Títulos C y F

Diseño por resistencia (B.2.4); \(E\) ya está al nivel de resistencia (\(E=F_s/R\)) y el viento \(W\) de B.6 al nivel de servicio:

| Ec. | Combinación |
|---|---|
| B.2.4-1 | \(1.4(D+F)\) |
| B.2.4-2 | \(1.2(D+F+T)+1.6(L+H)+0.5(L_r\ \text{ó}\ G\ \text{ó}\ L_e)\) |
| B.2.4-3 | \(1.2D+1.6(L_r\ \text{ó}\ G\ \text{ó}\ L_e)+(L\ \text{ó}\ 0.8W)\) |
| B.2.4-4 | \(1.2D+1.6W+1.0L+0.5(L_r\ \text{ó}\ G\ \text{ó}\ L_e)\) |
| B.2.4-5 | \(1.2D+1.0E+1.0L\) |
| B.2.4-6 | \(0.9D+1.6W+1.6H\) |
| B.2.4-7 | \(0.9D+1.0E+1.6H\) |

En B.2.4-3, B.2.4-4 y B.2.4-5 el factor de \(L\) puede tomarse 0.5 cuando \(L_o\le4.8\ \text{kN/m}^2\), excepto garajes y zonas de reunión pública; donde \(H\) contrarresta el sismo su factor se toma cero si el empuje no es permanente. Método de esfuerzos de trabajo (B.2.3): \(D+F\); \(D+H+F+L+T\); \(D+H+F+(L_r\,\text{ó}\,G\,\text{ó}\,L_e)\); \(D+H+F+0.75(L+T)+0.75(L_r\,\text{ó}\,G\,\text{ó}\,L_e)\); \(D+H+F+(W\,\text{ó}\,0.7E)\); \(D+H+F+0.75(W\,\text{ó}\,0.7E)+0.75L+0.75(L_r\,\text{ó}\,G\,\text{ó}\,L_e)\); \(0.6D+W+H\); \(0.6D+0.7E+H\), donde el 0.7E es el coeficiente de carga de A.3.1.8. El dimensionamiento y el detallado de elementos se rigen por el Título C (concreto estructural, con el detallado sismorresistente para DMI, DMO y DES) y el Título F (estructuras metálicas); el empuje del suelo y la cimentación, por los Títulos E y H; la vía alternativa P-Delta en concreto está en C.10.11.6.2(b). Los puentes y pontones se diseñan con el CCP-14, que define su propio espectro, factores de sitio y combinaciones.

> ⚠️ VERIFICAR: la edición del CCP-14 aplicable y su norma de adopción, y las ediciones de ACI y AISC adoptadas por los Títulos C y F, deben confirmarse contra los textos oficiales; el programa solo registra la remisión y no replica coeficientes del CCP-14.

## Procedimiento

1. Resolver si el municipio tiene microzonificación vigente (A.2.9). Si la tiene, cargar su espectro y **no** aplicar A.2.4/A.2.6; si no, continuar.
2. Obtener \(A_a\), \(A_v\) del municipio o de la región de los mapas y clasificar la zona con \(\max(A_a,A_v)\).
3. Clasificar el perfil de suelo A–F con los parámetros geotécnicos; si es F o el depósito es inestable, detener y exigir estudio particular.
4. Interpolar \(F_a\) y \(F_v\), calcular \(T_0\), \(T_c\), \(T_L\) y verificar el empalme \(2.5A_aF_aT_c=1.2A_vF_v\) como control de datos.
5. Asignar grupo de uso \(I\) y clasificar material, sistema y grado DMI/DMO/DES; comprobar límites de altura y prohibiciones por zona.
6. Evaluar irregularidades en planta y altura (Tablas A.3-6 y A.3-7), tomar el menor \(\phi_p\) y el menor \(\phi_a\), fijar \(\phi_r\) y calcular \(R\), documentando cada \(\phi\) con su tipo y su tabla.
7. Elegir el método con A.3.4.2 y verificar sus límites de uso; si es FHE, calcular \(T\) (Rayleigh o \(T_a\)) con su tope \(C_uT_a\).
8. Calcular \(V_s=S_agM\), distribuir \(F_x\) y aplicar torsión accidental y efectos direccionales (A.3.6.3, A.3.6.7).
9. Si es dinámico: incluir modos hasta el 90 % de masa por dirección, combinar con CQC, combinar derivas modo a modo y ajustar toda la respuesta con \(0.80V_s/V_{tj}\) o \(0.90V_s/V_{tj}\).
10. Verificar derivas con los desplazamientos de \(F_s\) sin reducir, contra 1.0 % (o 0.5 %), y calcular \(Q_i\) por piso.
11. Si \(0.10<Q_i\le0.30\) incorporar \(\delta_{pd}\) y \(1/(1-Q_i)\); si \(Q_i>0.30\), detener y rigidizar.
12. Formar \(E=F_s/R\), resolver las combinaciones B.2.4 (o B.2.3), diseñar con los Títulos C/F y emitir el informe con trazabilidad (norma, edición, artículo, tabla).

## Implementación en la plataforma

```python
# opensees_studio/core/codes/colombia_nsr10.py   (core puro: sin Qt, sin OpenSeesPy)

def hazard_zone(aa: float, av: float) -> str: ...        # 'baja'|'intermedia'|'alta' (A.2.3)
def site_coefficients(aa: float, av: float, profile: str) -> tuple[float, float]: ...
#   -> (Fa, Fv) interpolados de data/colombia/nsr10/site_factors.json (Tablas A.2.4-3/4)
def spectrum_periods(aa: float, av: float, fa: float, fv: float) -> tuple[float, float, float]: ...
#   -> (T0, Tc, TL) en s (A.2.6.1); CodeDataError si el empalme 2.5*Aa*Fa*Tc = 1.2*Av*Fv no cierra
def design_spectrum(aa, av, fa, fv, importance: float, t: float | None = None) -> "Spectrum": ...
#   -> Sa(T) como fracción de g; con t=None devuelve la curva completa y su `source` (A.2.6.1)
def r_coefficient(r0: float, phi_a: float = 1.0, phi_p: float = 1.0, phi_r: float = 1.0) -> float: ...
def equivalent_lateral_force(model, *, code_data, direction: str) -> "ELFDemand": ...
#   -> Ta, T, Cu*Ta, Vs = Sa*g*M, k, Fx y la comprobación de los límites de A.3.4.2.1
def modal_base_shear_scale(vs_static: float, vtj: float, regular: bool) -> float: ...
#   -> 0.80*Vs/Vtj o 0.90*Vs/Vtj, aplicable a TODA la respuesta dinámica (A.5.4.5)
def drift_and_p_delta(*, floors, displacements_fs, code_data) -> "DriftReport": ...
#   -> derivas de Fs (sin dividir por R), Qi, delta_pd y el límite aplicable (A.6)
def load_combinations(method: str = "LRFD", loads: "LoadFlags") -> list["LoadCombination"]: ...
#   -> B.2.4 (resistencia) o B.2.3 (esfuerzos de trabajo, con 0.7E)
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services` y `codes/code-crosswalk-and-extension`):

- El módulo vive en `core/codes/` e implementa el protocolo `SeismicCode` (`code_id = "col-nsr10"`); **no** importa Qt ni OpenSeesPy y es utilizable sin interfaz gráfica.
- Todos los coeficientes regulados (\(A_a\), \(A_v\), \(F_a\), \(F_v\), \(I\), \(R_0\), \(\Omega_0\), \(\phi\), límites de deriva, combinaciones) vienen de `data/colombia/nsr10/*.json`, nunca del código; cada entrada lleva `source` (norma, edición, tabla) y `verified_on`.
- El espectro y \(R\) son funciones puras: entran amenaza, perfil, grupo y sistema; sale una curva o un número con su cita.
- Solo `services/` habla con el solver: `services/spectrum.py` consume estas funciones y el caso modal corre en el proceso hijo de `run.py`, con un único `ops.eigen` ARPACK por proceso.
- Combinación modal con `core/modal_combination.py` (CQC por defecto en 3D) y derivas combinadas modo a modo; está prohibido derivar derivas de desplazamientos ya combinados.
- Errores tipificados y no degradables a un valor por defecto: `MissingHazardData`, `MissingSiteClass`, `MicrozonificationRequired`, `ForbiddenMethod`, `CodeDataOutOfDate`.
- \(g\): el reglamento escribe \(g=9.8\ \text{m/s}^2\) (NSR-10, A.2.0) y la plataforma usa \(g=9.80665\ \text{m/s}^2\); la diferencia relativa (\(6.8\times10^{-4}\)) se declara y las pruebas que replican cifras publicadas usan tolerancia relativa 1e-3.

## Datos normativos

| Dato | Origen | Estado |
|---|---|---|
| Zonas por \(\max(A_a,A_v)\); regiones 1–10 → 0.05 … 0.50 | A.2.3.1–A.2.3.3, Tablas A.2.3-1 y A.2.2-1 | verificado; cotejo oficial pendiente |
| \(A_a\), \(A_v\) de capitales; por municipio | Tabla A.2.3-2; Apéndice A-4 | **VERIFICAR** → `zones.json`, `municipalities.json` |
| Perfiles A–F; umbrales de \(\bar v_s\), \(\bar N_{60}\), \(\bar s_u\) | A.2.4.2–A.2.4.5, Tabla A.2.4-1 | **VERIFICAR** → `site_factors.json` |
| \(F_a\), \(F_v\) | Tablas A.2.4-3 y A.2.4-4 | **VERIFICAR** → `site_factors.json` |
| \(I\): 1.00, 1.10, 1.25, 1.50 | Tabla A.2.5-1 | verificado; cotejo pendiente |
| \(T_0\), \(T_c\), \(T_L\) y las cuatro ramas de \(S_a\) | A.2.6.1 | verificado (empalme exacto en \(T_c\)) |
| \(R=\phi_a\phi_p\phi_rR_0\); \(E=F_s/R\) | A.3.1.1, A.3.3.3, ec. A.3.3-1 | verificado |
| \(\phi_p\), \(\phi_a\) por tipo de irregularidad | Tablas A.3-6 y A.3-7 | **VERIFICAR** → `irregularities.json` |
| \(\phi_r=1.0\) (DMI); 0.75 (DMO, DES) con excepciones | A.3.3.8.1 y A.3.3.8.2 | verificado |
| \(R_0\), \(\Omega_0\), límites de altura; límites del FHE y casos de dinámico obligatorio | Tablas A.3-1 a A.3-4; A.3.4.2.1, A.3.4.2.2, A.5.1.2 | **VERIFICAR** → `r_factors.json` |
| \(C_u=1.75-1.2A_vF_v\ge1.2\); \(k=0.75+0.5T\); \(V_s=S_agM\) | A.4.2.1, A.4.3.1, A.4.3.2 | verificado |
| 90 % de masa, CQC, derivas modo a modo, ajuste 80/90/100 % | A.5.4.2, A.5.4.4, A.5.4.5, A.5.5 | verificado |
| Deriva 1.0 % y 0.5 %, ×0.7 con secciones fisuradas; \(Q_i\) (0.10 y 0.30), \(\delta_{pd}\) | Tabla A.6.4-1, A.6.4.1.1, A.6.2.3 | verificado; cotejo pendiente |
| Espectro, factores de sitio y combinaciones de puentes | CCP-14 | **VERIFICAR** (fuera de esta skill) |

> ⚠️ VERIFICAR: todos los valores marcados provienen de una **edición digital de referencia no oficial** (texto del Título A y análisis por capítulo, publicados en línea) y deben cotejarse con el texto oficial del Decreto 926 de 2010 y sus modificatorios. Hasta cerrar ese cotejo, el programa los lee de `data/colombia/nsr10/*.json` y ninguna prueba fija un valor regulado dentro del código.

> ⚠️ VERIFICAR: la expresión del coeficiente de amplificación torsional \(A_x\) y la excentricidad accidental (5 % de la dimensión perpendicular) atribuidas a A.3.6.7 no se pudieron leer del articulado completo; se comprueban en §A.3.6.7 antes de implementarlas.

## Verificación y casos de prueba

| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Zona | \(A_a=0.15\), \(A_v=0.20\) | Intermedia | exacto | A.2.3.2 |
| Períodos | \(A_a=A_v=0.25\), \(F_a=F_v=1.0\) | \(T_0=0.10\) s, \(T_c=0.48\) s, \(T_L=2.4\) s | 1e-9 | A.2.6.1 |
| Meseta, \(I=1.0\) | \(T=0.30\) s | \(S_a=0.625\,g\) | 1e-9 | A.2.6.1 |
| Rampa inicial | \(T=0.05\) s | \(S_a=0.4375\,g\) | 1e-9 | A.2.6.1 |
| Rama hiperbólica | \(T=1.00\) s | \(S_a=0.300\,g\) | 1e-9 | A.2.6.1 |
| Cola de desplazamiento | \(T=4.80\) s (> \(T_L\)) | \(S_a=0.03125\,g\) | 1e-9 | A.2.6.1 |
| Empalme en \(T_c\) | Meseta vs. rama descendente | Diferencia nula | 1e-12 rel. | A.2.6.1 |
| \(R\) con irregularidades | \(R_0=7.0\), \(\phi_a=0.9\), \(\phi_p=0.9\), \(\phi_r=0.75\) | \(R=4.2525\); \(E=F_s/4.2525\) | 1e-9 | A.3.3.3 |
| Período aproximado | Pórtico de concreto, \(h_n=30\) m | \(T_a=0.047\times30^{0.9}=1.0035\) s | 1e-6 rel. | Tabla A.4.2-1 |
| Tope \(C_u\) | \(A_v=0.25\), \(F_v=1.0\) | \(C_u=1.45\); piso 1.2 si \(A_vF_v\ge0.4583\) | 1e-9 | A.4.2.1 |
| Cortante basal | \(S_a=0.625\), \(M=1.0\times10^6\) kg | \(V_s=6.125\times10^6\) N (\(g=9.8\)) | 1e-6 rel. | A.4.3.1 |
| \(Q_i\) en sus dos rangos | \(P=5000\) kN, \(\Delta_{cm}=0.02\) m, \(V=800\) kN, \(h_p=3\) m; y \(P=20000\) kN, \(\Delta_{cm}=0.03\) m, \(V=1000\) kN | \(Q_i=0.0417\le0.10\) (se ignora); \(Q_i=0.20\), \(\delta_{pd}=0.0075\) m, \(1/(1-Q_i)=1.25\) | 1e-6 | A.6.2.3 |
| Deriva límite | \(\Delta=0.032\) m, \(h_p=3.0\) m | 1.067 % > 1.0 % → no cumple; ×0.7 → 0.747 % | 1e-6 | Tabla A.6.4-1 |
| Ajuste del basal dinámico | \(V_s=1000\) kN, \(V_{tj}=700\) kN, regular | \(f=1.1429\) sobre toda la respuesta | 1e-6 | A.5.4.5 |

Contraste externo obligatorio: reproducir el espectro de dos municipios con microzonificación vigente contra el espectro del decreto municipal, y dos modelos (un pórtico regular y uno con muro) contra una memoria de cálculo independiente revisada.

## Errores frecuentes y trampas

1. **Amplificar derivas por \(R\) o por \(C_d\).** En NSR-10 la deriva se verifica con los desplazamientos elásticos de \(F_s\), sin dividir por \(R\) (A.6). Analizar con \(E=F_s/R\) y verificar deriva con esos desplazamientos subestima la deriva en un factor \(R\) (5 a 7 en pórticos dúctiles).
2. **Multiplicar por 0.7 dos veces.** El 0.7 de A.6.4.1.1 solo aplica si el modelo usó secciones fisuradas; modelar con secciones brutas y además aplicar 0.7 descuenta dos veces la misma fisuración.
3. **Usar el período del modelo sin el tope \(C_uT_a\)**, o sin repetir el análisis cuando \(T\) cambia más del 10 % (A.4.2.3): un modelo sin tabiques da períodos largos y fuerzas menores.
4. **Usar la rampa \(T<T_0\) para el modo fundamental.** La rampa solo vale en análisis dinámico y en modos distintos del fundamental; para el modo fundamental del FHE rige la meseta.
5. **Confundir masa con peso.** \(V_s=S_agM\) con \(M\) en kg; usar \(W\) en kN sin dividir por \(g\) multiplica el cortante por 9.8. Mezclar kgf con kg en el mismo modelo.
6. **Usar \(R_0\) como \(R\).** Olvidar \(\phi_a\phi_p\phi_r\) ignora que una estructura torsional extrema (0.8), con piso débil (0.8) y sin redundancia (0.75) trabaja con menos de la mitad del \(R_0\) nominal (A.3.3.3).
7. **Clasificar la zona con \(A_a\) solo.** La fija \(\max(A_a,A_v)\): Montería (\(A_a=0.10\), \(A_v=0.15\)) es intermedia, no baja, y eso cambia el grado de disipación exigido.
8. **Escalar solo el cortante basal del análisis dinámico** (el factor \(0.80V_s/V_{tj}\) o 0.90 se aplica a toda la respuesta, derivas incluidas: A.5.4.5) o **derivar derivas de desplazamientos ya combinados**: la combinación modal no conserva simultaneidad y la deriva se combina modo a modo (A.5.4.4).
9. **Aplicar A.2.4 y A.2.6 donde hay microzonificación.** En Bogotá, Medellín y otras ciudades con decreto vigente el espectro municipal sustituye las tablas (A.2.1.2.1, A.2.9).
10. **Usar el FHE fuera de sus límites** (perfiles D, E o F con \(T>2T_c\), más de 20 niveles o 60 m, irregularidades 1aA/1bA/2A/3A: A.3.4.2.1, A.5.1.2) o **suponer perfil D por costumbre**: la clasificación exige parámetros medidos en los 30 m y en depósitos licuables o inestables no aplican las tablas (A.2.4.1.1).
11. **Mezclar \(g=9.8\) con \(g=9.80665\)** entre espectro, masa y verificación normativa: discrepancias de \(6.8\times10^{-4}\) que hacen fallar pruebas contra cifras publicadas.
12. **Aplicar el 0.5L de B.2.4 sin condiciones.** Solo vale con \(L_o\le4.8\ \text{kN/m}^2\) y nunca en garajes ni zonas de reunión pública; además es una reducción del término gravitacional concomitante, no de la demanda sísmica.

## Interfaz de salida

Para cada dirección de análisis, el programa debe exponer:

- Municipio, región de los mapas, \(A_a\), \(A_v\) en g, zona de amenaza y fuente exacta (tabla o decreto de microzonificación vigente); perfil de suelo con los parámetros de su clasificación y su cita, y aviso explícito si el perfil es F o el depósito es inestable.
- \(F_a\), \(F_v\), \(I\), \(T_0\), \(T_c\), \(T_L\) y la curva \(S_a(T)\) con `accel_unit = "g"`, `damping = 0.05` y la cita de cada valor.
- Material, sistema estructural, grado DMI/DMO/DES, \(R_0\), \(\Omega_0\), límites de altura por zona y cada irregularidad detectada con su código (1aP, 5bA, …), su \(\phi\), su tabla de origen y los \(\phi_a\), \(\phi_p\), \(\phi_r\) resultantes; y \(R\) por dirección según A.3.3-1.
- Método de análisis usado, la comprobación de sus límites de uso y, si es dinámico, número de modos, masa participante por dirección, regla de combinación y factor de ajuste del basal.
- \(T_a\), \(C_uT_a\), \(T\) calculado, \(k\), \(V_s\) en N (y kN), la distribución \(F_x\) y la masa \(M\) con su desglose (particiones, equipos, 25 % de viva en depósitos).
- Derivas por entrepiso con \(\delta_{cm}\), \(\delta_t\), \(\delta_{pd}\), el límite aplicable (1.0 % o 0.5 %), el factor 0.7 si se usó, y el veredicto con el artículo.
- \(Q_i\) por piso y la amplificación \(1/(1-Q_i)\) cuando corresponda; aviso de inestabilidad si \(Q_i>0.30\).
- Envolventes de las combinaciones B.2.4 (o B.2.3) realmente empleadas, con la ecuación usada, y las advertencias activas (microzonificación aplicada, coeficientes pendientes de cotejo, \(g\) empleada).

## Referencias

1. NSR-10, *Reglamento Colombiano de Construcción Sismo Resistente*, Decreto 926 de 2010, modificado por los Decretos 2525 de 2010, 092 de 2011, 340 de 2012 y 945 de 2017. Título A (A.2 a A.7), Título B (B.2.3, B.2.4), Títulos C y F.
2. Ley 400 de 1997, marco legal del Reglamento NSR-10.
3. CCP-14, *Código Colombiano de Puentes*, Ministerio de Transporte, edición 2014, y su norma de adopción.
4. AIS, *Comentarios al Reglamento Colombiano de Construcción Sismo Resistente NSR-10*, edición 2010-2011, y decretos municipales de microzonificación vigentes (p. ej. Bogotá D. C.), cuyo espectro sustituye A.2.4 y A.2.6.
5. Edición digital de referencia **no oficial** consultada para este borrador: texto del Título A y análisis por capítulo (A.2 a A.6) publicados en `nsr-10.com`, consulta del 2026-02-14; suficiente para estructura y formulación, insuficiente para cerrar valores regulados.
6. ACI 318 y AISC 360/341 en las ediciones adoptadas por los Títulos C y F: pendiente de confirmar cuáles son.

## Registro de verificación

- **Comprobado (2026-02-14)**: definición de \(A_a\) y \(A_v\) al 10 % en 50 años; zonificación por \(\max(A_a,A_v)\); regiones 1–10 y subconjunto de capitales; forma de las cuatro ramas del espectro y empalme exacto en \(T_c\); \(R=\phi_a\phi_p\phi_rR_0\) y \(E=F_s/R\); prohibición de multiplicar irregularidades del mismo tipo; \(\phi_r=1.0\) en DMI y 0.75 en DMO/DES con excepciones; límites del FHE y casos de dinámico obligatorio; \(C_u\), \(k\), \(V_s=S_agM\); 90 % de masa, CQC y derivas modo a modo; ajuste 80/90/100 % del cortante basal; \(\delta_{tot}\), \(Q_i\) (0.10 y 0.30); deriva 1.0 % y 0.5 % con factor 0.7; combinaciones B.2.4-1…7 y B.2.3-1…8.
- **Pendiente**: cotejo de todos los valores citados con el texto oficial del Decreto 926 de 2010 y modificatorios; transcripción de las Tablas A.2.4-1, A.2.4-3, A.2.4-4, A.3-1 a A.3-4, A.3-6, A.3-7, A.6.4-1, A.6.5-1 y del Apéndice A-4 a archivos de datos con `source` y `verified_on`; confirmación de la ecuación A.3.3-2 y de \(A_x\) (A.3.6.7); ediciones de ACI y AISC adoptadas por los Títulos C y F; edición y adopción del CCP-14.
- **Responsable de cerrar**: responsable de normativa del proyecto, con ejemplar oficial (impreso o PDF licenciado) del NSR-10 y de los decretos de microzonificación aplicables. La skill permanece en `status: draft` mientras existan marcas VERIFICAR.
