---
name: peru-e030
description: >-
  Implementa y verifica el análisis sísmico peruano de la NTE E.030 del RNE: factor de zona Z, factor de uso U, parámetros de sitio S, Tp y Tl, factor de amplificación sísmica C, coeficientes R0 y R = R0·Ia·Ip, irregularidades en altura y en planta, peso sísmico P, cortante basal V = ZUCS/R, distribución de fuerzas en altura, excentricidad accidental, análisis dinámico modal espectral con corrección por cortante mínimo, límites de distorsión y desplazamientos laterales, con remisión a E.060 (concreto armado) y E.090 (estructuras metálicas). Úsala cuando el proyecto declara jurisdicción Perú, cuando una memoria cita «E.030», «RM 355-2018-VIVIENDA», «Zona 4», «perfil S3», «R0» o «E.060», o cuando se audita un módulo sísmico peruano ya escrito.
metadata:
  track: codes
  jurisdiction: PER
  edition: "E.030 (con E.060 y E.090)"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Perú — NTE E.030, Diseño Sismorresistente (con E.060 y E.090)

## Cuándo usar esta skill
- El proyecto declara `code = E.030` o ubicación en Perú y hay que resolver \(Z\) del mapa o del listado de provincias y distritos del Anexo II.
- Hay que construir el espectro inelástico \(S_a = (ZUCS/R)\,g\), el cortante basal estático, o corregir el cortante del primer entrepiso del análisis dinámico contra el estático.
- Hay que clasificar la estructura como regular o irregular y aplicar \(I_a\) e \(I_p\), que reducen \(R\), o verificar distorsiones contra la Tabla N° 11.
- Se audita un módulo peruano existente: los defectos típicos son usar \(R\) en vez de \(0.75R\)/\(0.85R\) en desplazamientos, olvidar \(R=R_0I_aI_p\) y escalar los desplazamientos junto con las fuerzas.

**No usar** para diseñar elementos: la capacidad es de E.060 (concreto) y E.090 (acero). Para combinaciones de carga, peligro sísmico y resolución de código por ubicación: `seismic/load-combinations-and-limit-states`, `seismic/seismic-hazard-and-site-response`, `codes/code-crosswalk-and-extension`.

## Alcance y límites
Cubre la demanda sísmica de la E.030 (Capítulos I–VII y Anexos I y II): peligro, caracterización del edificio, análisis estático y dinámico modal espectral, requisitos de rigidez y elementos no estructurales. **No cubre** el diseño ni el detallado de elementos (→ E.060, E.090), la mecánica de suelos (→ E.050), el aislamiento sísmico (→ E.031), ni estructuras cuyo comportamiento difiere del de edificaciones (puentes, reservorios, muelles), para las que el Art. 1.2 exige amplificar \(Z\) y \(S\) con práctica internacional.

Supuestos: análisis lineal elástico con solicitaciones sísmicas reducidas, secciones brutas sin fisurar para concreto armado y albañilería (Art. 25.2), base empotrada salvo justificación, y diafragmas rígidos o flexibles declarados. No se consideran simultáneamente sismo y viento (Art. 8.2).

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Departamento/provincia/distrito, o \(Z\) explícito | sí | bloquear: no se inventa el peligro |
| Perfil S0–S4 del EMS (30 m bajo el nivel de cimentación) | sí | error explícito; nunca un perfil por defecto |
| Categoría (A1, A2, B, C, D) y \(U\) | sí | bloquear |
| Sistema estructural por dirección (Tabla N° 7) | sí | bloquear |
| Irregularidades en altura y en planta | sí | evaluar Tablas N° 8 y N° 9; piso blando y torsión se confirman con el análisis |
| Pesos por nivel, alturas de entrepiso y \(h_n\) | sí | bloquear |
| Carga permanente y viva por nivel, uso de azotea | sí | bloquear (definen el peso sísmico) |
| Método de análisis y dirección de análisis | sí | derivar de Tabla N° 10 y Art. 28.1.2 |

Unidades internas SI coherentes: m, N, kg, s, Pa; \(g = 9.80665\ \text{m/s}^2\). \(Z\), \(U\), \(C\), \(S\) y \(R\) son adimensionales. \(S_a\) se expresa **en g** porque así lo publica la norma (Art. 29.2.1); para obtener fuerza se multiplica por \(g\) y por la masa.

## Fundamento y formulación

### 1. Peligro y sitio
\(Z\) es la aceleración máxima horizontal en suelo rígido con 10 % de probabilidad de excedencia en 50 años, como fracción de \(g\) (Art. 10.2). El factor de suelo y los períodos de plataforma dependen de \(Z\) y del perfil del EMS (Art. 13):
$$S = S(Z,\text{perfil}),\qquad T_P = T_P(\text{perfil}),\qquad T_L = T_L(\text{perfil})$$

### 2. Factor de amplificación sísmica
$$C = 2.5 \;\;(T < T_P);\quad C = 2.5\,\frac{T_P}{T} \;\;(T_P < T < T_L);\quad C = 2.5\,\frac{T_P\,T_L}{T^2} \;\;(T > T_L)$$
\(T\) período fundamental en la dirección de análisis [s]. Los tres tramos son continuos en \(T_P\) y \(T_L\) (Art. 14). \(C\) es la amplificación de la aceleración estructural respecto de la del suelo.

### 3. Reducción por ductilidad e irregularidad
$$R = R_0\,I_a\,I_p$$
\(R_0\) depende solo del sistema estructural y del material (Tabla N° 7). \(I_a\) es el menor valor de la Tabla N° 8 entre las irregularidades en altura e \(I_p\) el menor de la Tabla N° 9 entre las de planta, tomando además el menor de las dos direcciones de análisis (Art. 20, 22). Si una dirección combina varios sistemas se toma el menor \(R_0\) (Art. 18.2). Estos coeficientes no se aplican a estructuras tipo péndulo invertido.

### 4. Peso sísmico
\(P\) suma la carga permanente total más un porcentaje de la carga viva (Art. 26): 50 % en categorías A y B, 25 % en categoría C, 25 % en azoteas y techos, 80 % del peso almacenable en depósitos, 100 % del contenido en tanques y silos.

### 5. Cortante basal y distribución en altura
$$V = \frac{Z\,U\,C\,S}{R}\,P \quad [\text{N}], \qquad \frac{C}{R} \ge 0.11 \qquad\qquad F_i = \alpha_i V,\qquad \alpha_i = \frac{P_i\,h_i^{k}}{\sum_{j=1}^{n} P_j\,h_j^{k}}$$
\(P_i\) peso del nivel \(i\) [N]; \(h_i\) altura del nivel \(i\) sobre la base [m]; \(n\) número de pisos (Art. 28.2, 28.3). El exponente es \(k=1.0\) para \(T \le 0.5\ \text{s}\) y \(k = 0.75 + 0.5\,T \le 2.0\) para \(T > 0.5\ \text{s}\) (Art. 28.3.2). Período aproximado \(T = h_n/C_T\) (Art. 28.4.1) con \(h_n\) en m y \(C_T\): 35 para pórticos de concreto sin muros de corte y pórticos dúctiles de acero sin arriostramiento; 45 para pórticos de concreto con muros en cajas de ascensores y escaleras y pórticos de acero arriostrados; 60 para albañilería y para todo edificio de concreto dual, de muros estructurales o de muros de ductilidad limitada. Alternativamente la fórmula de Rayleigh del Art. 28.4.2, multiplicada por \(0.85\) cuando el modelo omite la rigidez de los elementos no estructurales (Art. 28.4.3).

### 6. Excentricidad accidental
Con diafragmas rígidos se aplica en cada nivel un momento torsor \(M_{ti} = \pm F_i\,e_i\) con \(e_i = 0.05\,D_\perp\), donde \(D_\perp\) es la dimensión del edificio perpendicular a la dirección de análisis [m]. Se usan las excentricidades con el mismo signo en todos los niveles y solo los incrementos de fuerzas, no las disminuciones (Art. 28.5, 29.5).

### 7. Análisis dinámico modal espectral
$$S_a(T) = \frac{Z\,U\,C(T)\,S}{R}\,g \quad [\text{m/s}^2],\qquad \text{amortiguamiento } 5\,\%,\qquad \rho_{ij} = \frac{8\beta^2(1+\lambda)\lambda^{3/2}}{(1-\lambda^2)^2+4\beta^2\lambda(1+\lambda)^2},\quad \lambda = \frac{\omega_j}{\omega_i}$$
Se incluyen los modos cuya suma de masas efectivas alcance al menos el 90 % de la masa total, con un mínimo de los tres primeros modos predominantes por dirección (Art. 29.1.2). La combinación es cuadrática completa con \(\beta = 0.05\) (Art. 29.3.2); alternativamente el Art. 29.3.4 admite \(r = 0.25\sum_i|r_i| + 0.75\sqrt{\sum_i r_i^2}\). Corrección por cortante mínimo (Art. 29.4): el cortante del primer entrepiso no baja del 80 % del estático si la estructura es regular, ni del 90 % si es irregular; al escalar, **todos los resultados de fuerzas se escalan proporcionalmente y los desplazamientos no** (Art. 29.4.2).

### 8. Desplazamientos y distorsiones
Los desplazamientos laterales son \(0.75R\) veces los del análisis lineal elástico en estructuras regulares y \(0.85R\) veces en irregulares (Art. 31.1). Para calcularlos no se aplican el mínimo \(C/R \ge 0.11\) ni el escalamiento del Art. 29.4 (Art. 31.2). La distorsión de entrepiso \(\Delta_i/h_{ei}\) no excede la Tabla N° 11 (Art. 32). Separación entre edificios (Art. 33.2): no menor que \(2/3\) de la suma de los desplazamientos máximos de los edificios adyacentes, ni menor que \(s = 0.006\,h \ge 0.03\ \text{m}\), con \(h\) la altura desde el terreno natural hasta el nivel considerado.

### 9. Fuerzas verticales, redundancia y no estructurales
- Fuerza sísmica vertical estática: \(2/3\,Z\,U\,S\) como fracción del peso (Art. 28.6.1); equivale a \(2/3\) de la fuerza horizontal (Art. 40.1).
- Espectro vertical: \(2/3\) del horizontal, salvo \(T < 0.2\,T_P\), donde \(C = 1 + 7.5\,(T/T_P)\) (Art. 29.2.2).
- Redundancia (Art. 34): si un solo elemento toma \(\ge 30\,\%\) del cortante de un entrepiso, se diseña para \(1.25\) veces esa fuerza.
- No estructurales (Art. 38–43): \(F = (F_i/P_i)\,C_1\,P_e\), con \(C_1\) de la Tabla N° 12, mínimo \(F \ge 0.5\,Z\,U\,S\,P_e\) (Art. 39); por esfuerzos admisibles se multiplica por \(0.8\) (Art. 43).

## Procedimiento
1. Resolver \(Z\) del Anexo II o de la microzonificación aplicable (Art. 10, 11).
2. Clasificar el perfil S0–S4 con \(\bar V_s\), \(\bar N_{60}\) o \(\bar S_u\) de los 30 m bajo el nivel de cimentación; si los criterios discrepan, tomar el perfil más desfavorable (Art. 12).
3. Leer \(S\), \(T_P\) y \(T_L\) (Tablas N° 3 y N° 4), fijar categoría y \(U\) (Tabla N° 5) y comprobar que el sistema estructural esté permitido para esa categoría y zona (Tabla N° 6).
4. Leer \(R_0\) por dirección (Tabla N° 7); si hay varios sistemas, el menor.
5. Evaluar irregularidades, obtener \(I_a\) e \(I_p\) como los menores valores de las Tablas N° 8 y N° 9 en las dos direcciones, y verificar la Tabla N° 10 según categoría y zona.
6. Calcular \(R = R_0I_aI_p\) (Art. 22) y el peso sísmico \(P\) (Art. 26).
7. Elegir el procedimiento (Art. 27), respetando el Art. 28.1.2: el estático solo para estructuras regulares de hasta 30 m, para cualquier estructura en Zona 1, y para muros portantes de concreto o albañilería de hasta 15 m aunque sean irregulares.
8. Estimar \(T\) por \(h_n/C_T\) o Rayleigh y construir \(C(T)\); en el dinámico, resolver autovalores y tomar \(T\) del modo fundamental.
9. Estático: \(V = ZUCS/R\cdot P\) con \(C/R \ge 0.11\), distribuir \(F_i\) con \(k(T)\) y aplicar \(M_{ti} = \pm F_i e_i\).
10. Dinámico: espectro \(S_a(T)\), combinación CQC, excentricidad accidental, y escalar las fuerzas al 80 %/90 % del cortante estático del primer entrepiso sin tocar los desplazamientos.
11. Amplificar desplazamientos por \(0.75R\) o \(0.85R\) y verificar \(\Delta_i/h_{ei}\) contra la Tabla N° 11.
12. Calcular \(s\), las fuerzas verticales y las de elementos no estructurales.
13. Reverificar irregularidades con los resultados (piso blando, torsión), actualizar \(R\) si cambiaron y emitir el informe con la traza normativa.

## Implementación en la plataforma

```python
# src/opensees_studio/core/codes/peru_e030.py   (core puro: sin Qt, sin OpenSeesPy)
def factor_z(zona: int, *, datos: CodeData) -> float: ...
def parametros_sitio(zona: int, perfil: str, *, datos: CodeData) -> tuple[float, float, float]:
    """(S, TP, TL) de las Tablas N° 3 y N° 4; lanza MissingSiteProfileError."""
def factor_amplificacion(t: float, tp: float, tl: float) -> float: ...  # C(T), Art. 14
def factor_uso(categoria: str, zona: int, *, datos: CodeData) -> float: ...
def coeficiente_basico(sistema_id: str, *, datos: CodeData) -> float:
    """R0 de la Tabla N° 7; UnsupportedSystemError si el id no existe."""
def coeficiente_reduccion(r0: float, ia: float, ip: float) -> float: ...  # R = R0*Ia*Ip
def peso_sismico(niveles: Sequence[NivelCarga], categoria: str) -> float: ...   # N
def cortante_basal(z, u, c, s, r, p) -> float: ...                            # N
def distribucion_altura(pesos, alturas, v, t) -> list[float]: ...              # F_i, N
def excentricidad_accidental(d_perp: float) -> float: ...                      # m
def espectro_inelastico(z, u, s, r, tp, tl) -> Spectrum: ...                   # en g
def factor_escala_cortante(v_din: float, v_est: float, regular: bool) -> float:
    """max(1.0, 0.80*v_est/v_din) o 0.90; nunca se aplica a desplazamientos."""
def amplificar_desplazamientos(delta_elastico, r: float, regular: bool) -> float:
    """0.75*R o 0.85*R, Art. 31.1."""
def limite_distorsion(material: str, *, datos: CodeData) -> float: ...  # Tabla N° 11
def separacion_sismica(h: float) -> float: ...                         # m, Art. 33.2
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services`):
- El módulo vive en `core/codes/` y **no importa Qt ni OpenSeesPy**; debe importarse desde un notebook o la CLI sin GUI.
- Todo coeficiente sale de `data/codes/peru-e030-<edicion>.json` con `value`, `unit`, `source` y `verified_on` por entrada; ninguno se incrusta en el código. Cambiar de edición de norma = cambiar el archivo de datos, no el motor.
- El solver se toca solo desde `services/`: `services/spectrum.py` convierte el `Spectrum` del núcleo en el patrón de cargas de OpenSeesPy y `services/opensees_runner.py` ejecuta. El núcleo devuelve curvas y vectores, no la respuesta del solver.
- La combinación modal y el CQC se reutilizan de `core/modal_combination.py`; no se duplican.
- Errores tipados: `MissingSiteProfileError`, `ForbiddenIrregularityError` (Tabla N° 10), `UnsupportedSystemError` (Tabla N° 6), `StaticMethodNotAllowedError` (Art. 28.1.2).

## Datos normativos
Factor de zona, adimensional y fracción de \(g\) (E.030, Art. 10.2 y Tabla N° 1): Zona 4 → \(Z=0.45\); Zona 3 → 0.35; Zona 2 → 0.25; Zona 1 → 0.10. Factor de suelo \(S\) y períodos \(T_P\), \(T_L\) en s (E.030, Tablas N° 3 y N° 4):

| Zona | S0 | S1 | S2 | S3 |
|---|---|---|---|---|
| \(S\) Z4 | 0.80 | 1.00 | 1.05 | 1.10 |
| \(S\) Z3 | 0.80 | 1.00 | 1.15 | 1.20 |
| \(S\) Z2 | 0.80 | 1.00 | 1.20 | 1.40 |
| \(S\) Z1 | 0.80 | 1.00 | 1.60 | 2.00 |
| \(T_P\) | 0.3 | 0.4 | 0.6 | 1.0 |
| \(T_L\) | 3.0 | 2.5 | 2.0 | 1.6 |

Factor de uso \(U\) (E.030, Art. 15 y Tabla N° 5): A1 y A2 → 1.5; B → 1.3; C → 1.0; D → sin exigencia de análisis sísmico. Las edificaciones A1 nuevas en Zonas 4 y 3 llevan aislamiento en la base.

Coeficiente básico \(R_0\) (E.030, Art. 18 y Tabla N° 7): acero, pórticos especiales resistentes a momentos (SMF) 8, intermedios (IMF) 5, ordinarios (OMF) 4, arriostrados concéntricos especiales (SCBF) 7, ordinarios (OCBF) 4, excéntricamente arriostrados (EBF) 8; concreto armado, pórticos 8, dual 7, muros estructurales 6, muros de ductilidad limitada 4 (máximo ocho pisos); albañilería armada o confinada 3; madera 7 solo por esfuerzos admisibles.

Irregularidades en altura \(I_a\) (E.030, Tabla N° 8): piso blando 0.75; piso débil 0.75; rigidez extrema 0.50; resistencia extrema 0.50; masa o peso 0.90; geometría vertical 0.90; discontinuidad de sistemas resistentes 0.80; discontinuidad extrema 0.60. En planta \(I_p\) (E.030, Tabla N° 9): torsional 0.75; torsional extrema 0.60; esquinas entrantes 0.90; discontinuidad del diafragma 0.85; sistemas no paralelos 0.90. La irregularidad torsional se mide con \(\Delta_{max}/\Delta_{prom} > 1.3\) y la extrema con \(> 1.5\), y solo se aplican si el desplazamiento relativo supera el 50 % del admisible de la Tabla N° 11.

Límites de distorsión \(\Delta_i/h_{ei}\) (E.030, Art. 32 y Tabla N° 11): concreto armado 0.007; acero 0.010; albañilería 0.005; madera 0.010; concreto armado con muros de ductilidad limitada 0.005. Para uso industrial los fija el proyectista, sin exceder el doble de esos valores.

> ⚠️ VERIFICAR: no se pudo confirmar qué edición de la E.030 está vigente a la fecha de esta revisión. Circula una revisión 2025 firmada digitalmente por el MVCS el 30-10-2025 (84 pp.) que **conserva \(Z\)** pero cambia la tabla de \(S\) (añade el perfil S4 y modifica Z4/S2, Z4/S3, Z2/S2, Z1/S2 y Z1/S3), cambia \(T_P\) y \(T_L\) (S2 y S3 con \(T_P\) interpolado entre 0.4–0.6 y 0.6–0.9; \(T_L\) = 3.0/3.0/3.0/2.5/2.0), introduce un tramo explícito \(C = 1 + 7.5\,(T/T_P)\) para \(T < 0.2T_P\) y baja a 0.004 la distorsión de muros de ductilidad limitada. Se comprueba en la publicación oficial de El Peruano y en la resolución ministerial aprobatoria del MVCS. Hasta entonces el programa **lee todos los valores de este apartado de un archivo de datos versionado** con campos `edition` y `source`, y rechaza un proyecto cuya edición no figure en el archivo.

> ⚠️ VERIFICAR: el listado de provincias y distritos por zona (Anexo II) no se transcribe aquí. Se comprueba contra el Anexo II de la edición vigente y se carga como `data/codes/peru-e030-zonas.json` con `departamento`, `provincia`, `distrito`, `zona` y `source`. La Zona 1 solo se admite si el distrito figura en el listado; no se deduce de la latitud ni del departamento.

> ⚠️ VERIFICAR: las ediciones vigentes de E.060 y E.090 y sus combinaciones de carga (E.060 §9.2; E.090, capítulo de combinaciones). Se comprueban en los decretos supremos aprobatorios del RNE y se cargan en `data/codes/peru-e060-e090-combos.json`. El motor de E.030 no codifica factores de combinación, \(\phi\) ni coeficientes de reducción de resistencia.

## Verificación y casos de prueba

| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| \(C\) meseta | \(T_P=0.4\), \(T=0.20\ \text{s}\) | \(C=2.5\) | 1e-9 | E.030 Art. 14 |
| \(C\) hipérbola | \(T_P=0.4\), \(T=0.5714286\ \text{s}\) | \(C=1.75\) | 1e-9 | E.030 Art. 14 |
| \(C\) cola | \(T_P=0.4\), \(T_L=2.5\), \(T=3.0\ \text{s}\) | \(C=0.277778\) | 1e-9 | E.030 Art. 14 |
| \(k\) interpolado | \(T=0.5714286\ \text{s}>0.5\) | \(k=1.035714\) | 1e-9 | E.030 Art. 28.3.2 |
| \(T\) aproximado | \(h_n=20\ \text{m}\), pórticos de concreto sin muros | \(T=0.5714286\ \text{s}\) | 1e-9 | E.030 Art. 28.4.1 |
| \(V\) estático | \(Z=0.35\), \(U=1.0\), \(C=1.75\), \(S=1.00\), \(R=8\), \(P=1.0\times10^6\ \text{N}\) | \(V=76\,562.5\ \text{N}\) | 1e-6 rel | E.030 Art. 28.2 |
| Mínimo \(C/R\) | \(C=0.8\), \(R=8\) | se usa \(C/R=0.11\) | 1e-9 | E.030 Art. 28.2.2 |
| \(R\) irregular | \(R_0=8\), \(I_a=0.75\), \(I_p=0.75\) | \(R=4.5\) | 1e-9 | E.030 Art. 22 |
| Escala cortante, regular | \(V_{din}=60\ \text{kN}\), \(V_{est}=76.5625\ \text{kN}\) | factor \(=1.020833\) | 1e-6 rel | E.030 Art. 29.4 |
| Escala cortante, irregular | ídem, estructura irregular | factor \(=1.148438\) | 1e-6 rel | E.030 Art. 29.4 |
| Desplazamiento, regular | \(\delta_e=10\ \text{mm}\), \(R=4.5\) | \(\delta=33.75\ \text{mm}\) | 1e-9 | E.030 Art. 31.1 |
| Desplazamiento, irregular | \(\delta_e=10\ \text{mm}\), \(R=4.5\) | \(\delta=38.25\ \text{mm}\) | 1e-9 | E.030 Art. 31.1 |
| Distorsión admisible | concreto armado, \(h_{ei}=3.0\ \text{m}\) | \(\Delta_{adm}=21\ \text{mm}\) | 1e-9 | E.030 Tabla N° 11 |
| Excentricidad accidental | \(D_\perp=12\ \text{m}\) | \(e=0.6\ \text{m}\) | 1e-9 | E.030 Art. 28.5 |
| Separación sísmica | \(h=12\ \text{m}\) | \(s=0.072\ \text{m}\) | 1e-9 | E.030 Art. 33.2 |

Además: contrastar el \(V\) estático y el cortante dinámico corregido de un edificio de cinco pisos contra una hoja de cálculo independiente y contra los pasos 1–18 del Anexo I, con períodos al 0.5 % y fuerzas al 1 %. El caso «\(V\) estático» y el de escala de cortante comparten datos: \(V_{est}=76\,562.5\ \text{N}=76.5625\ \text{kN}\).

## Errores frecuentes y trampas
1. **Usar \(R\) en vez de \(0.75R\)/\(0.85R\)** para los desplazamientos: es el defecto más común al portar formulaciones de ASCE 7 o NSR-10 (Art. 31.1).
2. Escalar los desplazamientos junto con las fuerzas al corregir el cortante mínimo; el Art. 29.4.2 los excluye, y el Art. 31.2 excluye también el mínimo \(C/R\) del cálculo de derivas.
3. Tomar \(R=R_0\) olvidando \(I_aI_p\), o aplicar solo la irregularidad de la dirección analizada en vez del menor valor entre las dos direcciones (Art. 20.3).
4. Memorizar «las irregularidades de planta valen 0.90»: la discontinuidad del diafragma vale 0.85, un error de 0.05 en \(R\) que mueve el cortante ~5 %.
5. Usar \(0.05D_\perp\) como excentricidad única en lugar del momento torsor \(M_{ti}=F_ie_i\), o promediar signos entre niveles cuando el Art. 28.5 exige el mismo signo en todos los niveles.
6. Importar el tope \(T \le 1.4\,T_{aproximado}\) de otros códigos: el articulado de E.030 no lo contiene, y tampoco define un tope de \(C/R\) distinto de 0.11.
7. Usar \(S_a\) en g como fuerza sin multiplicar por \(g\) y por la masa; es la causa habitual de un cortante 9.81 veces fuera de rango.
8. Omitir el \(0.85\) del Art. 28.4.3 cuando el modelo no incluye la rigidez de los elementos no estructurales.
9. Aplicar el método estático fuera del Art. 28.1.2: más de 30 m de altura, estructura irregular fuera de la Zona 1, o muros portantes de más de 15 m.
10. Ignorar la Tabla N° 10: en Zonas 4, 3 y 2 no se permiten irregularidades extremas en categorías A1, A2 y B, y en categoría A no se permite ninguna irregularidad.
11. Usar el cortante de la **base** en lugar del cortante del **primer entrepiso** en el mínimo del Art. 29.4.1; coinciden solo si no hay cargas horizontales en el nivel 1.
12. Resolver la cita del Art. 29.4.1 por número de artículo: el texto oficial cita «el artículo 25», pero el Anexo I (Paso 13B) aclara que la referencia es el cortante estático del Art. 28.
13. Confundir el espectro de la E.030 con el MCER y aplicar un 2/3 adicional: la norma ya entrega el espectro inelástico reducido por \(R\).
14. Redondear \(C\), \(R\) o \(V\) antes de la comprobación final, y usar el mismo \(R\) para fuerzas y para desplazamientos.

## Interfaz de salida
Para cada dirección de análisis el programa reporta:
- Ubicación resuelta, zona, \(Z\), perfil de suelo y los tres criterios de clasificación (\(\bar V_s\), \(\bar N_{60}\), \(\bar S_u\)) con su origen.
- \(S\), \(T_P\), \(T_L\), categoría, \(U\), sistema estructural y \(R_0\), citando tabla y edición.
- Irregularidades detectadas con su \(I_a\) o \(I_p\) individual, el valor gobernante por dirección, \(I_aI_p\), \(R\) y el veredicto de la Tabla N° 10.
- \(P\), \(T\) aproximado y dinámico, \(C\), \(C/R\), \(V\), los \(F_i\), \(\alpha_i\) y \(k\).
- Para el análisis dinámico: número de modos, masa participante acumulada por dirección, \(V_{din}\), \(V_{est}\), el factor de escala aplicado y la constancia de que no se aplicó a desplazamientos.
- Desplazamientos amplificados, \(\Delta_i/h_{ei}\), altura de entrepiso, límite de la Tabla N° 11 y cumplimiento con margen; más \(e_i\), \(M_{ti}\), \(s\), la fuerza vertical y las de elementos no estructurales.
- Avisos: edición de datos usada, entradas con `verified: false` (resultado preliminar) y todo VERIFICAR abierto que afecte a un número mostrado.

## Referencias
1. Norma Técnica E.030 «Diseño Sismorresistente», RNE — texto modificado por la Resolución Ministerial N° 355-2018-VIVIENDA, publicada en El Peruano el 7 de diciembre de 2018 (resolución del 23 de octubre de 2018).
2. Decreto Supremo N° 002-2018-VIVIENDA — aprueba la Norma Técnica E.030.
3. Norma Técnica E.060 «Concreto Armado», RNE — Decreto Supremo N° 010-2009-VIVIENDA.
4. Norma Técnica E.090 «Estructuras Metálicas», RNE — edición vigente del RNE.
5. Norma Técnica E.050 «Suelos y Cimentaciones», RNE — estudios que alimentan el perfil S0–S4.
6. Norma Técnica E.031 «Aislamiento Sísmico», RNE — obligatoria para A1 en Zonas 4 y 3.
7. Norma Técnica E.080 «Diseño y Construcción con Tierra Reforzada», RNE — remitida por el Art. 18.3 para construcciones de tierra.
8. ASCE/SEI 7 vigente — referida por el Art. 23.1 para aislamiento y disipación; ASCE/SEI 41 para verificación de resistencia última (Art. 35).
9. Norma Técnica E.030, revisión 2025 circulante (MVCS, firmas digitales del 30-10-2025) — **no confirmada como publicada**; ver el VERIFICAR de Datos normativos.

## Registro de verificación
- **Verificado** contra el texto oficial publicado (El Peruano, 7-12-2018; RM 355-2018-VIVIENDA, 32 pp., leído artículo por artículo): Tabla N° 1 (\(Z\)); Tabla N° 3 (\(S\)); Tabla N° 4 (\(T_P\), \(T_L\)); Tabla N° 5 (\(U\)); Tabla N° 7 (\(R_0\)); Tabla N° 8 (\(I_a\)); Tabla N° 9 (\(I_p\)); Tabla N° 11 (distorsiones); los tres tramos de \(C\) (Art. 14); \(R=R_0I_aI_p\) (Art. 22); porcentajes de carga viva del peso sísmico (Art. 26); \(V\), \(C/R \ge 0.11\), \(\alpha_i\) y \(k\) (Art. 28.2–28.3); \(C_T\) = 35/45/60 y el 0.85 de Rayleigh (Art. 28.4); \(e_i=0.05D_\perp\) (Art. 28.5); \(2/3\,ZUS\) vertical (Art. 28.6.1); masa participante del 90 % y mínimo tres modos, CQC con \(\beta=0.05\), combinación 0.25/0.75, mínimo 80 %/90 % y exclusión de desplazamientos (Art. 29); \(0.75R\)/\(0.85R\) y exclusiones del Art. 31.2 (Art. 31); \(s=0.006h \ge 0.03\ \text{m}\) (Art. 33); redundancia 30 % → 125 % (Art. 34); mínimos de elementos no estructurales (Art. 38–43).
- **Pendiente**: edición vigente de E.030 (2018 frente a la revisión 2025); transcripción del Anexo II de provincias y distritos; ediciones y combinaciones de E.060 y E.090; valores de la Tabla N° 12 (\(C_1\)).
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia licenciada o descarga oficial del MVCS y de El Peruano.
