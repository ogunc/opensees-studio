---
name: asce7-22-seismic-design
description: >-
  Implementa y verifica el análisis y el diseño sísmico conforme a ASCE/SEI 7-22:
  espectros de diseño multi-periodo modificados por sitio (sin Fa ni Fv), SDS/SD1,
  categoría de diseño sísmico, sistema estructural resistente a fuerzas sísmicas
  (R, Cd, Ω0), torsión accidental, P-Δ, límites de deriva y combinaciones con sismo.
  Úsala cuando el proyecto se rige por ASCE 7-22, cuando hay que construir un
  espectro de diseño estadounidense, o cuando se audita un módulo sísmico existente
  contra el capítulo 11 y 12.
metadata:
  track: codes
  jurisdiction: USA
  edition: "ASCE/SEI 7-22"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# ASCE 7-22 — Análisis y diseño sísmico

## Cuándo usar esta skill

- El proyecto declara `code = ASCE 7-22` (o el IBC 2024, que lo adopta).
- Hay que generar el espectro de diseño a partir de las aceleraciones del lugar.
- Hay que clasificar la estructura en una *Seismic Design Category* (SDC) y decidir
  qué procedimiento de análisis permite el código.
- Hay que auditar un módulo sísmico ya escrito: el 90 % de los defectos vienen de
  arrastrar la formulación de ASCE 7-16 (con \(F_a\) y \(F_v\)) a un proyecto 7-22.

**No usar** para códigos nacionales latinoamericanos: ver `codes/nicaragua-rnc07-nscm22`,
`codes/mexico-ntc-rcdf-cfe`, `codes/colombia-nsr10`, `codes/peru-e030`,
`codes/chile-nch433-nch2369`, `codes/ecuador-nec15`.

## Alcance y límites

Cubre los capítulos 11 (parámetros sísmicos y SDC), 12 (edificios), 13 (no
estructural), 15 (no edificaciones), 16 (conexiones) y las combinaciones del
capítulo 2 en lo que toca al sismo. **No cubre** el diseño de los elementos
(→ `design/concrete-aci318`, `design/steel-aisc360-341`) ni el análisis del
suelo (→ `design/foundations-and-soil-structure`).

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Ubicación (lat/lon o ciudad) | sí | bloquear: no se inventa el peligro |
| Clase de sitio (A–F) | sí | usar el procedimiento del cap. 20/21 para clasificar o pedir Vs30 |
| Categoría de riesgo (I–IV) | sí | bloquear |
| Sistema estructural resistente | sí | bloquear (define \(R\), \(C_d\), \(\Omega_0\)) |
| Altura, número de pisos, masas | sí | bloquear |
| Configuración (regular/irregular) | sí | evaluar según Tabla 12.3-1 y 12.3-2 |
| Espectro MCEr del sitio | sí en 7-22 | obtener del servicio de peligro USGS o de la tabla del proyecto |

## Fundamento y formulación

### 1. Cambio estructural de ASCE 7-22: espectros multi-periodo

ASCE 7-22 **abandona los coeficientes de sitio \(F_a\) y \(F_v\)**. El punto de
partida ya no es \((S_S, S_1)\) sino los valores **modificados por sitio**
\((S_{MS}, S_{M1})\) en varios períodos, obtenidos del modelo multi-periodo del
USGS. \(S_S\) y \(S_1\) quedan solo como **disparadores** de requisitos puntuales
(p. ej. exigencias de sitio específico).

Consecuencia de implementación: el espectro de diseño 7-22 no se puede reconstruir
con la forma de dos puntos de 7-16. El programa debe consumir una **tabla de
períodos vs. aceleración** (multi-periodo) y aplicar el factor 2/3.

> ⚠️ VERIFICAR: la definición exacta de la malla de períodos y de la forma del
> espectro multi-periodo (§11.4.4 y §11.4.5 de ASCE 7-22) debe transcribirse del
> estándar impreso o del informe del USGS, no de una fuente secundaria.
> Hasta entonces el programa lee el espectro de un archivo de datos versionado
> (`data/asce7-22/<sitio>.json`) con campo `source`.

### 2. Parámetros de la ordenada espectral

$$S_{DS} = \tfrac{2}{3} S_{MS}, \qquad S_{D1} = \tfrac{2}{3} S_{M1}$$

$$T_0 = 0.2\,\frac{S_{D1}}{S_{DS}}, \qquad T_s = \frac{S_{D1}}{S_{DS}}$$

Espectro de diseño (períodos en s, aceleraciones en g):

| Rango | \(S_a(T)\) |
|---|---|
| \(T < T_0\) | \(S_{DS}\,(0.4 + 0.6\,T/T_0)\) |
| \(T_0 \le T \le T_s\) | \(S_{DS}\) |
| \(T_s < T \le T_L\) | \(S_{D1}/T\) |
| \(T > T_L\) | \(S_{D1}\,T_L/T^2\) |

\(T_L\) es el período de transición a período largo del mapa (§11.4.5) y **no** es
una constante 6 s ni 8 s (a diferencia de TBDY o de aproximaciones de otros
códigos). Se lee del archivo de peligro del sitio.

### 3. Categoría de diseño sísmico (SDC)

La SDC se asigna por riesgo y por \(S_{DS}\) / \(S_{D1}\) según Tablas 11.6-1 y
11.6-2, con el ajuste por clase de sitio y el criterio adicional de \(T_s\). La SDC
gobierna: procedimiento de análisis permitido, requisitos de detallado, torsión
y límites de deriva.

> ⚠️ VERIFICAR: los cortes exactos de las Tablas 11.6-1 y 11.6-2 de ASCE 7-22
> (cambiaron respecto a 7-16 en varios sitios de suelo blando).
> Se transcriben a `data/asce7-22/sdc.json` con prueba unitaria.

### 4. Coeficientes del sistema estructural

Subconjunto verificado de la Tabla 12.2-1 (para datos de referencia; el programa
lee la tabla completa del archivo de datos):

| Sistema | \(R\) | \(C_d\) | \(\Omega_0\) |
|---|---|---|---|
| Pórtico especial de acero resistente a momento (SMF) | 8 | 5.5 | 3 |
| Pórtico intermedio de acero a momento (IMF) | 4.5 | 4 | 3 |
| Pórtico ordinario de acero a momento (OMF) | 3.5 | 3 | 3 |
| Pórtico especial de concreto a momento (SMF) | 8 | 5.5 | 3 |
| Pórtico intermedio de concreto a momento (IMF) | 5 | 4.5 | 3 |
| Pórtico ordinario de concreto a momento (OMF) | 3 | 2.5 | 3 |
| Arriostramiento concéntrico especial de acero (SCBF) | 6 | 5 | 2 |
| Arriostramiento concéntrico ordinario de acero (OCBF) | 3.25 | 3.25 | 2 |
| Muros especiales de concreto (bearing wall) | 5 | 5 | 2.5 |
| Pórticos arriostrados con pandeo restringido (BRBF) | 8 | 5 | 2.5 |
| Muros de corte de madera (light-frame) | 6.5 | 4 | 3 |

> ⚠️ VERIFICAR: la Tabla 12.2-1 completa (más de 80 sistemas, con límites de
> altura \(h_n\) y restricciones por SDC) no se transcribe aquí.
> Regla del programa: **estos tres coeficientes nunca se escriben en el código**,
> se leen de `data/asce7-22/systems.json` con su cita y su límite de altura.

### 5. Fuerza sísmica y combinaciones

Procedimiento de fuerza lateral equivalente (§12.8):

$$V = C_s W, \qquad C_s = \frac{S_{DS}}{R/I_e}$$

con los topes \(C_s \le S_{D1}/(T\,R/I_e)\) para \(T \le T_L\),
\(C_s \le S_{D1}T_L/(T^2 R/I_e)\) para \(T > T_L\), y
\(C_s \ge 0.044\,S_{DS}I_e \ge 0.01\).

Distribución en altura (§12.8.3):

$$F_x = C_{vx}V, \qquad C_{vx} = \frac{w_x h_x^k}{\sum_i w_i h_i^k}$$

con \(k = 1\) para \(T \le 0.5\ \text{s}\), \(k = 2\) para \(T \ge 2.5\ \text{s}\) y
\(k = 0.5T + 0.75\) para \(0.5 < T < 2.5\ \text{s}\) (a \(T = 1.0\) s, \(k = 1.25\)).

Efecto sísmico y vertical (§12.4.2):

$$E = E_h + E_v, \qquad E_v = 0.2\,S_{DS}\,D, \qquad E_h = \rho\,Q_E$$

Combinaciones LRFD (§2.3.1) y ASD (§2.3.6) — ver
`seismic/load-combinations-and-limit-states` para la tabla completa y para el
tratamiento de \(\rho\) (factor de redundancia, §12.3.4).

### 6. Torsión, P-Δ y ortogonalidad

- **Torsión accidental** (§12.8.4.2): desplazar la masa de cada nivel una distancia
  igual al **5 % de la dimensión perpendicular** a la dirección de las fuerzas.
- **Amplificación torsional** \(A_x\) (§12.8.4.3) para SDC C–F:
  \(1 \le A_x = (\delta_{max}/(1.2\,\delta_{avg}))^2 \le 3\).
- **Estabilidad (P-Δ)** (§12.8.7):
  \(\theta = \dfrac{P_x \Delta I_e}{V_x h_{sx} C_d} \le \dfrac{0.5}{\beta C_d} \le 0.25\).
  Si \(\theta \le 0.10\) no se amplifican los efectos; si \(0.10 < \theta \le \theta_{max}\),
  multiplicar desplazamientos y fuerzas por \(1/(1-\theta)\).
- **Efectos ortogonales** (§12.5.4): 100 % en una dirección + 30 % en la
  perpendicular, o SRSS.

### 7. Límites de deriva

\(\delta_x = C_d\,\delta_{xe}/I_e\); deriva de entrepiso \(\Delta_a = \delta_x/h_{sx}\).
Límites de la Tabla 12.12-1 (estructuras de 4 pisos o menos vs. el resto, y por
categoría de riesgo): del orden de 0.025 / 0.020 / 0.015 / 0.010 según el caso.

> ⚠️ VERIFICAR: transcribir la Tabla 12.12-1 completa (filas por \(T < 0.7\) s y
> \(T \ge 0.7\) s, columnas por categoría de riesgo y por ocupación de 4 horas o
> más) a `data/asce7-22/drift.json`.

## Procedimiento

1. Resolver clase de sitio y peligro (tabla multi-periodo del sitio).
2. Calcular \(S_{MS}\), \(S_{M1}\) en la malla de períodos y luego \(S_{DS}\), \(S_{D1}\).
3. Construir \(S_a(T)\) con las cuatro ramas y graficarla contra los puntos del
   peligro para detectar inconsistencias de datos.
4. Asignar SDC (Tablas 11.6-1/11.6-2) y verificar los límites de altura y las
   restricciones del sistema estructural elegido.
5. Seleccionar el procedimiento de análisis (§12.6): ELF, modal espectral o
   historia de respuesta, con las restricciones de regularidad y altura.
6. Calcular \(V\), distribuir \(F_x\), aplicar torsión accidental y \(A_x\).
7. Resolver, combinar, amplificar por \(\rho\) y \(\Omega_0\) donde corresponda.
8. Verificar derivas, \(\theta\) y resistencia; emitir el informe de cumplimiento.

## Implementación en la plataforma

```python
# opensees_studio/core/codes/asce7_22.py   (core puro: sin Qt, sin openseespy)
def design_spectrum(hazard: HazardTable, code_data: CodeData) -> Spectrum:
    """Sa(T) de diseño. hazard trae la malla multi-periodo; code_data, los cortes de SDC."""

def sdc(sds: float, sd1: float, risk: RiskCategory, site: SiteClass,
        code_data: CodeData) -> str: ...

def design_system(system_id: str, code_data: CodeData) -> DesignSystem:
    """R, Cd, Omega0, limite de altura y restricciones de SDC. Lee systems.json."""
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):

- El módulo de código vive en `core/` y **no** importa Qt ni OpenSeesPy.
- Los coeficientes vienen de `data/asce7-22/*.json`, nunca del código.
- La generación del espectro es pura: entra un sitio + categoría, sale una curva.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(S_{DS} = \tfrac{2}{3}S_{MS}\), \(S_{D1} = \tfrac{2}{3}S_{M1}\) | ASCE 7-22 §11.4.5 | sí |
| \(T_0 = 0.2 S_{D1}/S_{DS}\), \(T_s = S_{D1}/S_{DS}\) | ASCE 7-22 §11.4.5 | sí |
| Eliminación de \(F_a\) y \(F_v\) en favor de valores multi-periodo | ASCE 7-22 cap. 11 | sí (confirmado en literatura técnica) |
| \(E_v = 0.2 S_{DS} D\); \(E_h = \rho Q_E\) | ASCE 7-22 §12.4.2 | sí |
| \(k\) de distribución vertical | ASCE 7-22 §12.8.3 | sí |
| Tabla 12.2-1 completa | ASCE 7-22 | no — `VERIFICAR` |
| Tablas 11.6-1 / 11.6-2 (SDC) | ASCE 7-22 | no — `VERIFICAR` |
| Tabla 12.12-1 (derivas) | ASCE 7-22 | no — `VERIFICAR` |
| Enmienda del piso de aceleración para clases DE y E en el CEUS | Supplement No. 5 a ASCE 7-22 / Code Change S102-25 | pendiente de publicación; el programa debe permitir activar/desactivar el piso |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| \(T_0\), \(T_s\) | \(S_{DS}=1.0\), \(S_{D1}=0.6\) | \(T_0 = 0.12\) s, \(T_s = 0.6\) s | 1e-9 |
| Meseta | \(T = 0.3\) s con los datos anteriores | \(S_a = 1.0\,g\) | 1e-9 |
| Rama hiperbólica | \(T = 1.2\) s, \(T_L = 8\) s | \(S_a = 0.5\,g\) | 1e-9 |
| Rama de desplazamiento | \(T = 16\) s, \(T_L = 8\) s | \(S_a = 0.1875\,g\) | 1e-9 |
| \(C_s\) mínimo | \(S_{DS}=0.2\), \(I_e=1.0\) | \(C_s \ge 0.01\) | 1e-9 |
| \(k\) interpolado | \(T = 1.0\) s | \(k = 0.5(1.0) + 0.75 = 1.25\) | 1e-9 |
| \(\theta_{max}\) | \(C_d = 5.5\), \(\beta = 1\) | \(0.0909 \le 0.25\) | 1e-6 |

Además: contraste obligatorio del espectro generado contra la herramienta oficial
de peligro del USGS para al menos dos sitios (uno del oeste y uno del este) y
contra los ejemplos del capítulo 12.

## Errores frecuentes y trampas

1. **Usar \(F_a\)/\(F_v\) en 7-22.** Es el error más grave: produce aceleraciones
   que no corresponden al estándar vigente.
2. Confundir \(S_{MS}\) (modificado por sitio) con \(S_S\) (del mapa, sin modificar).
3. Tratar \(T_L\) como constante (6 s, 8 s). Se lee del peligro del sitio.
4. Olvidar el factor de redundancia \(\rho\) en \(E_h\).
5. Aplicar \(A_x\) fuera del rango \([1, 3]\) o a categorías que no lo requieren.
6. Mezclar \(R\) de ASCE 7 con \(q\) o \(R_0\) de un código nacional en el mismo
   modelo.
7. Comparar derivas con \(\delta_{xe}\) en vez de \(C_d\delta_{xe}/I_e\).
8. Ignorar que la SDC puede cambiar entre 7-16 y 7-22 en suelos blandos del este
   de EE. UU., invalidando un diseño anterior.
9. Redondear \(S_{DS}\) antes de calcular \(C_s\).

## Interfaz de salida

El programa debe reportar, para cada dirección de análisis:

- Clase de sitio, categoría de riesgo, \(S_{MS}\), \(S_{M1}\), \(S_{DS}\), \(S_{D1}\),
  \(T_0\), \(T_s\), \(T_L\) y **la fuente** de cada uno (archivo de peligro + cita).
- SDC asignada y la razón.
- Sistema estructural, \(R\), \(C_d\), \(\Omega_0\), \(\rho\), con cita de Tabla 12.2-1.
- Procedimiento de análisis utilizado y la comprobación de sus límites de uso.
- \(V\), \(C_s\), \(T\) calculado y \(T\) aproximado, distribución de fuerzas.
- Derivas por entrepiso, \(\theta\), \(A_x\), y el veredicto con el artículo aplicable.
- Advertencias activas (p. ej. enmienda del piso de aceleración activada).

## Referencias

1. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and
   Other Structures*. Capítulos 2, 11, 12, 13, 15, 16, 20, 21, 22.
2. USGS, *Seismic Hazard Maps and Site-Specific Data* — modelo multi-periodo
   empleado por ASCE 7-22.
3. S. K. Ghosh Associates, *Understanding the Multi-Period, Soil-Modified Design
   Response Spectra of ASCE 7-22* (2026) — análisis de la pérdida de amplificación
   en suelos blandos del CEUS.
4. BSSC, *NEHRP Recommended Seismic Provisions* — comentarios de respaldo.
5. ICC, *Code Change S102-25* (2026 Public Comment Agenda) — piso de aceleración
   para clases de sitio DE y E.

## Registro de verificación

- **Verificado**: la eliminación de \(F_a\)/\(F_v\) y el uso de valores
  multi-periodo en ASCE 7-22; las expresiones de \(S_{DS}\), \(S_{D1}\), \(T_0\),
  \(T_s\) y las cuatro ramas del espectro; \(E_v = 0.2 S_{DS} D\); el exponente
  \(k\); la forma de \(\theta\) y \(A_x\).
- **Pendiente**: transcripción de las Tablas 12.2-1, 11.6-1/11.6-2 y 12.12-1;
  malla exacta de períodos del espectro multi-periodo (requiere el estándar
  impreso); estado de publicación del Supplement No. 5.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia
  licenciada de ASCE 7-22.
