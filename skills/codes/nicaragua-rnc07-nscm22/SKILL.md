---
name: nicaragua-rnc07-nscm22
description: >-
  Implementa el análisis y diseño sismorresistente en Nicaragua: el Reglamento
  Nacional de la Construcción RNC-07 (coeficiente sísmico c, espectro de diseño
  con Ta/Tb/Tc, método estático equivalente y modal espectral) y la Norma
  Sismorresistente para la Ciudad de Managua NSCM-22 (fuerza lateral equivalente
  con Cs, espectro multi-ramal A(T), Cd, P-Δ y derivas). Úsala para proyectos
  ubicados en Nicaragua, para migrar un modelo de RNC-07 a NSCM-22 al pasar por
  Managua, o para auditar comprobaciones sísmicas nicaragüenses.
metadata:
  track: codes
  jurisdiction: NIC
  edition: "RNC-07 (MTI, 2007) y NSCM-22 (MTI, 2022)"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Nicaragua — RNC-07 (nacional) y NSCM-22 (Managua)

## Cuándo usar esta skill

- El proyecto está en Nicaragua y hay que decidir **qué norma aplica**: RNC-07 en
  todo el territorio, NSCM-22 en el municipio de Managua (y por remisión, en los
  municipios que la adopten).
- Hay que calcular el coeficiente sísmico \(c\), el cortante basal, el espectro de
  diseño o las derivas con la formulación nicaragüense.
- Hay que justificar ante el MTI (Ministerio de Transporte e Infraestructura) o la
  Alcaldía de Managua.
- Hay que actualizar un modelo antiguo dimensionado con RNC-07 a la práctica
  vigente en Managua.

## Alcance y límites

Cubre la acción sísmica y las comprobaciones globales (cortante, torsión, P-Δ,
derivas, regularidad). El dimensionamiento de elementos se hace con
`design/concrete-aci318` (el RNC-07 se apoya en ACI 318 cap. 21 para
sismorresistente) y `design/steel-aisc360-341`. La cimentación y el sitio, con
`design/foundations-and-soil-structure`.

## Entradas y supuestos

| Dato | RNC-07 | NSCM-22 |
|---|---|---|
| Zona sísmica / ubicación | mapa de isoaceleraciones (Anexo C) | \(a_0\) de roca por zona Z1… |
| Tipo de suelo | I–IV por \(V_s\) | clase de sitio A–E por \(V_s\) |
| Grupo / categoría de riesgo | A (esencial), B (normal), C (menor) | 4 categorías de riesgo + índice de importancia \(I\) |
| Tipo estructural | define \(Q\) y \(\Omega\) | define \(R_0\), \(C_d\), tipo I–IV |
| Regularidad | 12 condiciones (Art. 23) | sección 5, irregularidad extrema |

Si falta el estudio de suelos, el programa **no debe suponer** un tipo de suelo:
emite error y pide clasificación (el RNC-07 permite el perfil "mediano" solo en el
reglamento de 1983, no como sustituto del estudio actual).

## Fundamento y formulación

### A. RNC-07 — método estático equivalente

Cortante basal (Art. 27):

$$F_c = c\,W_0, \qquad W_0 = CM + CVR$$

donde \(CVR\) es la carga viva incidental (típicamente \(0.4\,CV\); en depósitos y
almacenaje se conserva el 85 % de la carga viva para el peso sísmico).

Coeficiente de diseño sismorresistente (Art. 24):

$$c = \frac{S\,(2.7\,a_0)}{Q'\,\Omega}, \qquad c \ge c_{min} = S\,a_0$$

| Símbolo | Significado | Unidad |
|---|---|---|
| \(a_0\) | aceleración máxima del terreno (Anexo C) | g |
| \(S\) | factor de amplificación por tipo de suelo (Art. 25) | — |
| \(Q\) | factor de ductilidad (Anexo B) | — |
| \(Q'\) | factor de ductilidad corregido por irregularidad (Art. 23) | — |
| \(\Omega\) | factor de sobrerresistencia (Art. 22) | — |

Aceleración del terreno por zona (valores citados en la literatura técnica
nicaragüense: zona A \(a_0 = 0.10\), zona B \(0.20\), zona C \(0.30\) en g):

> ⚠️ VERIFICAR: los valores de \(a_0\) por zona y el mapa de isoaceleraciones
> (Anexo C) deben transcribirse del RNC-07 impreso a
> `data/nicaragua/rnc07_zones.json`. El valor por **coordenada** debe interpolarse
> del mapa, no asignarse por ciudad.

Clasificación de sitio por velocidad de onda de corte (m/s):

| Tipo | Descripción | \(V_s\) |
|---|---|---|
| I | roca / suelo muy firme | \(V_s \ge 750\) |
| II | suelo firme | \(360 < V_s \le 750\) |
| III | moderadamente blando | \(180 < V_s \le 360\) |
| IV | muy blando | \(V_s \le 180\) |

\(V_s\) promedio ponderado por espesor:
\(V_S = \sum h_n / \sum (h_n/V_n)\).

> ⚠️ VERIFICAR: la tabla de \(S\) por zona y tipo de suelo (Tabla 2 del RNC-07)
> está en el documento oficial; no se reproduce aquí.

Espectro de diseño (Art. 27), pseudoaceleraciones al 5 % de amortiguamiento, con
\(d = 2.7 a_0\), \(T_a = 0.1\) s, \(T_b = 0.6\) s, \(T_c = 2.0\) s:

| Rango | \(a(T)\) |
|---|---|
| \(T < T_a\) | \(S\left[a_0 + (d-a_0)\dfrac{T}{T_a}\right]\) |
| \(T_a \le T \le T_b\) | \(S\,d\) |
| \(T_b \le T \le T_c\) | \(S\,d\,\dfrac{T_b}{T}\) |
| \(T > T_c\) | \(S\,d\,\dfrac{T_b}{T}\left(\dfrac{T_c}{T}\right)^2\) |

Corrección por irregularidad (Art. 23): \(Q' = Q\) si cumple las 12 condiciones;
\(Q' = 0.9Q\) si incumple una; \(Q' = 0.8Q\) si incumple dos o más;
\(Q' = 0.7Q\) si es **fuertemente irregular** (excentricidad torsional estática
\(> 20\,\%\) de la dimensión en planta, o rigidez/resistencia de un entrepiso
\(> 100\,\%\) de la del inferior). En todos los casos \(Q' \ge 1\).

Ductilidad \(Q\) (Anexo B): \(Q = 4\) en marcos especiales a momento de concreto
colados en sitio y en sistemas mixtos donde los marcos toman \(\ge 50\,\%\) del
corte; \(Q = 3\) en marcos especiales donde los marcos toman \(< 50\,\%\);
madera: 3.0 diafragma de contrachapado, 2.0 machihembrado, 1.5 marcos y armaduras.
Acero: leer la Tabla 1B del Anexo B.

Periodo fundamental (Art. 32.B, Rayleigh):

$$T = 2\pi\sqrt{\frac{\sum W_i x_i^2}{g \sum F_{si} x_i}}$$

Fuerzas laterales por nivel (Art. 32.A):

$$F_{si} = c\,W_i\,h_i\,\frac{\sum W_i}{\sum W_i h_i}$$

Reducción por periodo (Art. 32.B):

$$F_{si} = \frac{a}{\Omega Q'}\,W_i\,h_i\,\frac{\sum W_i}{\sum W_i h_i}$$

Torsión (Art. 32.D): excentricidad estática \(e_s = |C_{CM} - C_{CR}|\); la
excentricidad de diseño es la más desfavorable de

$$E_D = 1.5 e_s + 0.1 b, \qquad E_D = e_s - 0.1 b$$

con \(b\) la dimensión en planta perpendicular a la acción sísmica.

Efectos de segundo orden (Art. 32.E): despreciables solo si

$$\frac{\Delta}{H} \le 0.08\,\frac{V}{P_Y}$$

Efectos bidireccionales: 100 % en la dirección analizada + 30 % en la
perpendicular, con los signos desfavorables.

Límites de uso del método estático (Art. 30): estructuras regulares de altura
\(\le 40\) m; irregulares \(\le 30\) m.

Derivas (Art. 34):

- Servicio: desplazamientos \(\Delta_{servicio} = F_{si}\,Q\Omega/2.5\) (si se
  ignoró el periodo) o \(F_{si}\,Q'\Omega/2.5\) (si se consideró el periodo o se
  usó método dinámico). Se acepta si la distorsión de entrepiso no excede **0.002**;
  **0.004** cuando no hay elementos incapaces de soportar deformaciones apreciables
  (p. ej. muros de mampostería).
- Colapso: \(\Delta_{colapso} = F_{si}\,Q\,\Omega\), contrastado con las
  distorsiones máximas de la Tabla 4 del RNC-07.

> ⚠️ VERIFICAR: Tabla 4 del RNC-07 (distorsiones máximas permisibles por tipo de
> estructura) — transcribir a `data/nicaragua/rnc07_drift.json`.

Método dinámico modal espectral (Art. 33): modos suficientes para capturar
\(\ge 90\,\%\) de la masa; combinación CQC (o SRSS si los modos están bien
separados); corrección del cortante basal modal al valor estático cuando resulte
menor.

### B. NSCM-22 — Norma Sismorresistente para la Ciudad de Managua

De linaje ASCE 7 (cita explícitamente las ecuaciones 12.8-6 de ASCE 7-16), con
peligro, espectro y coeficientes propios.

Método de fuerza lateral equivalente (FLE), cortante basal (8.2.1.2):

$$V_b = C_s\,W$$

Coeficiente sísmico (8.2.1.3), con \(p = 0.8\), \(q = 2\):

| Rango | \(C_s\) |
|---|---|
| \(0 \le T \le F_{STc}T_c\) | \(\dfrac{\beta A_0}{R_0}\) |
| \(F_{STc}T_c \le T \le T_d\) | \(\dfrac{\beta A_0}{R_0}\left(\dfrac{F_{STc}T_c}{T}\right)^{p}\) |
| \(T_d \le T\) | \(\dfrac{\beta A_0}{R_0}\left(\dfrac{F_{STc}T_c}{T}\right)^{p}\left(\dfrac{T_d}{T}\right)^{q}\) |

$$C_{s,min} = F_{STc}\,\beta\,\frac{A_0}{R_0}, \qquad A_0 = a_0\,F_{as}\,I$$

con \(a_0\) = aceleración de terreno en roca para periodo cero, \(F_{as}\) = factor
de amplificación por sitio, \(I\) = índice de importancia, \(\beta\) = coeficiente
de aceleración de meseta/\(a_0\), \(R_0\) = factor de comportamiento sísmico.

Distribución vertical de fuerzas (8.2.1.4):

$$F_x = C_{vx}V_b, \qquad C_{vx} = \frac{W_x h_x^k}{\sum_i W_i h_i^k}$$

$$k = 1 \ (T \le 0.5\ \text{s}), \qquad k = 2 \ (T \ge 2.5\ \text{s}), \qquad k = 0.75 + 0.5T\ \text{(intermedio)}$$

Límites de uso del FLE (8.2.1.1): estructuras regulares \(\le 12\) m e irregulares
\(\le 6\) m; en **Zona 1**: 24 m y 12 m respectivamente. No aplica a estructuras
tipo III o IV, ni con irregularidad extrema, ni a las que no cumplen diafragma
rígido, ni cuando el suelo es tipo E.

Espectro elástico \(A(T)\) (6.x), con \(F_{STb}\), \(F_{STc}\) de la Tabla 6.5.1:

| Rango | \(A(T)\) |
|---|---|
| \(0 \le T \le F_{STb}T_b\) | \(A_0\left[1 + \dfrac{T}{F_{STb}T_b}(\beta - 1)\right]\) |
| \(F_{STb}T_b \le T < F_{STc}T_c\) | \(\beta A_0\) |
| \(F_{STc}T_c \le T < T_d\) | \(\beta A_0\left(\dfrac{F_{STc}T_c}{T}\right)^{p}\) |
| \(T_d < T\) | \(\dfrac{\beta A_0}{R_0}\left(\dfrac{F_{STc}T_c}{T}\right)^{p}\left(\dfrac{T_d}{T}\right)^{q}\) |

Espectro reducido para diseño: \(A(T)/R_0\), **excepto** el tramo ascendente
\(0 \le T \le F_{STb}T_b\), que se calcula con

$$A(T) = \left[\frac{A_0 T}{F_{STb}T_b}\left(\frac{\beta}{R_0} - 1\right)\right] + A_0$$

> ⚠️ VERIFICAR: Tabla 6.4.1 (\(T_b\), \(T_c\), \(T_d\) por clase de sitio),
> Tabla 6.5.1 (\(F_{STb}\), \(F_{STc}\)), Tabla 5.5.1 (sismo de diseño por
> categoría de riesgo), Anexo B.3 (categorías), valores de \(\beta\), \(R_0\),
> \(C_d\) y \(\gamma_{max}\) por sistema estructural, y \(a_0\) por zona.
> Se transcriben a `data/nicaragua/nscm22_*.json`.

Corrección del cortante basal modal (8.2.2): si \(V_t < V_b\), escalar las fuerzas
por \(V_b/V_t\). La combinación modal es CQC; las operaciones entre
desplazamientos (derivas) se hacen **por modo** y luego se combinan.

Desplazamientos y derivas (cap. 10):

$$\delta_i = \frac{C_d\,\delta_{ie}}{I}, \qquad \Delta_i = \delta_i - \delta_{i-1}, \qquad \gamma_i = \frac{\Delta_i}{h_i}$$

Límites: tipo I y II \(\gamma \le \gamma_{max}\); tipo III \(\gamma \le 0.75\gamma_{max}\);
tipo IV \(\gamma \le 0.5\gamma_{max}\).

Torsión accidental (9.7–9.8): 5 % de la dimensión del piso perpendicular a la
dirección de análisis; para categorías de diseño C y D,

$$1 \le A_x = \left(\frac{\delta_{max}}{1.2\,\delta_{prom}}\right)^2 \le 3$$

Efectos de segundo orden (P-Δ), \(\theta\):

$$\theta = \frac{P_i \Delta_i I}{V_i h_i C_d}, \qquad \theta_{max} = \frac{0.5}{\beta_{pd} C_d} \le 0.25$$

Efectos bidireccionales: \(E_{hX} = E_X \pm 0.3E_Y\), \(E_{hY} = 0.3E_X \pm E_Y\).

## Procedimiento

1. **Determinar la norma aplicable** por ubicación: Managua → NSCM-22; resto del
   país → RNC-07. Registrar la decisión en el proyecto (no es un ajuste global).
2. Clasificar sitio (\(V_s\)) y obtener la zonificación por coordenada.
3. Calcular \(Q\)/\(R_0\), \(C_d\), \(\Omega\) y la corrección por irregularidad
   (\(Q'\) en RNC-07; irregularidad extrema en NSCM-22).
4. Estimar \(T\) (Rayleigh, o fórmula aproximada + \(C_u\) en NSCM-22) y construir
   el espectro correspondiente.
5. Elegir el método: estático equivalente si cumple los límites de altura y
   regularidad; en caso contrario, modal espectral.
6. Analizar, combinar (CQC + 100/30), amplificar torsión (\(A_x\)) y corregir el
   cortante basal si aplica (NSCM-22).
7. Verificar derivas de servicio y de colapso, y \(\theta\).
8. Emitir el informe con la norma, edición, artículo y valores intermedios.

## Implementación en la plataforma

```python
# opensees_studio/core/codes/nicaragua.py   (core puro)
def rnc07_coefficient(a0: float, S: float, Q: float, Omega: float,
                      Q_prime: float) -> float:
    """c = S*2.7*a0/(Q'*Omega), con el piso c >= S*a0. Devuelve c."""

def rnc07_spectrum(a0: float, S: float) -> Spectrum:
    """a(T) con Ta=0.1, Tb=0.6, Tc=2.0, d=2.7*a0."""

def nscm22_cs(T: float, a0: float, Fas: float, I: float, beta: float,
              R0: float, FSTc: float, Tc: float, Td: float) -> float:
    """Cs por tramos (ecs. 2.31-2.33) y su minimo (ec. 2.34)."""

def nscm22_spectrum(...) -> Spectrum:
    """A(T) elastico y reducido (ecs. 2.47-2.52)."""
```

Reglas:

- La **norma aplicable se resuelve por ubicación** en `core/codes/registry.py`, y el
  proyecto guarda el `code_id` resuelto con su edición; un cambio normativo no debe
  reinterpretar proyectos históricos.
- Todos los coeficientes en `data/nicaragua/*.json` con `source` y `verified_on`.
- Los dos métodos conviven: el objeto `SeismicCode` expone `elf()` y `modal()`.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(c = S(2.7a_0)/(Q'\Omega)\); \(c_{min}=S a_0\) | RNC-07 Art. 24 | sí |
| \(F_c = c W_0\); \(W_0 = CM + CVR\) | RNC-07 Art. 27 | sí |
| \(T_a = 0.1\), \(T_b = 0.6\), \(T_c = 2.0\) s; \(d = 2.7a_0\) | RNC-07 Art. 27 | sí |
| \(Q' = \{1, 0.9, 0.8, 0.7\}Q\) por irregularidad | RNC-07 Art. 23 | sí |
| \(E_D = 1.5e_s \pm 0.1b\); \(e_s - 0.1b\) | RNC-07 Art. 32.D | sí |
| \(\Delta/H \le 0.08\,V/P_Y\) | RNC-07 Art. 32.E | sí |
| Derivas de servicio 0.002 / 0.004 | RNC-07 Art. 34 | sí |
| Límites del método estático (40 m / 30 m) | RNC-07 Art. 30 | sí |
| \(a_0\) por zona (A 0.10, B 0.20, C 0.30 g) | RNC-07 Anexo C | parcial — `VERIFICAR` |
| Tabla de \(S\) por zona y tipo de suelo | RNC-07 Art. 25 | no — `VERIFICAR` |
| Tabla 4 (distorsiones máximas) | RNC-07 | no — `VERIFICAR` |
| \(V_b = C_s W\); tramos de \(C_s\); \(C_{s,min}\) | NSCM-22 8.2.1 | sí |
| \(k\) de distribución vertical | NSCM-22 8.2.1.4 | sí |
| Límites del FLE (12/6 m; Z1 24/12 m; no en suelo E) | NSCM-22 8.2.1.1 | sí |
| \(A(T)\) por tramos (2.47–2.50) y reducción (2.51–2.52) | NSCM-22 cap. 6 | sí |
| \(\delta_i = C_d\delta_{ie}/I\); límites 1.0/0.75/0.5 \(\gamma_{max}\) | NSCM-22 cap. 10 | sí |
| \(A_x\); 5 % de torsión accidental; \(\theta\) | NSCM-22 9.7–9.8 | sí |
| \(\beta\), \(R_0\), \(C_d\), \(\gamma_{max}\), \(T_b\), \(T_c\), \(T_d\), \(F_{STb}\), \(F_{STc}\), \(a_0\) | NSCM-22 tablas | no — `VERIFICAR` |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| \(c\) RNC-07 | \(S=1.0\), \(a_0=0.2\), \(Q'=3\), \(\Omega=2\) | \(c = 0.09\) | 1e-9 |
| Piso de \(c\) | \(S=1.0\), \(a_0=0.3\), \(Q'=4\), \(\Omega=2\) | \(c = 0.10125 \to c_{min}=0.3\) | 1e-9 |
| Espectro RNC-07, meseta | \(T=0.3\) s, \(S=1\), \(a_0=0.2\) | \(a = 0.54\,g\) | 1e-9 |
| Espectro RNC-07, rama 1/T | \(T=2.0\) s | \(a = 0.162\,g\) | 1e-9 |
| Espectro RNC-07, cola | \(T=4.0\) s | \(a = 0.0405\,g\) | 1e-9 |
| \(k\) NSCM-22 | \(T = 1.0\) s | \(k = 1.25\) | 1e-9 |
| \(C_s\) meseta | \(\beta A_0 = 0.6\), \(R_0 = 6\) | \(C_s = 0.1\) | 1e-9 |
| \(A_x\) | \(\delta_{max} = 1.2\delta_{prom}\) | \(A_x = 1.0\) | 1e-9 |
| Reparto vertical | 2 niveles iguales, \(k=1\) | \(F_1/F_2 = h_1/h_2\) | 1e-9 |

Contraste obligatorio: reproducir un modelo del estudio comparativo RNC-07 vs
NSCM-22 (edificio de concreto de 3 niveles, \(V_s = 360\) m/s, Managua) y comparar
cortante basal y derivas con los reportados por el análisis de referencia, dentro
del 5 %.

## Errores frecuentes y trampas

1. **Aplicar RNC-07 en Managua.** Desde 2022 rige NSCM-22; usar RNC-07 allí
   subestima o distorsiona la demanda.
2. Confundir \(Q\) (ductilidad, Anexo B) con \(Q'\) (corregido por irregularidad) y
   con \(\Omega\) (sobrerresistencia). Son tres cosas distintas que se multiplican.
3. Olvidar que \(Q'\) **nunca** baja de 1.
4. Usar \(c_{min} = S a_0\) como cortante en vez de como piso del coeficiente.
5. En NSCM-22, reducir el tramo ascendente del espectro con \(/R_0\): ese tramo
   tiene su propia ecuación (2.52).
6. Confundir \(A_0 = a_0 F_{as} I\) con \(a_0\) a secas.
7. Aplicar el FLE fuera de sus límites de altura o en suelo tipo E.
8. Calcular derivas restando desplazamientos **ya combinados** en vez de combinar
   las derivas modales.
9. Ignorar la corrección \(V_b/V_t\) del cortante basal modal.
10. Mezclar el peso sísmico (\(CM + CVR\)) con la carga gravitacional de diseño.

## Interfaz de salida

- Norma aplicada (`RNC-07` o `NSCM-22`), edición, y la regla de selección usada.
- Zona sísmica, \(a_0\), clase/tipo de suelo, \(S\) o \(F_{as}\), y su cita.
- \(Q\), \(Q'\), \(\Omega\) (RNC-07) o \(R_0\), \(C_d\), \(I\) (NSCM-22), con la
  justificación de la corrección por irregularidad (qué condiciones fallaron).
- \(c\) o \(C_s\), \(W\), \(V\)/\(V_b\), \(T\), y la comparación con el mínimo.
- Cortantes y fuerzas por nivel, torsión de diseño (\(E_D\) o 5 % + \(A_x\)).
- Derivas de servicio y colapso con el límite aplicable y el veredicto.
- \(\theta\) y la decisión de amplificar o no.
- Advertencias: método fuera de límites, datos de tabla no verificados,
  irregularidades detectadas.

## Referencias

1. MTI, *Reglamento Nacional de la Construcción (RNC-07)*, Nicaragua, 2007
   (Arts. 20–34 y Anexos B y C).
2. MTI, *Norma Sismorresistente para la Ciudad de Managua (NSCM-22)*, Nicaragua,
   2022 (secciones 5, 6, 8.2, 9 y 10).
3. M. A. R. y otros, *Análisis comparativo entre métodos lineales del RNC-07 y
   NSCM-22, aplicado a edificios ubicados en la ciudad de Managua*, UNI, Nicaragua
   — fuente de contraste numérico y de la formulación aquí resumida.
4. ACI 318 (edición referida por el RNC-07: ACI 318-02, cap. 21) — detallado
   sismorresistente.
5. ASCE/SEI 7-16 — base metodológica citada por NSCM-22.

## Registro de verificación

- **Verificado** contra la formulación transcrita en el estudio comparativo UNI y
  sus citas al RNC-07 y NSCM-22: cocientes del coeficiente sísmico, espectro de
  cuatro ramas con \(T_a/T_b/T_c\) de RNC-07, corrección \(Q'\), torsión, P-Δ,
  derivas de servicio, \(V_b = C_sW\), tramos de \(C_s\), exponente \(k\),
  espectro NSCM-22 (ecs. 2.47–2.52), \(C_d\delta_{ie}/I\), \(A_x\) y \(\theta\).
- **Pendiente**: valores numéricos de las tablas del RNC-07 (Anexo C, \(S\),
  Tabla 4) y de NSCM-22 (6.4.1, 6.5.1, 5.5.1, \(\beta\), \(R_0\), \(C_d\),
  \(\gamma_{max}\)); deben leerse del documento oficial del MTI y cargarse en
  `data/nicaragua/`.
- **Responsable de cerrar**: ingeniero estructural con registro en Nicaragua, con
  copia oficial de ambos documentos.
