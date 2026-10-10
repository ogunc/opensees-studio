---
name: load-combinations-and-limit-states
description: >-
  Construye los sistemas de cargas y las combinaciones de carga de un proyecto de
  análisis estructural: cargas muertas, vivas con reducción por área tributaria,
  vivas de cubierta, nieve, viento simplificado, sismo con E = Eh + Ev, empuje de
  tierras, juegos LRFD y ASD, combinaciones de servicio, dirección y alternancia
  de signos, generación automática de envolventes y trazabilidad de la combinación
  que gobierna cada esfuerzo. Úsala al definir acciones, al generar o auditar un
  juego de combinaciones, al producir envolventes de esfuerzos, o cuando el usuario
  pregunta qué combinación produce un resultado o por qué el programa marca un
  coeficiente como preliminar.
metadata:
  track: seismic
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Sistemas de cargas, combinaciones y estados límite

## Cuándo usar esta skill

- Hay que declarar las acciones del proyecto (D, L, Lr, S, R, W, E, H, F, T) y decidir cuáles son revertibles.
- Hay que generar el juego de combinaciones de un código, para resistencia (LRFD) o para esfuerzos admisibles (ASD).
- Hay que producir una **envolvente** de esfuerzos y saber **qué combinación gobierna** cada barra, estación y componente.
- Hay que comprobar estados límite de servicio (deflexión, deriva, vibración) con la combinación no mayorada correcta.
- El usuario reporta que una capacidad está mal: "amplificó dos veces", "el cortante basal no coincide con el peso sísmico", "la deriva sale del doble", "esa carga viva no debía reducirse".
- Hay que auditar un juego de combinaciones importado de otro programa o de una hoja de cálculo.

**No usar** para el peligro sísmico ni \(S_a(T)\) (→ `seismic/seismic-hazard-and-site-response`), para torsión, P-Δ y 100/30 (→ `seismic/seismic-analysis-procedures`), ni para los coeficientes de un código concreto (→ `codes/...`). La capacidad de los elementos es de `design/concrete-aci318` y `design/steel-aisc360-341`.

## Alcance y límites

Cubre valores característicos de las acciones, reducción de carga viva, peso sísmico efectivo, formatos LRFD/ASD, combinaciones de servicio, dirección y signos, envolventes con trazabilidad, y el contrato de datos de los juegos nacionales.

No cubre la construcción del espectro, la combinación modal (CQC/SRSS) ni la integración paso a paso; tampoco los factores de resistencia \(\phi\) ni las ecuaciones de interacción. Supone linealidad de la combinación de acciones (lo es por definición), aunque el análisis por combinación pueda ser no lineal.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Familia y edición de combinaciones (`asce7-22`, `nsr-10`, `e030`, …) | sí | bloquear: no se mezclan familias |
| Valor característico de cada acción | sí | bloquear; no se asume un valor típico |
| Uso u ocupación del piso, \(A_T\) (m²), \(K_{LL}\) y pisos soportados | solo para reducir \(L\) | no reducir \(L\) y avisar |
| \(S_{DS}\) y edición del código sísmico | sí si hay \(E\) | bloquear \(E\) |
| \(V\) (m/s), exposición y \(K_{zt}\) | sí si hay \(W\) | bloquear \(W\) |
| \(W\) o los datos para calcular el peso sísmico | sí si hay \(E\) | calcularlo y reportar el desglose |
| Coeficiente con `verified: true` en el archivo de datos | sí | marcar el resultado **preliminar** |

Unidades internas SI coherentes (N, m, kg, s, Pa); \(g = 9.80665\ \text{m/s}^2\). Las aceleraciones espectrales se publican en g y se declaran: \(S_{DS} = 1.0\,g\). Los factores de carga son adimensionales.

## Fundamento y formulación

### 1. Naturalezas de carga
D muerta (peso propio + permanentes), L viva de piso, Lr viva de cubierta, S nieve, R lluvia, W viento, E sismo, H empuje de tierras, F fluidos, T temperatura y retracción. Solo **W** y **E** son revertibles: aportan dos ramas de signo por eje y exigen envolvente. Las demás tienen dirección fija y un único sentido de aplicación. H puede resistir la acción principal y por eso lleva **dos** factores (favorable y desfavorable), que son dato normativo, no criterio del programa.

### 2. Reducción de carga viva por área tributaria
La norma la publica con \(A_T\) en ft²; \(15\ \text{ft}^{-1} = 15/\sqrt{10.7639} = 4.5720\ \text{m}^{-1}\), con \(A_T\) en m²:

$$L = L_0\left(0.25 + \frac{4.5720}{\sqrt{K_{LL}\,A_T}}\right), \qquad L \ge 0.50\,L_0 \ \text{(un piso)}, \qquad L \ge 0.40\,L_0 \ \text{(dos o más)}$$

\(L_0\) = viva sin reducir (Pa); \(K_{LL}\) = factor de elemento de carga viva (adimensional, ASCE 7-22 Table 4.7-1); \(A_T\) = área tributaria (m²). No se reduce \(L\) donde la norma lo prohíbe: ocupaciones de asamblea, garajes, \(L_0 > 4.79\ \text{kN/m}^2 \approx 100\ \text{psf}\).

> ⚠️ VERIFICAR: la lista de exclusiones de reducción y el \(K_{LL}\) de cada elemento (ASCE 7-22, §4.7.1 y Table 4.7-1) no se transcriben desde el estándar impreso. El programa debe leer `data/asce7-22/live_load.json` (campos `kll`, `reducible`) con `source` y `verified_on`.

### 3. Viva de cubierta, nieve y viento
Viva de cubierta reducida (ASCE 7-22, §4.8.2): \(L_r = L_0 R_1 R_2\), con \(R_1\) función del área tributaria (ft²) y \(R_2\) del número de contrapendientes o de la pendiente.

Nieve sobre cubierta (ASCE 7-22, §7.3): \(p_f = 0.7\,C_e C_t I_s p_g\ [\text{Pa}]\), con \(C_e\) exposición, \(C_t\) térmico, \(I_s\) importancia y \(p_g\) nieve del terreno (Pa). La nieve no balanceada y la lluvia sobre nieve son casos separados que no se suman al \(p_f\) balanceado. Presión dinámica de viento (Pa, \(V\) en m/s): \(q_z = 0.613\,K_z K_{zt} K_d K_e V^2\), con \(p = q\,G\,C_p - q_i(GC_{pi})\); el método simplificado para edificios bajos cerrados usa \(p_s = \lambda K_{zt} I_w p_{s30}\), con \(p_{s30}\) tabulada para exposición B a \(h = 9.1\ \text{m}\) (30 ft).

> ⚠️ VERIFICAR: los tramos de \(R_1\) y \(R_2\) (§4.8.2), los factores \(C_e\), \(C_t\), \(I_s\) (cap. 7) y el capítulo, figuras y valor de \(\lambda\) del método simplificado de viento de ASCE 7-22 (los caps. 26–32 se renumeraron respecto a 7-16, que lo ubicaba en el cap. 28). Se leen de `data/asce7-22/roof_live_snow.json` y `data/asce7-22/wind_simplified.json`.

### 4. Sismo: efecto horizontal y vertical
$$E = E_h + E_v, \qquad E_h = \rho\,Q_E, \qquad E_v = 0.2\,S_{DS}\,D$$

\(Q_E\) = efecto de las fuerzas sísmicas horizontales; \(\rho\) = factor de redundancia; \(D\) = efecto de la carga muerta; \(S_{DS}\) en g (declarado). La combinación \(0.9D + 1.0E\) exige tomar \(E_v\) **negativo**, es decir \((0.9 - 0.2S_{DS})D + E_h\): con \(E_v\) siempre positivo el modelo nunca ve el levantamiento ni la tracción en columnas.

### 5. Empuje de tierras
\(k_0 = 1 - \sin\phi'\), \(k_a = \tan^2(45^\circ - \phi'/2)\), \(k_p = \tan^2(45^\circ + \phi'/2)\), con \(\phi'\) = ángulo de fricción efectivo (grados o radianes, se declara). El empuje del agua en el suelo se modela como acción separada, no sumado a \(H\) dentro de la misma componente.

> ⚠️ VERIFICAR: los factores favorable y desfavorable de \(H\) en ASCE 7-22 (§2.3.1 y §2.4.1) y el tratamiento del agua. Se leen de `data/asce7-22/combinations.json`.

### 6. Juegos LRFD y ASD

| # | Resistencia (LRFD) | # | Esfuerzos admisibles (ASD) |
|---|---|---|---|
| 1 | \(1.4D\) | 1 | \(D\) |
| 2 | \(1.2D + 1.6L + 0.5(L_r \text{ o } S \text{ o } R)\) | 2 | \(D + L\) |
| 3 | \(1.2D + 1.6(L_r \text{ o } S \text{ o } R) + (L \text{ o } 0.5W)\) | 3 | \(D + (L_r \text{ o } S \text{ o } R)\) |
| 4 | \(1.2D + 1.0W + L + 0.5(L_r \text{ o } S \text{ o } R)\) | 4 | \(D + 0.75L + 0.75(L_r \text{ o } S \text{ o } R)\) |
| 5 | \(1.2D + 1.0E + L + 0.2S\) | 5 | \(D + (0.6W \text{ o } 0.7E)\) |
| 6 | \(0.9D + 1.0W\) | 6 | \(D + 0.75L + 0.75(0.6W) + 0.75(L_r \text{ o } S \text{ o } R)\) |
| 7 | \(0.9D + 1.0E\) | 7 | \(D + 0.75L + 0.75(0.7E) + 0.75S\) |
|  |  | 8 | \(0.6D + 0.6W\) |
|  |  | 9 | \(0.6D + 0.7E\) |

Las alternativas "o" son excluyentes: cada una genera una rama, no una suma. \(L_r\), \(S\) y \(R\) nunca se suman entre sí, y \(0.5(L_r \text{ o } S \text{ o } R)\) no admite las tres a la vez.

> ⚠️ VERIFICAR: la numeración y el texto literal de las tablas de ASCE 7-22 (§2.3.1 y §2.4.1 reorganizaron las de 7-16 §2.3.1/§2.3.2/§2.4.1) y la carga de tornado del cap. 32 como acción revertible adicional. Se transcriben a `data/asce7-22/combinations.json` con prueba unitaria valor por valor.

### 7. Juegos nacionales
Lo que cambia entre códigos no son solo los números sino la **estructura**: quién lleva el factor de importancia, si el sismo entra ya reducido por \(R\), y si existe término vertical.

| Familia | Rasgo propio |
|---|---|
| NSR-10 (Colombia, Títulos A y B §B.2.4) | linaje ASCE 7-05; define el peso sísmico \(W = CM + CVR\), con \(CVR\) (carga viva incidental) según el uso |
| NTE E.030 / E.060 (Perú) | tres combinaciones: \(1.4CM + 1.7CV\); \(1.25(CM+CV) \pm CS\); \(0.9CM \pm CS\); el \(\pm CS\) es obligatorio |
| RNC-07 (Nicaragua) | \(W_0 = CM + CVR\), con \(CVR\) una fracción de la viva (→ `codes/nicaragua-rnc07-nscm22`) |
| NSCM-22 (Managua) | linaje ASCE 7-16; hereda el formato LRFD/ASD con factores propios |

> ⚠️ VERIFICAR: los factores literales de NSR-10 §B.2.4, de la NTE E.060 (Perú) y de NSCM-22 no se transcriben aquí. Cada uno se comprueba en su documento oficial y se guarda en `data/<pais>/<code_id>/combinations.json`; los skills `codes/colombia-nsr10`, `codes/peru-e030` y `codes/nicaragua-rnc07-nscm22` son responsables de esa transcripción.

### 8. Dirección, signos, envolventes y estados límite
Cada acción revertible aporta dos ramas por eje (\(+W,-W\); \(+E,-E\)). Efectos ortogonales (ASCE 7-22, §12.5.4): \(E = E_x + 0.3E_y\), \(E = 0.3E_x + E_y\) y sus cuatro combinaciones de signo. Con \(S_k(x)\) el esfuerzo en la sección \(x\) bajo la combinación \(k\):

$$\overline{S}(x) = \max_k S_k(x), \qquad \underline{S}(x) = \min_k S_k(x), \qquad k^*(x) = \arg\max_k \left|S_k(x)\right|$$

La envolvente es **por componente** (N, Vy, Vz, T, My, Mz) y guarda \(k^*\). Mezclar el máximo de una componente con el de otra tomados de combinaciones distintas rompe el equilibrio; solo es válido si la comprobación posterior es envolvente de la razón demanda/capacidad.

Estados límite: **resistencia** \(\phi R_n \ge R_u\) con \(R_u\) de la tabla LRFD; **esfuerzos admisibles** \(R_a \ge R\) con \(R\) de la tabla ASD; **servicio** (deflexión, deriva, vibración, fisuración) con combinaciones no mayoradas y **nunca** con las de resistencia.

> ⚠️ VERIFICAR: los límites numéricos de deriva (ASCE 7-22 Table 12.12-1, → `codes/asce7-22-seismic-design`) y de deflexión por elemento y acabado (p. ej. IBC 2024 Table 1604.3) se leen de `data/<code>/serviceability_limits.json`; no se codifican.

## Procedimiento

1. **Normalizar** cada caso de carga a una de las diez naturalezas; rechazar toda carga sin naturaleza (no se combina lo que no se clasifica).
2. **Calcular** los valores derivados: \(L\) reducida, \(L_r\), \(p_f\), \(q_z\), \(W\) (peso sísmico efectivo) y \(E_v = 0.2S_{DS}D\).
3. **Seleccionar la familia** y cargar su `combinations.json`; verificar que todo coeficiente usado tenga `verified: true`.
4. **Expandir alternativas**: cada "o" produce una rama; cada acción revertible, dos signos; la ortogonalidad, 100/30 en ambos sentidos.
5. **Canonicalizar** cada combinación (factores ordenados por naturaleza + rama de signo), calcular su hash y descartar duplicados.
6. **Resolver** una vez por combinación: con linealidad se superponen los casos base; con no linealidad cada combinación es una corrida del solver.
7. **Construir la envolvente** por componente y registrar \(k^*\) por elemento, estación y componente.
8. **Comprobar** cada estado límite con su combinación correcta y emitir el veredicto con la cita del artículo aplicable.
9. **Reportar** avisos: coeficientes no verificados, acciones revertibles sin alternancia de signo, elementos sin \(K_{LL}\) (no se redujo \(L\)).

## Implementación en la plataforma

```python
# core/loads/cases.py  — Pydantic v2; sin Qt, sin openseespy
class LoadCase(BaseModel):
    id: str                       # "D", "L_p3", "W_X", "E_X", "H_muro_norte"
    nature: Literal["D","L","Lr","S","R","W","E","H","F","T"]
    magnitude: float              # N, N/m o N/m2 según `apply_as`
    apply_as: Literal["nodal","line","area","body"]
    direction: tuple[float, float, float]
    at_m2: float | None = None    # área tributaria, para reducir L
    kll: float | None = None
    floors_supported: int | None = None

# core/loads/live_reduction.py
def reduced_live_load(l0_pa: float, at_m2: float, kll: float,
                      floors_supported: int, reducible: bool) -> float:
    """L reducida en Pa; aplica el tope 0.50/0.40 L0. No reduce si no es reducible."""

# core/loads/seismic_weight.py
def effective_seismic_weight(cases: Sequence[LoadCase],
                             code_data: CodeData) -> SeismicWeight:
    """W con desglose por piso (D + fracción de L + fracción de S)."""

# core/combinations/generator.py
def generate(family: str, code_data: CodeData,
             options: ComboOptions) -> tuple[Combination, ...]:
    """Combinaciones canónicas y deterministas. Lanza CoefficientNotVerified."""

# core/combinations/envelope.py
def envelope(cases: Sequence[ComboResult], components: Sequence[str]) -> Envelope:
    """Máximo, mínimo y combinación gobernante por (elemento, estación, componente)."""
```

Reglas de arquitectura (→ `platform/platform-architecture-and-services`):

- La generación vive en `core/combinations/`; el solver se usa **solo** desde `services/combination_runner.py`, con `run_combinations(project, plan, out_dir)`.
- Ningún factor se escribe en el código: `data/<jurisdiction>/<code_id>/combinations.json`, con `value`, `unit`, `source` y `verified`.
- La generación es pura y determinista: misma entrada, mismo hash; el `manifest.json` guarda `code_id`, edición y `sha256` del archivo de datos.
- Errores tipados: `CoefficientNotVerified`, `MissingLoadCase`, `CodeFamilyMix` (dos ediciones en el mismo juego), `UnclassifiedAction`.
- `core/` no importa Qt ni OpenSeesPy; la GUI consume el resultado a través de un servicio.

## Datos normativos

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(E = E_h + E_v\), \(E_v = 0.2S_{DS}D\), \(E_h = \rho Q_E\) | ASCE 7-22, §12.4.2 | sí |
| Forma de la reducción de \(L\), topes \(0.50L_0\)/\(0.40L_0\) y constante SI \(4.5720\ \text{m}^{-1} = 15/\sqrt{10.7639}\) | ASCE 7-22, §4.7.2 | sí |
| \(p_f = 0.7C_eC_tI_sp_g\) | ASCE 7-22, §7.3 | sí |
| \(q_z = 0.613K_zK_{zt}K_dK_eV^2\) (Pa, \(V\) en m/s) | ASCE 7-22, cap. 26 | sí |
| Efectos ortogonales 100/30 | ASCE 7-22, §12.5.4 | sí |
| Coeficientes de empuje \(k_0\), \(k_a\), \(k_p\) | mecánica de suelos (Rankine) | sí |
| Factores literales de LRFD y ASD | ASCE 7-22, §2.3.1 y §2.4.1 | no — `VERIFICAR` |
| Table 4.7-1 (\(K_{LL}\)) y exclusiones de reducción | ASCE 7-22, §4.7.1 | no — `VERIFICAR` |
| \(R_1\), \(R_2\), \(C_e\), \(C_t\), \(I_s\) | ASCE 7-22, §4.8.2 y cap. 7 | no — `VERIFICAR` |
| Método simplificado de viento y valor de \(\lambda\) | ASCE 7-22, caps. 26–32 | no — `VERIFICAR` |
| Factores favorable/desfavorable de \(H\) | ASCE 7-22, §2.3.1 y §2.4.1 | no — `VERIFICAR` |
| Juegos de NSR-10, E.030/E.060 y NSCM-22 | documentos nacionales | no — `VERIFICAR` |
| Límites de servicio (deriva, deflexión) | ASCE 7-22 Table 12.12-1; IBC Table 1604.3 | no — `VERIFICAR` |

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Reducción de \(L\) | \(L_0=2.40\) kN/m², \(K_{LL}=4\), \(A_T=37.16\) m² | \(L/L_0 = 0.625\); \(L = 1.50\) kN/m² | 1e-6 rel | mano: \(0.25+15/\sqrt{1600}\) |
| Constante de conversión | \(A_T\) en m² en lugar de ft² | \(k = 4.5720\) m\(^{-1}\) | 1e-4 | \(15/\sqrt{10.7639}\) |
| Topes de reducción | un piso con cociente calculado \(0.40\); garaje con `reducible=False` | devuelve \(0.50L_0\); devuelve \(L_0\) | 1e-9 / exacto | §4.7.2 y §4.7.1 |
| Peso sísmico | D = 5000 kN, L = 1200 kN (almacén) | \(W = 5000 + 0.25(1200) = 5300\) kN | 1e-9 rel | §12.7.2 |
| \(E_v\) | \(S_{DS}=1.0\), \(D = 1000\) kN | \(E_v = 200\) kN | 1e-9 | §12.4.2 |
| LRFD-5 | D=1000, L=300, S=0, \(E_h\)=400 kN, \(S_{DS}\)=1.0 | \(R_u = 2100\) kN | 1e-9 rel | §2.3.1 |
| LRFD-2 | D=1000, L=300, Lr=100 kN | \(R_u = 1730\) kN | 1e-9 rel | §2.3.1 |
| ASD-8 | D=1000 kN, W = −250 kN | \(R = 450\) kN | 1e-9 rel | §2.4.1 |
| Levantamiento | comb. 7, \(S_{DS}=1.0\), \(E_h=0\) | \((0.9-0.2)1000 = 700\) kN (no 900) | 1e-9 rel | §12.4.2 |
| Ortogonal 100/30 | \(E_x=400\), \(E_y=200\) kN | \(1.0E_x+0.3E_y = 460\) kN | 1e-9 rel | §12.5.4 |
| Envolvente | 3 combinaciones; máx. N en C3 y máx. M en C1 | reporta los dos \(k^*\) | exacto | contrato de esta skill |
| Canonicidad | la misma combinación escrita en otro orden | un hash, una rama | exacto | contrato de esta skill |
| Trazabilidad | cualquier resultado | `code_id`, edición, `sha256` y cita no vacíos | exacto | `codes/code-crosswalk-and-extension` |

Contraste obligatorio: un juego completo recalculado a mano y otro contra un programa de referencia reconocido, con la combinación gobernante impresa en ambos.

## Errores frecuentes y trampas

1. **Amplificar dos veces el sismo**: meter \(\Omega_0\) (o \(R\)) en el factor de la combinación y además amplificar los efectos por separado, o contar \(\rho\) y \(A_x\) dentro de una combinación cuando ya están incluidos en \(E_h\).
2. **Aplicar \(E_v\) dos veces**: usar \(1.2D+1.0E\) con \(E\) ya conteniendo \(0.2S_{DS}D\) y añadir luego un término vertical explícito; el factor efectivo sobre \(D\) pasa a \(1.4\).
3. **Omitir la carga viva incidental en el peso sísmico**: calcular \(W\) solo con \(D\) y comparar después el cortante basal contra el "peso total".
4. **Mezclar familias**: factores de NSR-10 con \(R\) de ASCE 7, o \(\phi\) de ACI dentro de combinaciones ASD. El generador debe rechazarlo, no promediarlo.
5. **Signo fijo en \(E_v\)**: la combinación \(0.9D + 1.0E\) sin \(E_v\) negativo no detecta levantamiento ni tracción en columnas.
6. **Envolvente que viola el equilibrio**: tomar \(M_{max}\) de una combinación y \(V_{max}\) de otra para la misma comprobación de corte-flexión.
7. **Reducir \(L\) con el área de influencia** en vez del área tributaria, o reducir donde la norma lo prohíbe (asamblea, garajes, \(L_0\) alto).
8. **Sumar las alternativas "o"**: \(L_r+S+R\) simultáneos, o \(L+L_r\) duplicando la sobrecarga de cubierta.
9. **Usar la combinación de servicio para resistencia** (o la mayorada para deflexiones), y comparar derivas con \(\delta_{xe}\) en lugar de \(C_d\delta_{xe}/I_e\).
10. **Convertir mal ft² a m²** en la reducción de viva (la constante 15 con \(A_T\) en m² infla la reducción ~15 %) y **redondear \(S_{DS}\)** o los factores antes de combinar, perdiendo el control de la tolerancia de regresión.
11. **Indexar resultados por posición** en vez de por hash canónico: dos corridas distintas asignan la envolvente a la combinación equivocada.

## Interfaz de salida

Por proyecto, el programa debe exponer:

- El catálogo de casos de carga con naturaleza, dirección, magnitud y unidades SI.
- El desglose de \(W\) por piso y por naturaleza, con la fracción de \(L\) y de \(S\) usada y su cita.
- La tabla de combinaciones: id canónico, factores por naturaleza, rama de signo y la cita de cada factor (`code_id`, edición, tabla o sección).
- La envolvente por elemento, estación y componente, con la combinación gobernante \(k^*\) y su valor.
- Las comprobaciones de estado límite con veredicto, combinación usada y artículo aplicable.
- Avisos: coeficientes con `verified: false` → resultado **preliminar**; elementos sin \(K_{LL}\) → \(L\) no reducida; acciones revertibles sin alternancia de signo; familias mezcladas → error, no aviso.

## Referencias

1. ASCE/SEI 7-22, *Minimum Design Loads and Associated Criteria for Buildings and Other Structures* (2022). Capítulos 2, 3, 4, 7, 12, 26–32.
2. ASCE/SEI 7-16 (2017). Referencia de comparación para la reorganización de las tablas de combinaciones.
3. NSR-10, *Reglamento Colombiano de Construcción Sismo Resistente* (2010). Título A y Título B, §B.2.4.
4. NTE E.030 *Diseño Sismorresistente* (Perú, 2018) y NTE E.060 *Concreto Armado* (Perú, 2009), §9.2.
5. RNC-07, *Reglamento Nacional de la Construcción* (Nicaragua, 2007) y NSCM-22 (Nicaragua, 2022).
6. ICC, *International Building Code* (2024), Table 1604.3 — límites de deflexión.
7. ACI 318-19, §24.2, y AISC 360-22, capítulos B y C — deflexiones de servicio y estados límite del acero.

## Registro de verificación

- **Verificado**: la forma de la reducción de carga viva y sus topes; la conversión ft²→m² de la constante; \(E = E_h + E_v\) con \(E_v = 0.2S_{DS}D\) y \(E_h = \rho Q_E\); \(p_f = 0.7C_eC_tI_sp_g\); \(q_z = 0.613K_zK_{zt}K_dK_eV^2\); los coeficientes de empuje de tierras; la estructura general de los juegos LRFD y ASD; los efectos ortogonales 100/30.
- **Pendiente (bloquea el paso a `ready`)**: transcripción valor por valor de las tablas de combinaciones de ASCE 7-22 y de los juegos nacionales; Table 4.7-1 (\(K_{LL}\)) y exclusiones; \(R_1\), \(R_2\), \(C_e\), \(C_t\), \(I_s\); capítulo y figuras del método simplificado de viento en 7-22; factores de \(H\); límites de servicio de deriva y deflexión.
- **Responsable de cerrar**: responsable de normativa del proyecto, con copia licenciada de cada documento; la transcripción se cierra en `data/<jurisdiction>/<code_id>/*.json` con `source` y `verified_on`, y los skills `codes/...` verifican valor por valor.
