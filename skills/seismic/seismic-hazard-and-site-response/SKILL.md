---
name: seismic-hazard-and-site-response
description: >-
  Define el peligro sísmico y la respuesta de sitio: niveles de peligro
  (servicio, diseño, máximo considerado), conversión entre período de retorno y
  probabilidad de excedencia en 50 años, peligro uniforme frente a riesgo
  uniforme, lectura de mapas y servicios de peligro (PGA y ordenadas
  espectrales), clasificación de sitio por Vs30 con correlaciones N-SPT y cu
  sobre perfiles estratificados, amplificación por sitio (lineal equivalente,
  funciones de transferencia y factores de código) y plantillas de espectro de
  diseño reutilizables. Úsala al construir o auditar un espectro de diseño, al
  clasificar un sitio, al decidir si se exige un estudio de sitio específico, o
  cuando el programa debe elegir entre un espectro normativo y uno calculado.
metadata:
  track: seismic
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, qa]
---

# Peligro sísmico y respuesta de sitio

## Cuándo usar esta skill

- Hay que fijar el **nivel de peligro** (servicio, diseño, máximo considerado) y traducirlo a período de retorno \(T_R\) o a probabilidad \(p\) de excedencia.
- Hay que **clasificar el sitio** a partir de un perfil de \(V_s\), de golpeos SPT, de \(c_u\), o de los tres a la vez.
- Hay que **construir un espectro de diseño** y elegir plantilla: dos puntos, multi-periodo, meseta con hipérbola y cola de desplazamiento.
- El programa debe decidir si el espectro normativo es admisible o si el código **exige estudio de sitio específico** (clase F, suelos blandos profundos, licuación, período largo).
- Se audita un módulo existente: los defectos típicos son doble amplificación por sitio, \(V_{s30}\) extrapolado más allá de los 30 m medidos y confusión entre aceleración del mapa y aceleración modificada por sitio.
- **No usar** para el diseño de elementos (→ `codes/asce7-22-seismic-design`, `codes/nicaragua-rnc07-nscm22`, `codes/code-crosswalk-and-extension`), interacción suelo–estructura (→ `design/foundations-and-soil-structure`), selección y escalado de registros (→ `seismic/ground-motion-selection-and-scaling`) ni combinación modal (→ `core/modal-and-time-history`).

## Alcance y límites

Cubre parámetros de peligro y su conversión probabilista, lectura trazable de mapas y servicios de peligro, clasificación de sitio, amplificación por sitio (analítica y normativa) y el registro de plantillas de espectro compartido por todos los códigos soportados.

**No cubre** el método de análisis (ELF, modal espectral, historia de respuesta), los coeficientes de sistema estructural \(R\), \(C_d\), \(\Omega_0\), los límites de deriva, las combinaciones de carga ni el detallado. Tampoco la amenaza geológica no vibratoria (falla superficial, deslizamiento, asentamiento) más allá de declararla disparador de estudio específico. Supuestos: movimiento horizontal, propagación vertical de ondas SH, comportamiento 1D del depósito, propiedades constantes por capa; los efectos 2D/3D (cuenca, topografía, ondas superficiales) quedan fuera y deben declararse como no capturados.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Ubicación (lat/lon) y datum | sí | bloquear: no se inventa el peligro |
| Nivel de peligro objetivo (\(T_R\) o \(p\)) | sí | usar el del código sólo si el código lo fija; si no, bloquear |
| Perfil de \(V_s\), o \(\bar N_{60}\), o \(\bar s_u\) por capas | sí | bloquear la clase; no asumir D sin declararlo |
| Espesor y \(V_s\) del basamento (medio de referencia) | sí para respuesta de sitio | bloquear: define el contraste de impedancia |
| Curvas \(G/G_{max}(\gamma)\) y \(\xi(\gamma)\) | sí para lineal equivalente | usar biblioteca declarada por material e IP, con cita |
| Registro o espectro de entrada en roca | sí | bloquear: la amplificación no es un factor suelto |
| Categoría de riesgo y período fundamental estimado | sí | bloquear (fijan el nivel de peligro y el chequeo de período largo) |
| Unidades del modelo | sí | SI coherente (m, m/s, kg/m³, Pa, s) |

Ningún dato faltante se sustituye por un valor por defecto silencioso. Si el código autoriza un valor por defecto (p. ej. asumir una clase de sitio sin datos), el programa lo aplica **declarándolo en la salida** y marcando el resultado como no verificado en sitio.

## Fundamento y formulación

### 1. Niveles de peligro y período de retorno
Con el modelo de Poisson (estándar en peligro sísmico), \(t\) en años y \(p\) adimensional:

$$p = 1 - \exp\!\left(-\frac{t}{T_R}\right) \qquad\Longleftrightarrow\qquad T_R = \frac{-t}{\ln(1-p)}$$

La forma binomial, aún usada por algunas normas, difiere: \(p = 1 - (1 - 1/T_R)^{t}\). Para \(p = 0.10\), \(t = 50\) a: Poisson da \(T_R = 474.56\) a y la binomial \(475.13\) a; la diferencia (0.1 %) es irrelevante para el diseño pero **debe declararse la convención**. Niveles usuales: servicio \(\approx 50\%\) en 50 a (\(T_R \approx 72\) a), diseño \(\approx 10\%\) en 50 a, máximo considerado \(\approx 2\%\) en 50 a.

### 2. Peligro uniforme frente a riesgo uniforme
El **espectro de peligro uniforme (UHS)** toma en cada período la ordenada con la misma probabilidad anual de excedencia; no corresponde a un sismo real, es envolvente de muchos escenarios y sobreestima la demanda de período largo cuando el escenario dominante de corto período es otro. El **espectro de riesgo uniforme (URS)** escala el movimiento a una probabilidad objetivo de respuesta estructural inelástica (colapso), no de excedencia de la aceleración; los mapas de ASCE 7 son de este tipo desde 7-10 y el espectro de diseño es una fracción del movimiento de riesgo uniforme:

$$S_a^{dis}(T) = \tfrac{2}{3}\,S_a^{MCEr}(T) \quad \text{(ASCE 7-22, §11.4.5)}$$

El factor \(2/3\) y el escalado de riesgo son pasos distintos y **no se apilan dos veces**: un espectro de sitio específico calculado por historia de respuesta ya está en el nivel pedido.

### 3. Mapas y servicios de peligro: PGA y ordenadas espectrales
Fuentes: mapas del USGS (NSHM) y su servicio de diseño (`earthquake.usgs.gov/ws/designmaps`), más los mapas nacionales equivalentes (SGC en Colombia, AFAD/TDTH en Turquía, CENAPRED/CFE en México, IGP en Perú, INPRES en Argentina). El programa guarda **la respuesta cruda** del servicio y la fecha de consulta, no sólo el número extraído.

La **PGA** es la aceleración máxima del terreno, no una ordenada espectral de período nulo; los mapas modernos la reportan a \(T = 0.01\) s y no debe interpolarse \(S_a(T \to 0)\) como si el espectro fuese continuo en el origen. Aceleraciones efectivas de pico (ATC-3-06 / NEHRP), con \(S_a\) en g y el divisor 2.5 como constante de definición:

$$EPA = \frac{1}{0.4}\int_{0.1}^{0.5} S_a(T)\,dT \Big/ 2.5, \qquad EPV = \frac{S_a(1\ \text{s})}{2.5}$$

> ⚠️ VERIFICAR: la definición de componente del movimiento publicada por cada mapa (media geométrica, `GMRotI50`, `RotD50` o dirección máxima) y el endpoint/versión exactos del servicio. Se comprueba en la documentación del servicio y en el capítulo de peligro del código aplicable. El programa registra componente y fecha en el archivo de datos y no mezcla componentes distintas en una misma curva.

### 4. Clasificación de sitio por \(V_{s30}\)
Promedio por **tiempo de recorrido**, no aritmético, con \(d_i\) en m y \(V_{si}\) en m/s:

$$V_{s30} = \frac{30\ \text{m}}{\displaystyle\sum_{i=1}^{n} \frac{d_i}{V_{si}}}, \qquad \sum_i d_i = 30\ \text{m}$$

Una capa que cruza los 30 m aporta sólo su espesor parcial. Si el basamento está a menos de 30 m, \(V_{s30}\) no está definido por medición: se declara la profundidad real, se reporta la \(V_s\) del basamento y se aplica el procedimiento del código para suelos someros.

| Clase (ASCE 7-22, Table 20.3-1) | \(V_{s30}\) (m/s) | \(\bar N\) o \(\bar N_{ch}\) | \(\bar s_u\) (kPa) |
|---|---|---|---|
| A — roca dura | \(> 1500\) | — | — |
| B — roca | \(760 < V_{s30} \le 1500\) | — | — |
| C — suelo muy denso / roca blanda | \(360 < V_{s30} \le 760\) | \(> 50\) | \(> 100\) |
| D — suelo rígido | \(180 < V_{s30} \le 360\) | \(15 \le \bar N \le 50\) | \(50 \le \bar s_u \le 100\) |
| E — suelo blando | \(< 180\) | \(< 15\) | \(< 50\) |
| F — requiere evaluación específica | — | — | — |

> ⚠️ VERIFICAR: la transcripción literal de ASCE 7-22 Table 20.3-1 (ubicación de las igualdades en los límites, columnas \(\bar N\)/\(\bar s_u\), notas al pie, clase F) y la precedencia entre los tres criterios. Se comprueba en el estándar impreso. El programa lee los cortes de `data/seismic/site_classes.json` con `source` y `verified_on`.

Medición directa de \(V_s\): downhole, crosshole, cono sísmico (SCPT), perfilaje PS por suspensión, refracción, MASW/SASW, arreglos de microtremor. La técnica HVSR da la frecuencia fundamental del sitio, **no** un perfil de \(V_s\): sólo clasifica combinada con una inversión declarada y su incertidumbre. Correlaciones \(N_{SPT} \to V_s\) en la forma \(V_s = a\,N_{60}^{\,b}\) (\(V_s\) en m/s) — Imai & Tonouchi (1982): \(a = 97\), \(b = 0.314\); Ohba & Toriumi (1970): \(a = 84\), \(b = 0.31\); Athanasopoulos (1995): \(a = 107.6\), \(b = 0.36\). Para arcillas, \(V_s = \alpha\,s_u^{\,\beta}\) con \(s_u\) en kPa y coeficientes dependientes del índice de plasticidad.

> ⚠️ VERIFICAR: los coeficientes de cada correlación deben contrastarse con el artículo original, incluida la definición de \(N_{60}\) y el rango de suelos válido. El programa los lee de `data/seismic/vs_correlations.json`, cada entrada con cita y rango.

En perfil estratificado se clasifica con el criterio que gobierne el comportamiento, no con el promedio de clases: si \(V_s\), \(N\) y \(s_u\) dan clases distintas, se reporta la más desfavorable y se documenta la discrepancia.

### 5. Amplificación por sitio
Capa viscoelástica sobre base rígida, ondas SH verticales, \(k^* = \omega/(V_s\sqrt{1+2i\xi})\), \(V_s\) en m/s y \(\xi\) adimensional:

$$H_r(\omega) = \frac{1}{\cos(k^*H)}, \qquad H_e(\omega) = \frac{1}{\cos(k^*H) + i\,\alpha^*\sin(k^*H)}, \qquad |H_r(\omega)| = \left[\cos^2\!\left(\frac{\omega H}{V_s}\right) + \sinh^2\!\left(\frac{\xi\,\omega H}{V_s}\right)\right]^{-1/2}$$

donde \(H_r\) es la solución de base rígida y \(H_e\) la de base elástica referida al afloramiento rocoso, con razón de impedancia \(\alpha^* = \rho_b V_{sb}^*/(\rho_s V_s^*)\). El período fundamental de la columna es \(T_1 = 4H/V_s\) y el pico para \(\xi\) pequeño es \(|H|_{max} \approx 2/(\pi\xi)\) (\(\xi = 0.05 \Rightarrow 12.7\)).

**El límite \(\alpha \to \infty\) de esta expresión no es la solución de base rígida** (con base rígida no hay onda transmitida ni amortiguamiento por radiación): son dos problemas distintos y el programa debe elegir explícitamente uno.

Método lineal equivalente: se itera el módulo y el amortiguamiento compatibles con la deformación, con deformación efectiva \(\gamma_{eff} = R_\gamma \gamma_{max}\) y \(R_\gamma \approx 0.65\) (convención de Idriss & Sun, adoptada por SHAKE; \(\gamma\) en deformación angular adimensional, \(\xi\) en fracción del crítico). Curva constitutiva de referencia, con \(\gamma_r\) la deformación donde \(G/G_{max} = 0.5\):

$$\frac{G}{G_{max}} = \frac{1}{1+\gamma/\gamma_r}, \qquad \xi = \xi_{max}\left(1 - \frac{G}{G_{max}}\right)$$

Factores de amplificación de código: \(S_{MS} = F_a S_S\) y \(S_{M1} = F_v S_1\), todos adimensionales en g; \(F_a\) depende de la clase de sitio y de \(S_S\), \(F_v\) de la clase y de \(S_1\), y ambos decrecen al crecer la sacudida (no linealidad del suelo). Bibliotecas de curvas \(G/G_{max}\): Seed & Idriss, Vucetic & Dobry (por índice de plasticidad), Darendeli (2001), Menq (2003), cada una con su cita.

> ⚠️ VERIFICAR: las tablas de factores de sitio no se reproducen aquí. En ASCE 7-16 son Tables 11.4-1 y 11.4-2; NSR-10 usa A.2.4-1 y A.2.4-2; cada código define su condición de referencia (roca a 760 m/s, roca genérica, suelo tipo S1…). Se comprueban en el documento oficial y el programa las lee de `data/seismic/<codigo>-site-factors.json` con `source` y `verified_on`. ASCE 7-22 abandona \(F_a\) y \(F_v\) y publica valores ya modificados por sitio en una malla multi-periodo: en ese caso los factores tabulados **no se aplican**.

### 6. Plantillas de espectro de diseño
Toda plantilla se describe como datos, no como código: identificador, cita, parámetros, ramas con rango de período y expresión, y tipo de cola.

| Plantilla | Parámetros | Ramas | Cola | Fuente |
|---|---|---|---|---|
| Dos puntos (tipo NEHRP) | \(S_{DS}, S_{D1}, T_L\) | 4 | \(T_L/T^2\) | ASCE 7-16 §11.4.5 |
| Multi-periodo | malla de períodos + \(2/3\) | \(n\) | según malla | ASCE 7-22 §11.4.5 |
| Meseta + hipérbola | \(S_{DS}, S_{D1}\) | 3 | \(1/T\) | forma clásica |
| Meseta + hipérbola + desplazamiento | \(+\,T_L\) | 4 | \(T_L/T^2\) | ASCE 7-16, NSR-10 |
| Multi-rama con meseta | \(a_g S, T_B, T_C, T_D, \eta\) | 4 | \(T_C T_D/T^2\) | EN 1998-1 §3.2.2.2 |
| Turca | \(S_{DS}, S_{D1}, T_A, T_B\) | 4 | \(T_L/T^2\), \(T_L = 6\) s | TBDY 2018 Md. 2.3 |

Forma canónica de cuatro ramas, con \(T_0 = 0.2\,S_{D1}/S_{DS}\), \(T_s = S_{D1}/S_{DS}\), \(T\) en s y \(S_a\) en g:

$$S_a(T) = S_{DS}(0.4 + 0.6\,T/T_0)\ \ (T < T_0); \quad S_{DS}\ \ (T_0 \le T \le T_s); \quad S_{D1}/T\ \ (T_s < T \le T_L); \quad S_{D1}T_L/T^2\ \ (T > T_L)$$

La rama \(T > T_L\) es una asíntota de desplazamiento constante, no la prolongación de la hipérbola: usar \(S_{D1}/T\) más allá de \(T_L\) sobreestima la demanda de período largo.

### 7. Cuándo se exige un estudio de sitio específico
Disparadores habituales: clase de sitio F; suelos blandos profundos o arcillas sensitivas de espesor considerable; potencial de licuación, colapso o asentamiento dinámico; proximidad a una falla activa o régimen near-fault; estructuras de período largo, muy altas o de categoría de riesgo alta; y cualquier caso que el código local enumere.

> ⚠️ VERIFICAR: la lista exacta de disparadores y su umbralización numérica (ASCE 7-22 §11.4.7 y §11.4.8; equivalentes en NSR-10 Título A y en los demás códigos nacionales). Se comprueba en el estándar impreso. Hasta entonces el programa lee los disparadores de `data/seismic/site_specific_triggers.json`; ante un disparador activo **detiene el flujo** y emite el requerimiento en lugar de continuar con factores tabulados.

## Procedimiento

1. Fijar el nivel de peligro (\(p\), \(t\)) y calcular \(T_R\) con la convención declarada.
2. Obtener el peligro del sitio de un servicio o mapa nacional; guardar respuesta cruda, componente, fecha y versión del modelo.
3. Construir el perfil estratificado (espesores, \(V_s\), \(\rho\), profundidad de basamento) y verificar la cobertura de los 30 m superiores.
4. Calcular \(V_{s30}\) por tiempo de recorrido, clasificar el sitio y, si los criterios discrepan, tomar el más desfavorable.
5. Evaluar los disparadores de estudio específico; si hay alguno, detener y emitir el requerimiento.
6. Elegir la vía de amplificación (factores de código, función de transferencia, lineal equivalente o no lineal en `services/`) y registrarla.
7. Construir el espectro con la plantilla declarada y graficarlo contra el peligro del sitio para detectar inconsistencias (meseta por encima de la PGA, discontinuidades).
8. Comparar con el espectro normativo aplicable y reportar la diferencia, sin sustituirla en silencio.
9. Emitir envolvente, trazabilidad y advertencias; marcar el resultado como no verificado cuando falte el estudio específico exigido.

## Implementación en la plataforma

```python
# core/seismic/hazard.py                    (core puro: sin Qt, sin openseespy)
def probability_of_exceedance(tr_years, exposure_years, model="poisson") -> float: ...
def return_period(p_exceed, exposure_years, model="poisson") -> float: ...

# core/seismic/site_classification.py
class SoilLayer(NamedTuple):
    thickness: float; vs: float; density: float          # m, m/s, kg/m3
    n60: float | None = None; su: float | None = None    # su en Pa
def vs30(profile: Sequence[SoilLayer]) -> float: ...      # por tiempo de recorrido
def vs_from_n60(n60, correlation, data) -> float: ...
def classify_site(*, vs30=None, n60=None, su=None, data) -> SiteClass: ...
def requires_site_specific(site_class, ss, s1, t_fund, data) -> SiteSpecificVerdict: ...

# core/seismic/site_response.py
def transfer_function(freqs, profile, damping, base="rigid") -> np.ndarray: ...
def equivalent_linear(profile, motion, curves, tol=0.01, max_iter=15) -> SiteResponseResult: ...

# core/seismic/spectrum_templates.py
def design_spectrum(template_id, params, periods, registry) -> Spectrum: ...
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):

- `core/` no importa Qt ni OpenSeesPy; todo lo anterior es numpy puro.
- La **red** vive en `services/hazard_web.py` (sin Qt): consulta el servicio, escribe `data/seismic/sites/<id>.json` versionado y devuelve la ruta; `core/` sólo lee el archivo.
- El **solver** sólo se toca desde `services/site_response_runner.py`: el análisis no lineal 1D (PressureIndependMultiYield, PM4Sand, PDMY) se ejecuta ahí y devuelve un `SiteResponseResult` plano al núcleo.
- Los coeficientes de código (clases de sitio, \(F_a\), \(F_v\), cortes de plantilla) viven en `data/seismic/*.json` con `source` y `verified_on`; el motor no incrusta tablas.
- Errores que deben lanzarse, no devolverse como \(0\): `MissingSiteData`, `InsufficientProfile`, `SiteSpecificRequired`, `UnsupportedTemplate`, `NonConvergentEquivalentLinear`.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(p = 1-e^{-t/T_R}\) (Poisson) | práctica PSHA; ASCE 7-22 cap. 11 | sí (forma matemática) |
| \(S_a^{dis} = \tfrac{2}{3} S_a^{MCEr}\); \(V_{s30}\) por tiempo de recorrido | ASCE 7-22 §11.4.5 y Table 20.3-1 | sí |
| Cortes de clase de sitio A–F | ASCE 7-22 Table 20.3-1 | no — `VERIFICAR` |
| \(F_a\)(clase, \(S_S\)), \(F_v\)(clase, \(S_1\)) | ASCE 7-16 Tables 11.4-1/11.4-2; NSR-10 A.2.4 | no — `VERIFICAR` |
| Disparadores de estudio específico | ASCE 7-22 §11.4.7 y §11.4.8 | no — `VERIFICAR` |
| \(EPA\), \(EPV\) (divisor 2.5); \(R_\gamma \approx 0.65\) | ATC-3-06 / NEHRP; Idriss & Sun (1992) | sí (definiciones y literatura) |
| Coeficientes \(N_{60} \to V_s\) | Imai & Tonouchi (1982) y otros | no — `VERIFICAR` |
| Forma del espectro turco, \(T_L = 6\) s | TBDY 2018 Md. 2.3 | sí (`core/target_spectrum.py`) |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| \(T_R\), Poisson | \(p=0.10\), \(t=50\) a | 474.561 a | 1e-3 rel | cálculo cerrado |
| \(T_R\), binomial | \(p=0.10\), \(t=50\) a | 475.126 a | 1e-3 rel | cálculo cerrado |
| \(V_{s30}\) | 5 m @ 150, 10 m @ 250, 15 m @ 400 m/s | 270.68 m/s | 1e-6 rel | promedio por tiempo |
| Clase de sitio | \(V_{s30}=270.68\) m/s | D | exacta | ASCE 7-22 Table 20.3-1 |
| Perfil somero | 10 m @ 200 m/s sobre roca 900 m/s | `InsufficientProfile` | exacta | regla de la skill |
| \(T_1\) de la columna | \(H=30\) m, \(V_s=250\) m/s | 0.48 s | 1e-9 rel | \(T_1 = 4H/V_s\) |
| \(|H|\) en resonancia | \(\xi=0.05\), \(\omega H/V_s = \pi/2\) | 12.7193 | 1e-3 rel | forma cerrada |
| Aproximación de pico | \(\xi=0.05\) | \(2/(\pi\xi) = 12.732\) | 1 % rel | aproximación |
| \(T_0\), \(T_s\) | \(S_{DS}=1.0\), \(S_{D1}=0.6\) g | 0.12 s, 0.6 s | 1e-9 rel | ASCE 7-16 §11.4.5 |
| Cola de desplazamiento | \(T=16\) s, \(T_L=8\) s, \(S_{D1}=0.6\) g | 0.01875 g | 1e-9 rel | forma cerrada |
| Lineal equivalente | \(H=30\) m, \(V_s=250\) m/s, \(\xi_0=0.05\) | convergencia en ≤ 15 iter. | 1e-3 rel | SHAKE91 / DeepSoil |

Contraste obligatorio: una columna 1D del repositorio contra un programa de referencia (SHAKE91, DeepSoil o Strata) con el mismo perfil, la misma curva \(G/G_{max}\) y el mismo registro, exigiendo acuerdo de la función de transferencia dentro del 5 % en 0.1–10 Hz; y el espectro generado contra la herramienta oficial de peligro para un sitio rocoso y uno blando.

## Errores frecuentes y trampas

1. **Promediar \(V_s\) aritméticamente** en vez de por tiempo de recorrido: en perfiles contrastantes el error supera el 20 % y cambia la clase.
2. **Extrapolar \(V_{s30}\)** con el basamento a 12 m: se promedia hasta 30 m con la \(V_s\) del basamento, se inventa un suelo inexistente y se endurece la clase.
3. **Doble amplificación por sitio**: aplicar \(F_a\)/\(F_v\) a un espectro que ya viene modificado (ASCE 7-22 o sitio específico).
4. **Confundir condiciones de referencia**: \(F_a\) de NEHRP se refiere a roca de 760 m/s; el "suelo tipo S1" o la "roca" de otro código no son lo mismo.
5. **Usar \(N\) sin corregir por energía**: las correlaciones piden \(N_{60}\) y el golpeo de campo sobreestima \(V_s\); en gravas o rellenos antrópicos la correlación no es válida.
6. **Tratar la UHS como un escenario**: igualar registros a la UHS produce movimientos irreales; para eso se usa el espectro condicionado (CMS) en el período de interés.
7. **Apilar u omitir el \(2/3\)**: multiplicar un espectro de sitio específico ya escalado, o comparar derivas de diseño contra un espectro en nivel MCEr.
8. **Mezclar la PGA del mapa con \(S_a(0)\)** del espectro tabulado: la rama ascendente hasta \(T_0\) no pasa por la PGA en \(T=0\).
9. **Tratar \(T_L\) como constante** (6 s u 8 s): se lee del peligro del sitio y controla la cola de desplazamiento.
10. **Base rígida donde hay base elástica**: omitir el amortiguamiento por radiación infla la amplificación resonante de forma arbitraria.
11. **Lineal equivalente sin criterio de convergencia** o iterando sobre \(\gamma_{max}\) en vez de \(\gamma_{eff} = 0.65\gamma_{max}\): el resultado depende del número de iteraciones y no se reproduce; y **reutilizar curvas \(G/G_{max}\) de otro material** sin verificar índice de plasticidad ni rango de deformación.
12. **Unidades**: \(V_s\) en ft/s (los mapas estadounidenses las publican así), \(S_a\) en g mezclada con \(a_g\) en m/s², densidad en kg/m³ contra peso unitario en kN/m³ al calcular \(\alpha\).
13. **No declarar la componente** (media geométrica / `RotD50` / dirección máxima) al comparar el espectro calculado con el publicado.

## Interfaz de salida

El programa reporta, por sitio y nivel de peligro: el nivel de peligro con \(p\), \(t\), \(T_R\) y la convención; el origen del peligro (servicio o mapa, versión del modelo, componente, fecha de consulta y cita del archivo de datos); el perfil estratificado usado, \(V_{s30}\) con su método, profundidad de basamento y clase de sitio con el criterio que la fijó; el veredicto de estudio específico con la cita del disparador; la vía de amplificación y sus parámetros; el espectro en tabla \(T\)–\(S_a\) (periodos en s, \(S_a\) en g) más la representación interna en m/s² con la conversión declarada; la comparación contra el espectro normativo aplicable período a período; y las advertencias activas con trazabilidad completa (norma, edición, artículo, archivo de datos y `verified_on`).

## Referencias

1. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures*. Capítulos 11 y 20, 21, 22.
2. ASCE/SEI 7-16, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures*. §11.4, Tables 11.4-1 y 11.4-2.
3. NEHRP, *Recommended Seismic Provisions for New Buildings and Other Structures* (FEMA P-2082), edición vigente — comentarios de la clasificación de sitio.
4. ATC-3-06, *Tentative Provisions for the Development of Seismic Regulations for Buildings* — definición de \(EPA\) y \(EPV\).
5. S. L. Kramer, *Geotechnical Earthquake Engineering*, Prentice Hall, 1996 — funciones de transferencia y amplificación 1D.
6. I. M. Idriss y J. I. Sun, *User's Manual for SHAKE91*, 1992 — convención \(\gamma_{eff} = 0.65\gamma_{max}\).
7. M. B. Darendeli, *Development of a new family of normalized modulus reduction and material damping curves*, tesis doctoral, Universidad de Texas, 2001.
8. Y. M. A. Hashash et al., *DEEPSOIL* — manual del programa, versión vigente.
9. EN 1998-1, *Eurocode 8: Design of structures for earthquake resistance*, §3.2.2.2 y Table 3.2.
10. TBDY 2018, *Turkish Building Earthquake Code*, Md. 2.3 y Tablo 2.1/2.2.
11. NSR-10, *Reglamento Colombiano de Construcción Sismo Resistente*, Título A.
12. USGS, *Seismic Hazard Maps and Site-Specific Data* — modelo NSHM y servicios web de diseño.

## Registro de verificación

- **Verificado (2026-02-14)**: las conversiones \(p \leftrightarrow T_R\) y la diferencia entre Poisson y binomial (comprobadas numéricamente); el promedio de \(V_{s30}\) por tiempo de recorrido; las funciones de transferencia de capa sobre base rígida y elástica y su pico \(2/(\pi\xi)\); la forma de cuatro ramas y la cola de desplazamiento; \(S_a^{dis} = \tfrac{2}{3}S_a^{MCEr}\); la definición de \(EPA\)/\(EPV\); la existencia y ubicación de las tablas de factores de sitio de ASCE 7-16 y NSR-10.
- **Pendiente**: transcripción de ASCE 7-22 Table 20.3-1 y de las tablas de \(F_a\)/\(F_v\); disparadores exactos de estudio específico (ASCE 7-22 §11.4.7/§11.4.8); definición de componente de los mapas; coeficientes de las correlaciones \(N_{60}\to V_s\) contra los artículos originales; endpoint y versión del servicio de peligro.
- **Responsable de cerrar**: responsable de geotecnia sísmica del proyecto, con copia licenciada de ASCE 7-22 y acceso a los artículos originales.
