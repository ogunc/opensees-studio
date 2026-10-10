---
name: chile-nch433-nch2369
description: >-
  Implementa el análisis y el diseño sísmico en Chile: NCh433.Of1996 Mod.2009 para
  edificios (aceleración efectiva A₀ por zona sísmica, clasificación de suelos A–E,
  factor de importancia I, coeficiente de reducción R con su tope R₀, período T*,
  espectro de diseño, análisis estático y modal espectral con combinación modal,
  distorsión de entrepiso máxima y torsión accidental) y NCh2369.Of2003 para
  estructuras e instalaciones industriales (coeficientes propios, requisitos de
  análisis, componentes no estructurales, desplazamientos y separaciones), con
  remisión a NCh430 para hormigón armado y a NCh427 para acero. Úsala cuando el
  proyecto declare norma chilena, al generar un espectro NCh433/NCh2369 o al
  auditar un módulo que use A₀, R₀, T*, α o una distorsión de entrepiso de 0.002.
metadata:
  track: codes
  jurisdiction: CHL
  edition: "NCh433 y NCh2369"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Chile — NCh433 (edificios) y NCh2369 (estructuras industriales)

## Cuándo usar esta skill

- El proyecto declara `code_id = nch433` o `nch2369`, o su ubicación está en Chile y hay que resolver qué norma aplica antes de calcular.
- Hay que obtener \(A_0\) por zona, clasificar el suelo, fijar \(I\) y \(R_0\), construir el espectro y el corte basal.
- Hay que comprobar la distorsión de entrepiso y decidir si el análisis estático es admisible o se exige modal espectral.
- Aparece una estructura industrial (nave, silo, estanque, soporte de equipo, tubería, galpón con puente grúa) donde rige NCh2369 y no NCh433.
- Se audita un módulo existente. Señales de defecto: \(C_d\), \(\Omega_0\), \(S_{DS}\), \(F_a/F_v\) o 100/30 atribuidos a NCh433; un \(R\) tabulado sin tope; una deriva comparada contra 0.025.
- **No usar** para otros países (→ `codes/asce7-22-seismic-design`, `codes/nicaragua-rnc07-nscm22`, `codes/colombia-nsr10`, `codes/peru-e030`, `codes/mexico-ntc-rcdf-cfe`, `codes/ecuador-nec15`). El dimensionamiento de elementos va a `design/concrete-aci318` y `design/steel-aisc360-341`; el peligro y la respuesta de sitio, a `seismic/seismic-hazard-and-site-response`.

## Alcance y límites

Cubre la acción sísmica y las comprobaciones globales de NCh433 (zonificación, suelo, \(I\), \(R\), espectro, \(T^*\), análisis estático y modal espectral, torsión, distorsión de entrepiso) y de NCh2369 (aplicación, coeficientes propios, requisitos de análisis, componentes no estructurales, desplazamientos y separaciones).
**No cubre** el diseño y detallado de elementos — NCh433 remite a **NCh430** (hormigón armado, con sus requisitos sismorresistentes) y a **NCh427** (acero) —, la albañilería (NCh1928/NCh2123), las fundaciones ni el diseño de anclajes.
Supuestos: análisis lineal elástico con espectro reducido por \(R\); diafragma rígido salvo justificación explícita; masa sísmica por nivel según la regla de carga de la norma, no la carga de diseño; unidades SI coherentes (N, m, kg, s, Pa) con \(g = 9.80665\ \text{m/s}^2\).

## Entradas y supuestos

| Dato | Obligatorio | Si falta o es ambiguo |
|---|---|---|
| Ubicación (coordenada o comuna) | sí | bloquear: la zona sale del mapa versionado, no del nombre de la ciudad |
| Zona sísmica (1, 2, 3) | sí | bloquear: \(A_0\) depende solo de la zona |
| Tipo de suelo A–E, con \(V_s\) por estrato y espesores | sí | bloquear; suelo E o «especial» exige estudio de sitio específico |
| Sistema estructural sismorresistente | sí | bloquear: define \(R_0\) |
| Categoría de ocupación o destino | sí | bloquear: define \(I\) |
| Naturaleza industrial y peligro de las sustancias | sí | decide NCh2369 frente a NCh433 |
| Pesos sísmicos \(P_i\) por nivel | sí | calcularlos con la regla de masa sísmica del código y declararla |
| Alturas libres \(h_i\), dimensión en planta \(b\), altura \(h_n\) | sí | bloquear: sin ellos no hay deriva ni torsión |
| Tablas de coeficientes del código | sí | leer de `data/chile/**` versionado; nunca del código Python |

Un resultado que dependa de un coeficiente con `verified: false` se emite marcado **preliminar**; un dato de sitio faltante es error, no un valor por defecto.

## Fundamento y formulación

### A. NCh433 — edificios

**A.1 Peligro y suelo.** La zonificación asigna a cada zona sísmica una aceleración efectiva \(A_0\) publicada en g; los valores corrientemente citados son Zona 1 \(0.20\,g\), Zona 2 \(0.30\,g\) y Zona 3 \(0.40\,g\) (NCh433, zonificación sísmica; tabla por transcribir, ver `VERIFICAR` en «Datos normativos»). La zona se resuelve por el mapa geográfico versionado, nunca por nombre de ciudad.
El suelo se clasifica A–E por la velocidad media ponderada de ondas de corte, \(V_s=\sum_i h_i/\sum_i(h_i/V_{s,i})\ [\text{m/s}]\), con \(h_i\) el espesor del estrato [m] y \(V_{s,i}\) su velocidad [m/s]; el tipo aporta \(S\) [-], \(T_0\) y \(T'\) [s] y los exponentes \(n\), \(p\) [-].

**A.2 Reducción por ductilidad.** \(R\) depende del período y su tope es el valor tabulado \(R_0\) del sistema estructural:

$$R=1+\frac{T^*}{c\,T_0+\dfrac{T^*}{R_0}}\ \le\ R_0$$

con \(T^*\) el período del edificio [s], \(T_0\) el período del suelo [s], \(c\) una constante adimensional del código y \(R_0\) [-] el coeficiente del sistema; \(R\to1\) si \(T^*\to0\) y \(R\to R_0\) si \(T^*\to\infty\).

> ⚠️ VERIFICAR: la expresión de \(S_a^{ref}(T)\), las tablas de \(S,T_0,T',n,p\), \(R_0\) e \(I\) y el valor de \(c\) no se contrastaron con el documento oficial; se comprueban en NCh433.Of1996 Mod.2009 (clasificación de suelos, análisis estático y modal) y el programa los **lee de `data/chile/nch433/*.json`** (`source`, `verified_on`).

**A.3 Corte basal y reparto en altura.** Método estático:

$$V_0=C_s\,P,\qquad C_s=\frac{I\,A_0\,S\,\alpha(T^*)}{R(T^*)},\qquad F_i=\frac{W_i\,h_i^{k}}{\sum_j W_j\,h_j^{k}}\,V_0$$

con \(V_0\) el corte basal [N], \(P\) el peso sísmico total [N], \(I\) [-] el factor de importancia, \(\alpha(T^*)\) [-] el factor de forma espectral, \(F_i\) la fuerza del nivel [N], \(W_i\) su peso sísmico [N] y \(h_i\) su altura sobre la base [m]; \(\sum_i F_i = V_0\) exacto y la forma clásica es la triangular (\(k=1\)). Existe un corte basal mínimo \(V_{0,min}\).

> ⚠️ VERIFICAR: el arreglo y los topes de \(\alpha\), la expresión de \(V_{0,min}\), el exponente \(k\) y el artículo que los fija; el programa lee `alpha`, `k` y `v0_min` del archivo de datos.

**A.4 Período.** Se admite el calculado (Rayleigh o análisis dinámico) y las fórmulas empíricas en \(h_n\), \(L\) y sistema estructural:

$$T=2\pi\sqrt{\frac{\sum_i W_i\,\delta_i^{2}}{g\sum_i F_i\,\delta_i}}\quad [\text{s}]$$

con \(\delta_i\) el desplazamiento del nivel \(i\) bajo las fuerzas \(F_i\) [m].

> ⚠️ VERIFICAR: las fórmulas empíricas de \(T^*\) (coeficientes, exponentes de \(h_n\) y \(L\)) y cualquier tope al período usado en el espectro; se transcriben a `data/chile/nch433/period.json`.

**A.5 Torsión accidental.** Sobre la excentricidad estática entre centro de masa y centro de rigidez se añade una accidental:

$$M_t=V\,e_{acc},\qquad e_{acc}=\beta_{acc}\,b\quad [\text{N}\cdot\text{m}]$$

con \(V\) el corte del nivel o de la base [N] y \(b\) la dimensión en planta perpendicular a la dirección analizada [m].

> ⚠️ VERIFICAR: el valor de \(\beta_{acc}\) (la práctica chilena cita 5 % de \(b\)), si se amplifican las fuerzas de los elementos de borde y en qué casos la torsión obliga a pasar a análisis dinámico; se comprueba en el artículo de torsión de NCh433 y se lee de `data/chile/nch433/torsion.json`.

**A.6 Distorsión de entrepiso.** Con \(\delta_i\) el desplazamiento horizontal del nivel \(i\) [m] y \(h_i\) la altura libre del entrepiso [m]:

$$\Delta_i=\delta_i-\delta_{i-1},\qquad \gamma_i=\frac{\Delta_i}{h_i}\ \le\ \gamma_{max}$$

> ⚠️ VERIFICAR: NCh433 fija \(\gamma_{max}=0.002\) para la distorsión de entrepiso; el artículo exacto, el estado límite y si la comprobación usa los desplazamientos del espectro reducido o los elásticos se comprueban en su capítulo de análisis. El valor se lee de `data/chile/nch433/drift.json`, no del código.

**A.7 Análisis modal espectral.** Con \(M\) la matriz de masa [kg], \(\phi_m\) el modo \(m\) [-] y \(\mathbf{1}\) el vector de influencia de la dirección analizada:

$$\Gamma_m=\frac{\phi_m^{\mathsf T}M\,\mathbf{1}}{\phi_m^{\mathsf T}M\,\phi_m},\qquad M_{eff,m}=\frac{\left(\phi_m^{\mathsf T}M\,\mathbf{1}\right)^{2}}{\phi_m^{\mathsf T}M\,\phi_m}\ [\text{kg}]$$

Se incluyen los modos necesarios para acumular el porcentaje de masa traslacional exigido, se combinan las respuestas modales (CQC o SRSS según la separación de períodos) y se corrigen las fuerzas si el corte basal dinámico queda por debajo del estático.

> ⚠️ VERIFICAR: el porcentaje de masa exigido, la regla de combinación modal, el factor de corrección del corte dinámico y la regla direccional (NCh433 no aparece con 100/30 en el mapa de `codes/code-crosswalk-and-extension`); el programa lee `modal.min_mass_ratio`, `modal.combination` y `modal.v_dynamic_factor`.

### B. NCh2369 — estructuras e instalaciones industriales

**B.1 Aplicación.** Rige para estructuras e instalaciones industriales, incluidas las que soportan equipos, estanques, silos, tuberías y puentes grúa. No es «NCh433 con \(R\) menor»: fija sus propios criterios de diseño, coeficientes, requisitos de análisis, exigencias de componentes y separaciones. Usa la misma zonificación de tres zonas con \(A_0\) en g y la misma clasificación de suelos A–E.

**B.2 Coeficientes y análisis.** \(I\) por categoría de la instalación y \(R\) (o su equivalente) tabulados por tipo de estructura industrial, con tope; la reducción es menor que en edificación porque se persigue daño limitado en lo que soporta el proceso. Exige análisis dinámico modal espectral en los casos que determina, combinación de las componentes horizontales y, para ciertos componentes, la vertical; el modelo incluye la rigidez de soportes de equipos y de fundación cuando sea significativa.

**B.3 Componentes no estructurales.** Las fuerzas de diseño de anclajes, apoyos y amarres de equipos, estanques y tuberías salen del modelo completo o de un coeficiente de amplificación propio de componentes, mayor que la aceleración del nivel que los soporta.

**B.4 Desplazamientos y separaciones.** Define estados límite de operación y de colapso con sus límites de deformación, y exige separación entre estructuras adyacentes para evitar el impacto:

$$s\ \ge\ \delta_A+\delta_B\quad [\text{m}]$$

con \(\delta_A,\delta_B\) los desplazamientos máximos de cada estructura en la dirección de la separación [m].

> ⚠️ VERIFICAR: los criterios de aplicación de NCh2369 frente a NCh433, sus valores de \(A_0\), categorías, \(I\), \(R\) y topes, límites del análisis estático, la amplificación de componentes, los límites de operación y colapso y si \(s\ge\delta_A+\delta_B\) lleva factor adicional; se comprueban en NCh2369.Of2003 y se transcriben a `data/chile/nch2369/*.json`.

## Procedimiento

1. Resolver la norma aplicable: edificación → NCh433; estructura o instalación industrial → NCh2369 (con el criterio de aplicación verificado).
2. Resolver la zona por el mapa de zonificación y obtener \(A_0\), registrando su valor en g y su conversión a m/s².
3. Clasificar el suelo por \(V_s\) ponderado y obtener \(S,T_0,T'\) (y \(n,p\)); rechazar suelo especial sin estudio específico.
4. Fijar el sistema estructural → \(R_0\), y la categoría → \(I\).
5. Estimar \(T^*\) (fórmula del código o Rayleigh), calcular \(R(T^*)\) y verificar \(1\le R\le R_0\).
6. Construir el espectro y comprobar continuidad en los quiebres y monotonía de la rama descendente antes de usarlo.
7. Elegir el procedimiento dentro de los límites de la norma y registrar esa comprobación.
8. Analizar, combinar modalmente y direccionalmente según el código.
9. Aplicar la torsión accidental y las amplificaciones de borde.
10. Corregir el corte basal dinámico si queda por debajo del estático.
11. Verificar distorsión de entrepiso por nivel y dirección; en NCh2369, además desplazamientos de operación/colapso y separaciones.
12. Emitir el informe con norma, edición, artículo, valores intermedios, conversiones de unidades y advertencias activas.

## Implementación en la plataforma

```python
# core/codes/chile_nch433.py   (core puro: sin Qt, sin OpenSeesPy)
def effective_acceleration(zone, data) -> float: ...   # A0 [m/s^2] de zones.json
def weighted_vs(layers) -> float: ...                  # (h_i [m], Vs_i [m/s]) -> Vs [m/s]
def site_parameters(soil, data) -> SoilParams: ...     # S, T0 [s], Tp [s], n, p; suelo especial -> SiteSpecificRequired
def reduction_R(T_star, R0, T0, data) -> float: ...    # R = 1 + T*/(c*T0 + T*/R0), tope R0; invalida R0 <= 1
def design_spectrum(A0, soil, R, I, data) -> ResponseSpectrum: ...   # Sa(T) [m/s^2]
def static_base_shear(A0, S, alpha, I, R, P, data) -> float: ...     # V0 [N] con el piso V0_min
def vertical_distribution(V0, W, h, k) -> list[float]: ...           # F_i [N]; suma exacta V0
def interstory_drift(disp, h) -> list[float]: ...                    # gamma_i [-]

# core/codes/chile_nch2369.py   (core puro)
def applicability(model_meta, data) -> str: ...        # "nch2369" | "nch433"
def industrial_parameters(zone, soil, category, system, data) -> dict: ...  # I, R, topes
def component_demand(level_accel, component, data) -> float: ...
def separation_required(delta_a, delta_b, data) -> float: ...               # s [m]
```

Reglas de arquitectura (ver `platform/platform-architecture-and-services` y `codes/code-crosswalk-and-extension`):

- El módulo normativo vive en `core/codes/` y **no importa Qt ni OpenSeesPy**; sigue el patrón de `core/tbdy_site.py` (tabla, interpolación recortada, rechazo del suelo que exige estudio) y añade el `kind` `"nch433"` a `core/target_spectrum.py` conservando su convención declarada de unidades.
- El **solver solo se usa desde `services/`**: el caso modal y la combinación viven en `services/spectrum.py` sobre `core/modal_combination.py`; el módulo chileno produce espectro y coeficientes y no abre el solver.
- Coeficientes en `data/chile/{nch433,nch2369}/*.json` con `value`, `unit`, `source`, `verified`; cambiar de edición = cambiar el directorio de datos, no el motor.
- \(A_0\) se publica en g: la conversión a m/s² ocurre una sola vez, en la frontera del módulo, con \(g = 9.80665\ \text{m/s}^2\), y queda registrada en el espectro (`accel_unit`).
- Pruebas en `tests/unit/codes/test_chile_nch433.py` y `test_chile_nch2369.py`.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Zonificación y \(A_0\) por zona (0.20/0.30/0.40 g citados) | NCh433 | parcial — `VERIFICAR` |
| Clasificación de suelos A–E (\(V_s\)) | NCh433 | no — `VERIFICAR` |
| \(S, T_0, T', n, p\) por tipo de suelo | NCh433 | no — `VERIFICAR` |
| Expresión de \(S_a^{ref}(T)\) y espectro de diseño | NCh433 | no — `VERIFICAR` |
| \(R=1+T^*/(cT_0+T^*/R_0)\le R_0\) | NCh433 | parcial: forma sí, \(c\) no |
| \(R_0\) por sistema estructural | NCh433 | no — `VERIFICAR` |
| \(I\) por categoría de ocupación | NCh433 | no — `VERIFICAR` |
| \(V_0=C_sP\), \(C_s=I A_0 S\alpha/R\), \(V_{0,min}\) | NCh433 | parcial |
| Reparto \(F_i=W_ih_i^{k}V_0/\sum_j W_jh_j^{k}\) | NCh433 | parcial: \(k\) no |
| \(\gamma_{max}=0.002\) de distorsión de entrepiso | NCh433 | parcial — `VERIFICAR` |
| \(e_{acc}=\beta_{acc}b\) (5 % citado) | NCh433 | no — `VERIFICAR` |
| Masa sísmica \(P\) (fracción de carga de uso) | NCh433 | no — `VERIFICAR` |
| Combinación modal y direccional | NCh433 | no — `VERIFICAR` |
| Aplicación, \(I\), \(R\), análisis, componentes, desplazamientos, separaciones | NCh2369.Of2003 | no — `VERIFICAR` |
| Detallado sismorresistente de hormigón armado | NCh430.Of2008 | referencia, no se transcribe |
| Acero estructural (partes y edición vigentes) | NCh427 | referencia — `VERIFICAR` |

Ningún valor de esta tabla se escribe en el código Python: todos se cargan de `data/chile/**` con su cita y su fecha de verificación.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| \(V_s\) ponderado | (3 m, 200), (7 m, 400), (10 m, 800) | \(V_s=444.44\ \text{m/s}\) | 0.01 m/s | aritmética |
| \(\Gamma\), \(M_{eff}\) 1 GDL | \(m=10^4\ \text{kg}\), \(\phi=1\) | \(\Gamma=1.0\), \(M_{eff}=10^4\ \text{kg}\) | 1e-9 | definición |
| \(\Gamma\), \(M_{eff}\) 2 GDL | \(m_1=m_2=m\), \(\phi=(1,\ 1.5)\) | \(\Gamma=0.769230769\), \(M_{eff}=1.923076923\,m\) | 1e-9 | cálculo a mano |
| Reparto en altura | 3 niveles \(W=10^6\ \text{N}\), \(h=3,6,9\ \text{m}\), \(k=1\), \(V_0=10^6\ \text{N}\) | \(F=(1/6,\ 1/3,\ 1/2)V_0\) y \(\sum F_i=V_0\) | 1e-9 | aritmética |
| Deriva en el límite | \(\Delta=6.0\ \text{mm}\), \(h=3.0\ \text{m}\) | \(\gamma=0.002=\gamma_{max}\) | 1e-9 | NCh433 (valor en `VERIFICAR`) |
| Deriva excedida | \(\Delta=8.0\ \text{mm}\), \(h=3.0\ \text{m}\) | \(\gamma=0.002667>\gamma_{max}\) | 1e-9 | NCh433 (valor en `VERIFICAR`) |
| Continuidad del espectro | nodos \(T=0.5\to0.60\,g\), \(T=0.6\to0.50\,g\) | reproduce el nodo; sin salto en el quiebre | 1e-9 rel. | invariante de forma |
| Topes de \(R\) | \(R_0=6\); \(T^*\to0^{+}\) y \(T^*=200\ \text{s}\) | \(R\to1\), \(R\to R_0=6\), monótona creciente | 1e-6 | invariante de forma |
| Torsión accidental | \(V=1.2\times10^6\ \text{N}\), \(b=20\ \text{m}\), \(e_{acc}=0.05b\) | \(M_t=1.2\times10^6\ \text{N}\cdot\text{m}\) | 1e-9 | NCh433 (\(\beta_{acc}\) en `VERIFICAR`) |
| Separación | \(\delta_A=40\ \text{mm}\), \(\delta_B=25\ \text{mm}\) | \(s\ge65\ \text{mm}\) | 1e-9 | NCh2369 (por confirmar) |

Contraste obligatorio: reproducir un edificio chileno documentado y comparar período fundamental, corte basal y distorsión de entrepiso contra el valor publicado, dentro del 5 %. Ningún caso pasa a `ready` mientras el valor normativo que usa siga en `VERIFICAR`.

## Errores frecuentes y trampas

1. **Resolver la zona por nombre de ciudad**: las fronteras son geográficas y la asignación manual falla en comunas limítrofes y no es trazable.
2. **Usar \(A_0\) como aceleración de diseño**, sin la amplificación por suelo \(S\) ni el factor de importancia \(I\).
3. **Guardar un solo campo `R`**: \(R_0\) es tabular (sistema) y \(R\) es el valor reducido por \(T^*\) acotado por \(R_0\); confundirlos hace irreproducible el corte basal.
4. **No aplicar el tope \(R\le R_0\)**: las estructuras flexibles reciben menos demanda que la del código.
5. **Evaluar \(R\) con el período del modo en curso** cuando el código define el valor para el edificio (o al revés): el espectro deja de ser único y el corte basal cambia sin justificación.
6. **Convertir g a m/s² dos veces**, o no convertirla nunca: mezclar g con m/s² en la misma fórmula.
7. **Comparar la deriva con los desplazamientos equivocados**: la distorsión se calcula con los que el código define para ese estado límite, y aplicar el factor de reducción dos veces es el fallo simétrico.
8. **Restar desplazamientos ya combinados** en el análisis modal en lugar de combinar las derivas por modo: la deriva combinada no es la diferencia de los desplazamientos combinados.
9. **Aplicar NCh433 a una instalación industrial** (o NCh2369 a una edificación): los requisitos de análisis, componentes y separaciones de NCh2369 son propios.
10. **Adoptar el suelo D cuando falta el estudio**, o tratar un suelo especial como E; el módulo debe rechazar el cálculo, como `core/tbdy_site.py` hace con ZF.
11. **Cargar coeficientes sin `source`/`verified`** y perder la marca preliminar del informe.
12. **Mezclar el peso sísmico** (permanente más la fracción de carga de uso que el código define) con la carga gravitacional de diseño.

## Interfaz de salida

Para cada dirección de análisis el programa reporta:

- `code_id`, edición, fecha de verificación de los datos y ámbito resuelto (NCh433 o NCh2369) con la regla de selección.
- Zona sísmica, \(A_0\) en g y en m/s², tipo de suelo, \(V_s\) ponderado, y \(S,T_0,T'\) con su cita.
- Sistema estructural, \(R_0\), \(T^*\), \(R(T^*)\), \(I\), \(\alpha\), \(P\), cada uno con su cita y su marca `verified`.
- Espectro usado (elástico y de diseño) con `accel_unit` y su malla de períodos, y el corte basal estático y dinámico con la corrección aplicada y \(F_i\) por nivel.
- Distorsión de entrepiso por nivel y dirección, \(\gamma_{max}\) aplicable, \(\gamma/\gamma_{max}\) y veredicto por nivel; torsión con \(e_{acc}\), \(M_t\) y fuerzas amplificadas de borde.
- NCh2369: categoría, coeficientes propios, demandas de componentes, desplazamientos de operación/colapso y separación requerida.
- Advertencias activas: coeficientes sin verificar, suelo especial sin estudio, método fuera de sus límites y edición distinta de la registrada en el proyecto.

## Referencias

1. INN, *NCh433.Of1996 — Diseño sísmico de edificios*, Modificada 2009 (`VERIFICAR` el decreto supremo que la oficializa).
2. INN, *NCh2369.Of2003 — Diseño sísmico de estructuras e instalaciones industriales* (`VERIFICAR` modificaciones posteriores vigentes).
3. INN, *NCh430.Of2008 — Hormigón armado: requisitos de diseño y cálculo* (`VERIFICAR` modificaciones).
4. INN, *NCh427 — Cálculo de estructuras de acero*, partes 1 y 2 (`VERIFICAR` ediciones y años vigentes).
5. INN, *NCh1928.Of1993 — Albañilería armada* y *NCh2123.Of1997 — Albañilería confinada*.
6. AISC 360 y AISC 341 — referencia para el acero sismorresistente cuando la norma chilena remite a ella.
7. `codes/code-crosswalk-and-extension` — contrato de datos, registro por ubicación y tabla de equivalencias entre códigos.
8. `platform/platform-architecture-and-services` — capas, unidades y puntos de extensión del núcleo de cálculo.

## Registro de verificación

- **Verificado (forma, no valor)**: la secuencia de comprobaciones de NCh433 (zonificación, suelo, \(I\), \(R\) con tope \(R_0\), espectro por parámetros de suelo, análisis estático y modal espectral, combinación modal, distorsión de entrepiso, torsión) y de NCh2369 (aplicación, coeficientes propios, análisis, componentes, desplazamientos, separaciones); las expresiones de \(V_s\) ponderado, \(\Gamma_m\), \(M_{eff,m}\), el reparto \(F_i\), la distorsión \(\Delta_i/h_i\) y la separación \(s\ge\delta_A+\delta_B\).
- **Pendiente**: todos los valores tabulados y la expresión exacta del espectro, la constante \(c\) de \(R\), \(R_0\), \(I\), \(k\), \(\alpha\), \(V_{0,min}\), \(\beta_{acc}\), el porcentaje de masa modal, la combinación direccional y los coeficientes de NCh2369; se cierran transcribiéndolos a `data/chile/**` con prueba unitaria contra la tabla del documento oficial.
- **Responsable de cerrar**: ingeniero estructural con registro en Chile. La skill permanece `draft` mientras exista cualquier `VERIFICAR` abierto.
