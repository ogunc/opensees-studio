---
name: fem-materials-and-sections
description: >-
  Define y calibra los modelos constitutivos y las propiedades de sección que
  sostienen cualquier análisis por elementos finitos sobre OpenSeesPy: elástico
  isótropo, acero Steel01/Steel02 con endurecimiento y efecto Bauschinger,
  concreto Concrete01/Concrete02 con confinamiento y tracción, modelos
  histeréticos, y las propiedades A, Iy, Iz, J, áreas de cortante, módulos
  plásticos, factores de forma, torsión de Saint-Venant y de alabeo, secciones
  de fibra (parches, capas de armadura, agregadores) y la biblioteca AISC con su
  conversión de unidades. Úsala al crear o calibrar un material, al definir o
  auditar una sección, al importar un perfil de biblioteca, al convertir
  unidades de geometría, o cuando un modelo da rigidez, período o resistencia
  irreales.
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [analysis, design, qa]
---

# Materiales y secciones para el análisis por elementos finitos

## Cuándo usar esta skill

- Se define o edita un material (`ElasticIsotropic`, `Steel01`, `Steel02`, `Concrete01`, `Concrete02`, `Hardening`, `Hysteretic`) y hay que fijar sus parámetros con criterio, no copiarlos de un ejemplo.
- Se define una sección elástica o de fibra, o hay que decidir cuántas fibras hacen falta para que `A`, `Iy` e `Iz` no estén sesgados.
- Se inserta un perfil de la biblioteca AISC y hay que convertir in², in⁴ e in⁶ al sistema del proyecto sin redondeos silenciosos.
- Un modelo da un período demasiado largo, rigidez torsional nula o capacidad a flexión menor que la esperada, y la causa está en la sección.
- Se audita el emisor de materiales o el cálculo de propiedades de sección antes de confiar en sus resultados.

**No usar** para la formulación de elementos ni la matriz de rigidez (→ `core/fem-formulation-core`), para combinaciones y coeficientes de código (→ `seismic/load-combinations-and-limit-states`), ni para el diálogo de selección de perfiles (→ `platform/gui-cad-workflow-and-ux`).

## Alcance y límites

Cubre: material elástico isótropo 3D; uniaxiales `Elastic`, `Steel01`, `Steel02`, `Concrete01`, `Concrete02`, `Concrete04`, `Hardening`, `ElasticPP`, `Hysteretic`; secciones elásticas, de fibra y agregadores; propiedades agregadas (\(A\), centroide, \(I_y\), \(I_z\), \(J\), \(C_w\), \(Z\), \(S\), \(A_s\), radios de giro); discretización por parches y capas; biblioteca de perfiles y reglas de conversión de unidades.

No cubre: plasticidad multi-axial (J2, Drucker-Prager), modelos de daño continuo, viscosidad, fisuración distribuida en elementos lámina, pandeo local, comportamiento de conexiones (→ `design/steel-aisc360-341`), dimensionamiento de armadura (→ `design/concrete-aci318`), ni el efecto del confinamiento sobre la capacidad del elemento — solo sobre el material.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Sistema de unidades coherente del proyecto | sí | bloquear: no se adivina |
| Materiales con \(E\), \(\nu\), \(\rho\) o su curva constitutiva | sí | bloquear |
| Geometría de la sección o nombre de perfil | sí | bloquear |
| Unidades de origen del perfil | sí si hay perfil | el perfil declara su sistema de publicación |
| Modelo constitutivo y su calibración | sí | proponer el más simple que represente el fenómeno y avisar |
| \(C_w\) o clase de torsión (Saint-Venant / alabeo) | en 3D con sección abierta | asumir Saint-Venant y emitir aviso |
| \(A_s\) (área de cortante efectiva) | si el cortante no es despreciable | usar la tabla de datos versionada y registrar el origen |

Los parámetros calibrables (no publicados por una norma) viven en `data/materials/*.json` y `data/sections/*.json` con los campos `source`, `edition` y `verified_on`.

## Fundamento y formulación

### 1. Material elástico isótropo

$$ \lambda = \frac{E\,\nu}{(1+\nu)(1-2\nu)}, \qquad G = \frac{E}{2(1+\nu)}, \qquad \boldsymbol{\sigma} = \lambda\,\mathrm{tr}(\boldsymbol{\varepsilon})\,\mathbf{I} + 2G\,\boldsymbol{\varepsilon} $$

\(E\) módulo de Young [Pa]; \(\nu\) coeficiente de Poisson [–]; \(\lambda\), \(G\) constantes de Lamé [Pa]. En 1D, \(\sigma = E\varepsilon\). \(G\) se **calcula**, nunca se introduce por separado: un \(G\) independiente hace inconsistente la matriz de rigidez con el \(E\) declarado.

### 2. Acero `Steel01` (bilineal cinemático)

$$ |\sigma - \alpha| \le \sigma_y, \qquad \sigma = \alpha + E_0\,\varepsilon^{e} $$

Tras la fluencia la pendiente es \(b\,E_0\), con \(b = E_t/E_0\) [–]; \(E_0\) [Pa] tangente inicial; \(\sigma_y = F_y\) [Pa] tensión de fluencia; \(\alpha\) [Pa] tensión retrógrada, que se traslada con la deformación plástica y produce el efecto Bauschinger: al invertir la carga la fluencia ocurre a \(\alpha - \sigma_y\), con \(|\alpha - \sigma_y| < \sigma_y\). El endurecimiento isótropo opcional (\(a_1 \dots a_4\)) **ensancha** la superficie en vez de trasladarla.

### 3. Acero `Steel02` (Giuffré-Menegotto-Pinto)

$$ \sigma^{*} = b\,\varepsilon^{*} + \frac{(1-b)\,\varepsilon^{*}}{\left(1 + |\varepsilon^{*}|^{R}\right)^{1/R}}, \qquad \sigma^{*} = \frac{\sigma-\sigma_r}{\sigma_0-\sigma_r}, \qquad \varepsilon^{*} = \frac{\varepsilon-\varepsilon_r}{\varepsilon_0-\varepsilon_r}, \qquad R(\xi) = R_0\left(1 - \frac{c_{R1}\,\xi}{c_{R2}+\xi}\right) $$

\((\varepsilon_r,\sigma_r)\) punto de inversión; \((\varepsilon_0,\sigma_0)\) intersección de la asíntota elástica con la plástica; \(b = E_t/E_0\) [–]; \(\xi\) deformación plástica acumulada normalizada [–]. \(R_0\) controla la curvatura de la transición (menor \(R_0\) → transición más redondeada y mayor efecto Bauschinger); \(c_{R1}\), \(c_{R2}\) degradan \(R\) con la carga cíclica. Valores por defecto de OpenSeesPy: \(R_0 = 18\), \(c_{R1} = 0.925\), \(c_{R2} = 0.15\) (`uniaxialMaterial Steel02`). Son puntos de partida, no constantes del material: cambian el bucle histerético sin cambiar \(F_y\) ni \(E_0\).

### 4. Concreto `Concrete01` / `Concrete02` (Kent-Scott-Park)

$$ f_c = f'_{c}\left[2\frac{\varepsilon}{\varepsilon_{c0}} - \left(\frac{\varepsilon}{\varepsilon_{c0}}\right)^{2}\right] \quad (0 \ge \varepsilon \ge \varepsilon_{c0}), \qquad E_0 = \frac{2 f'_{c}}{\varepsilon_{c0}} $$

Rama descendente lineal hasta \((\varepsilon_{cu}, f'_{cu})\) y meseta residual \(f'_{cu}\) después. \(f'_c < 0\) y \(\varepsilon_{c0} < 0\) [Pa] y [–]; la resistencia residual \(f'_{cu} \le 0\) [Pa] no es cero en hormigón confinado. `Concrete01` **no tiene tracción**: cualquier fibra traccionada aporta rigidez nula. `Concrete02` añade tracción lineal de pendiente \(E_0\) hasta \(f_t\) [Pa], reblandecimiento de pendiente \(E_{ts}\) [Pa] y descarga con pendiente \(\lambda E_0\), con \(\lambda \in [0,1]\) [–].

Confinamiento (Mander, Priestley y Park, 1988):

$$ f'_{cc} = f'_{c}\left(-1.254 + 2.254\sqrt{1 + 7.94\,\frac{f'_{l}}{f'_{c}}} - 2\,\frac{f'_{l}}{f'_{c}}\right), \qquad \varepsilon_{cc} = \varepsilon_{c0}\left[1 + 5\left(\frac{f'_{cc}}{f'_{c}} - 1\right)\right] $$

\(f'_l\) [Pa] presión lateral efectiva de confinamiento. \(f'_{cc}\) y \(\varepsilon_{cc}\) **sustituyen** a \(f'_c\) y \(\varepsilon_{c0}\) en el modelo uniaxial.

> ⚠️ VERIFICAR: la deformación última confinada \(\varepsilon_{cu}\) por balance de energía (Mander et al., 1988) no se reproduce aquí; se comprueba en el artículo original. El programa la lee de `data/materials/concrete_confinement.json`, no la calcula.

### 5. Modelos histeréticos y plasticidad combinada

`Hardening` combina endurecimiento isótropo y cinemático: \(\sigma_y(\xi) = \sigma_{y0} + H_{iso}\xi\) y \(\mathrm{d}\alpha = H_{kin}\,\mathrm{d}\varepsilon^{p}\), con pendiente monotónica post-fluencia \(E(H_{iso}+H_{kin})/(E+H_{iso}+H_{kin})\) [Pa]. `Hysteretic` es trilineal por envolvente (tres puntos positivos y tres negativos, estos últimos negativos) con pinzamiento \((p_x, p_y)\) y daño \((d_1, d_2)\) adimensionales; es el modelo de plasticidad concentrada para rótulas momento-rotación, y sus unidades son las del par momento-rotación, no tensión-deformación.

### 6. Propiedades de sección

$$ A = \int_A \mathrm{d}A, \qquad \bar{y} = \frac{1}{A}\int_A y\,\mathrm{d}A, \qquad I_z = \int_A (y-\bar{y})^{2}\,\mathrm{d}A, \qquad I_y = \int_A (z-\bar{z})^{2}\,\mathrm{d}A $$

Convención de ejes locales: \(x\) es el eje del elemento; **\(I_y\) se calcula con la coordenada \(z\)** e **\(I_z\) con la \(y\)**. Módulos elásticos \(S_y = I_y/z_{max}\), \(S_z = I_z/y_{max}\) [m³]; módulos plásticos \(Z_y\), \(Z_z\) [m³]; factor de forma \(S_f = Z/S \ge 1\) [–]: 1.5 en rectángulo, 1.698 en círculo, del orden de 1.10–1.15 en perfiles I. Radios de giro \(r = \sqrt{I/A}\) [m]. Área de cortante efectiva \(A_s = kA\) con \(k\) [–]: \(k = 5/6\) en rectángulo (Timoshenko y Goodier); para el perfil I la práctica usa el área del alma, \(A_s = h_w t_w\).

> ⚠️ VERIFICAR: el factor de corrección por cortante depende de la definición adoptada (tensión media en la sección frente a tensión en el eje) y de \(\nu\); las expresiones de Cowper (1966) dan, para \(\nu = 0.3\), valores distintos de 5/6 y 0.9. Se comprueba en Cowper (1966). El programa lee \(k\) de `data/sections/shear_factors.json` con su cita.

### 7. Torsión de Saint-Venant y de alabeo

| Sección | \(J\) [m⁴] |
|---|---|
| Círculo lleno, diámetro \(d\) | \(\pi d^{4}/32\) |
| Tubo cerrado de pared delgada | \(4A_m^{2}\big/\oint (\mathrm{d}s/t)\) |
| Sección abierta de pared delgada, tramos \(b_i\), \(t_i\) | \(\tfrac{1}{3}\sum b_i t_i^{3}\) |
| Rectángulo \(a \times b\), \(a \ge b\) | \(\tfrac{1}{3}ab^{3}\left[1 - 0.63\tfrac{b}{a}\left(1 - \tfrac{b^{4}}{12a^{4}}\right)\right]\) |

\(A_m\) área encerrada por la línea media [m²]; \(s\) coordenada a lo largo de ella [m]; \(t\) espesor [m]. La fórmula de sección abierta **desprecia el alabeo** y solo vale si la longitud libre es mucho mayor que el desarrollo de la pared.

Rigidez de alabeo \(EC_w\) [N·m⁴], con \(C_w = I_\omega\) [m⁶]. En una doble T simétrica, \(C_w = I_f h_o^{2}/4\), con \(I_f = t_f b_f^{3}/12\) [m⁴] el momento de inercia del ala sobre el eje del alma y \(h_o\) [m] la distancia entre centros de gravedad de las alas. Bimomento \(B = -E C_w \varphi''\) [N·m²]; tensión normal de alabeo proporcional a \(E\,\omega\,\varphi''\), con \(\omega\) [m²] el área sectorial.

### 8. Secciones de fibra

$$ A = \sum_i a_i, \qquad I_z = \sum_i a_i (y_i-\bar{y})^{2}, \qquad I_y = \sum_i a_i (z_i-\bar{z})^{2} $$

Cada fibra aporta \(a_i = \Delta y\,\Delta z\) [m²] en su centroide. Regla del punto medio con \(n\) franjas iguales en la dirección de flexión: el momento de inercia calculado es \((1 - 1/n^{2})\) del exacto, es decir **siempre menor**; el área y el centroide son exactos. La rigidez torsional \(J\) **no** sale de las fibras: en 3D hay que declararla (`-torsion`) o aportarla con un `SectionAggregator`. Los elementos viga-columna estándar no tienen grado de libertad de alabeo, así que \(C_w\) no interviene en el análisis salvo que el elemento lo soporte.

## Procedimiento

1. Fijar el sistema de unidades del proyecto y registrar el sistema de origen de cada dato importado.
2. Elegir el modelo constitutivo mínimo que reproduce el fenómeno: cuasiestático → elástico o `Steel01`; cíclico → `Steel02` o `Concrete02`; rótula concentrada → `Hysteretic`.
3. Calibrar \(E\), \(F_y\) o \(f'_c\), \(b\) y los parámetros de forma del bucle. Si hay confinamiento, calcular \(f'_{cc}\) y \(\varepsilon_{cc}\) con la sección 4 y leer \(\varepsilon_{cu}\) y \(\lambda\) del archivo de datos.
4. Verificar el material contra su ensayo uniaxial monotónico y cíclico antes de usarlo en un modelo.
5. Calcular o importar la geometría; convertir unidades con el exponente de longitud correcto y mostrar el valor publicado y el convertido.
6. Elegir el tipo de sección: elástica (homogénea), de fibra (no lineal) o agregador (fibra más rigideces adicionales).
7. Discretizar: parches para el hormigón, capas o fibras explícitas para la armadura; refinar hasta que la propiedad de interés converja.
8. Comparar \(A\), \(\bar{y}\), \(I_y\), \(I_z\) de la fibra contra la solución analítica o el perfil equivalente y documentar la diferencia.
9. Aportar \(J\) (y \(A_s\) si el cortante no es despreciable) de forma explícita.
10. Emitir material y sección con su trazabilidad y registrar en el resultado qué modelo, qué parámetros y qué discretización se usaron.

## Implementación en la plataforma

```python
# Existentes: core/materials/__init__.py (ElasticIsotropic, Steel01, Steel02,
# Concrete01, Concrete02, Concrete04, Hardening, Hysteretic) y
# core/sections/__init__.py (ElasticSection, FiberSection, RectangularPatch,
# CircularPatch, StraightLayer, Fibre, SectionAggregator, w_shape_patches).

# core/sections/properties.py  (nuevo; puro: sin Qt, sin OpenSeesPy, solo NumPy)
def section_properties(sec: Section) -> SectionProperties:
    """A, centroide, Iy, Iz, radios de giro. ValueError si A <= 0."""

def torsion_and_warping(shape: SectionShape) -> tuple[float, float | None]:
    """J [m^4] y C_w [m^6]; C_w = None si la forma no lo define."""

def plastic_moduli(shape: SectionShape) -> tuple[float, float]:
    """Zy, Zz [m^3] y factor de forma; exige forma cerrada conocida."""

def shear_areas(shape: SectionShape, nu: float, data: ShearFactorData) -> tuple[float, float]:
    """As_y, As_z [m^2]; k se lee de data/sections/shear_factors.json."""

def fibre_convergence(sec: FiberSection, ref: SectionProperties) -> float:
    """Error relativo de Iy/Iz frente a la referencia analitica."""

# core/materials/calibration.py  (nuevo; puro)
def confined_core(fc: float, f_l: float, eps_c0: float) -> tuple[float, float]:
    """f'cc [Pa] y eps_cc [-] segun Mander; eps_cu se lee del archivo de datos."""

# core/aisc.py: shape_to_elastic_section(name, target_units) ya aplica L^2 y L^4.
# services/material_emitters.py: emit_material(material, ops), unico punto que
#     traduce un modelo de core/ a comandos de OpenSeesPy.
# services/material_tester.py: ensayo monotono/ciclico del material emitido.
# services/section_properties.py: adaptador de GUI; delega la aritmetica en
#     core/sections/properties.py y solo anade presentacion.
```

Reglas de arquitectura (`platform/platform-architecture-and-services`):

- Todo el cálculo de propiedades y la calibración viven en `core/`: **sin Qt y sin OpenSeesPy**; utilizables desde un notebook o un script.
- El solver se toca **solo** desde `services/`; `services/material_emitters.py` es el único módulo que conoce los nombres de los comandos de OpenSees.
- Las bibliotecas de perfiles aportan **geometría**; \(E\), \(\nu\) y \(\rho\) son decisión del usuario y no viajan con el perfil.
- Ninguna conversión de unidades es implícita: la función recibe el sistema de origen y el de destino y devuelve ambos valores.

## Datos normativos

No aplica como tabla normativa: esta skill no reproduce coeficientes de código (\(R\), \(C_d\), \(\phi\), límites de deriva). Sus parámetros son de material o de forma y se rigen por la procedencia siguiente.

| Dato | Origen | ¿Verificado? |
|---|---|---|
| \(E_0 = 2f'_c/\varepsilon_{c0}\) en `Concrete01`/`Concrete02` | OpenSeesPy 3.8.0.0, `uniaxialMaterial Concrete01` | sí |
| Por defecto \(R_0 = 18\), \(c_{R1} = 0.925\), \(c_{R2} = 0.15\) | OpenSeesPy 3.8.0.0, `Steel02` | sí |
| \(f'_{cc}\), \(\varepsilon_{cc}\) de Mander | Mander, Priestley y Park (1988), ec. 5 y 8 | sí |
| \(\varepsilon_{cu}\) confinada | Mander et al. (1988), balance de energía | no — `VERIFICAR` |
| \(k\) de cortante (\(5/6\), \(0.9\)) | Timoshenko y Goodier; Cowper (1966) | no — `VERIFICAR` |
| \(J\) de rectángulo (aprox. de tres términos) | Timoshenko y Goodier, tabla de torsión | sí, 1 % frente a la serie |
| \(C_w = I_f h_o^{2}/4\) (doble T simétrica) | Timoshenko; Blodgett | sí |
| Geometría y propiedades AISC (`data/aisc_v16.csv`) | AISC Shapes Database v16.0, vía steelpy 1.1.1 | sí — `tests/unit/test_aisc.py` |
| Factores \(L^{2}\), \(L^{3}\), \(L^{4}\), \(L^{6}\) de conversión | definición de unidad, no norma | sí |

> ⚠️ VERIFICAR: los valores publicados de \(\varepsilon_{cu}\) confinada y del factor \(k\) de cortante se comprueban contra las fuentes citadas en `data/materials/concrete_confinement.json` y `data/sections/shear_factors.json`. Mientras no estén cerrados, el programa **lee el valor del archivo** y lo etiqueta como no verificado en el informe.

## Verificación y casos de prueba

| Caso | Entrada | Esperado | Tolerancia |
|---|---|---|---|
| Rectángulo \(b=0.30\), \(h=0.50\) m | \(A = bh\), \(I_z = hb^{3}/12\) | \(A = 0.150000\) m², \(I_z = 1.1250\times10^{-3}\) m⁴ | 1e-12 rel. |
| Módulo plástico rectángulo | \(Z_z = hb^{2}/4\), \(S_z = I_z/(b/2)\) | \(Z_z = 1.1250\times10^{-2}\) m³, \(Z/S = 1.5\) | 1e-12 rel. |
| Círculo \(d = 0.40\) m | \(\pi d^{4}/64\), \(\pi d^{4}/32\), \(d^{3}/6\) | \(I = 1.256637\times10^{-3}\) m⁴, \(J = 2.513274\times10^{-3}\) m⁴, \(Z = 1.066667\times10^{-2}\) m³ | 1e-9 rel. |
| Fibra, \(n_y = n_z = 10\) | parche rectangular | \(I_z^{fem}/I_z^{exacto} = 1 - 1/n^{2} = 0.990000\) | 1e-12 rel. |
| Fibra, \(n_y = 20\) | ídem | \(0.997500\) | 1e-12 rel. |
| `Steel01` monotónico | \(F_y = 420\) MPa, \(E_0 = 200\) GPa, \(b = 0.02\), \(\varepsilon = 0.01\) | \(\sigma = 451.60\) MPa | 0.1 % rel. |
| `Steel02` asíntota | \(b = 0.02\), \(\varepsilon^{*} \to 10^{3}\) | pendiente \(\to bE_0 = 4.0\) GPa | 0.5 % rel. |
| `Steel02` descarga | \(\sigma = 0\) tras incursión plástica | pendiente \(E_0 = 200\) GPa | 0.5 % rel. |
| `Concrete01` parábola | \(f'_c = -30\) MPa, \(\varepsilon_{c0} = -0.002\) | \(E_0 = 30.0\) GPa; \(f_c(\varepsilon_{c0}/2) = -22.50\) MPa | 1e-9 rel. |
| `Concrete02` tracción | \(f_t = 3\) MPa, \(E_0 = 30\) GPa, \(\varepsilon = 1\times10^{-4}\) | \(\sigma = 3.000\) MPa | 1e-6 rel. |
| Confinamiento Mander | \(f'_c = 30\) MPa, \(f'_l = 2\) MPa | \(f'_{cc} = 42.003\) MPa, \(\varepsilon_{cc}/\varepsilon_{c0} = 3.0005\) | 0.1 % rel. |
| \(J\) rectángulo \(0.20\times0.10\) m | fórmula de tres términos vs. serie \(k = 0.229\) | \(J \approx 4.58\times10^{-5}\) m⁴ | 1 % rel. |
| Conversión de unidades | \(A = 26.5\) in², \(I = 999\) in⁴ | \(1.709674\times10^{-2}\) m², \(4.158152\times10^{-4}\) m⁴ | 1e-12 rel. |
| Agregador | fibra 3D con `T` y \(GJ\) explícito | \(K_{T} = GJ/L\), resto de la diagonal sin cambios | 1e-9 rel. |

Contraste obligatorio: comparar \(A\), \(I_y\), \(I_z\) de una sección de fibra contra la solución analítica de la misma geometría y contra el perfil equivalente del `aisc_v16.csv` cuando exista.

## Errores frecuentes y trampas

1. **Convertir inercia con \(L\) en vez de \(L^{4}\)** (y \(C_w\) con \(L^{4}\) en vez de \(L^{6}\)): un perfil AISC en un modelo SI queda con rigidez equivocada por un factor de \(6.45\times10^{4}\).
2. **Intercambiar \(I_y\) e \(I_z\)**: \(I_y\) usa \(z\) e \(I_z\) usa \(y\); el resultado es una sección girada 90° que parece razonable.
3. **Suponer rigidez torsional de la sección de fibra.** Las fibras no dan \(J\): sin `-torsion` o sin agregador la torsión queda nula y el análisis modal pierde modos torsionales.
4. **Aplicar la fórmula de sección abierta a un caso con alabeo restringido**, o Saint-Venant a una sección de pared gruesa o de longitud corta.
5. **Tratar \(R_0\), \(c_{R1}\), \(c_{R2}\) como propiedades del acero**: cambian el bucle histerético y el amortiguamiento histerético, no \(F_y\).
6. **Introducir \(G\) separado de \(E\) y \(\nu\).** Debe ser siempre \(G = E/[2(1+\nu)]\).
7. **Dar \(f'_c\) o \(\varepsilon_{c0}\) positivos** a `Concrete01`/`Concrete02`: el hormigón queda sin resistencia a compresión y el modelo carga de más sin avisar.
8. **Confundir \(\lambda\) de `Concrete02`** (pendiente de descarga; 1.0 = sin degradación) con un índice de daño acumulado.
9. **Calibrar `Concrete01` con un \(E_0\) distinto de \(2f'_c/\varepsilon_{c0}\)**: el modelo ignora el \(E_0\) declarado y la rigidez inicial real no es la que el usuario escribió.
10. **Elegir \(n\) de fibras por costumbre.** El punto medio subestima \(I\) en \(1/n^{2}\): 1 % con \(n=10\), 6.25 % con \(n=4\); el período sale largo y las fuerzas sísmicas mal estimadas.
11. **Poner toda la armadura en una fibra en el centroide** o en una sola fila: se pierde el brazo interno y cae la capacidad a flexión.
12. **Confundir `bar_area` (área por barra) con el área total de la capa** en una `StraightLayer`.
13. **Mezclar \(S\) y \(Z\)** en una comprobación demanda/capacidad: módulo plástico con tensión admisible elástica es doble conteo.
14. **Redondear la geometría convertida antes de usarla**, en vez de conservar el valor completo y redondear solo al mostrar.

## Interfaz de salida

Para cada material: tipo, parámetros con unidad, fuente de la calibración, `verified_on` y si algún valor proviene de un `VERIFICAR`.

Para cada sección: \(A\) [m²], \(\bar{y}\), \(\bar{z}\) [m], \(I_y\), \(I_z\), \(J\), \(C_w\) [m⁴ y m⁶], \(Z_y\), \(Z_z\), \(S_y\), \(S_z\) [m³], \(A_{sy}\), \(A_{sz}\) [m²], \(r_y\), \(r_z\) [m], masa por unidad de longitud [kg/m]; y, si viene de biblioteca, el valor **publicado** y el **convertido** con el sistema de origen declarado.

Para una sección de fibra: número de fibras por parche y capa, propiedades agregadas, referencia analítica y error relativo de \(I_y\), \(I_z\), con aviso cuando supere el 1 %. Para un agregador: qué grado de libertad cubre un material uniaxial y cuál la sección base. Todo informe hereda las advertencias de datos no verificados.

## Referencias

1. OpenSeesPy 3.8.0.0 — documentación de `uniaxialMaterial` (`Elastic`, `Steel01`, `Steel02`, `Concrete01`, `Concrete02`, `Concrete04`, `Hardening`, `ElasticPP`, `Hysteretic`) y de `section Fiber`, `patch`, `layer`, `Aggregator`.
2. M. Menegotto y P. E. Pinto, *Method of Analysis for Cyclically Loaded Reinforced Concrete Plane Frames*, IABSE Symposium, 1973.
3. F. C. Filippou, E. P. Popov y V. V. Bertero, *Effects of Bond Deterioration on Hysteretic Behavior of Reinforced Concrete Joints*, EERC Report 83/19, 1983.
4. J. B. Mander, M. J. N. Priestley y R. Park, *Theoretical Stress-Strain Model for Confined Concrete*, Journal of Structural Engineering ASCE 114(8), 1988.
5. D. C. Kent y R. Park, *Flexural Members with Confined Concrete*, Journal of the Structural Division ASCE, 1971; B. D. Scott, R. Park y M. J. N. Priestley, ACI Journal, 1982.
6. S. P. Timoshenko y J. N. Goodier, *Theory of Elasticity*, 3.ª ed., McGraw-Hill.
7. G. R. Cowper, *The Shear Coefficient in Timoshenko's Beam Theory*, Journal of Applied Mechanics 33(2), 1966.
8. AISC, *Shapes Database v16.0* y *Steel Construction Manual*, 16.ª ed.
9. O. W. Blodgett, *Design of Welded Structures*, James F. Lincoln Arc Welding Foundation — constantes de alabeo.
10. `src/opensees_studio/data/README.md` — procedencia, licencia y regeneración de `aisc_v16.csv`; `tests/unit/test_aisc.py` — consistencia de la tabla.
11. `docs/architecture.md` y `CLAUDE.md` — dirección de dependencias y reglas del repositorio.

## Registro de verificación

- **Verificado**: las relaciones \(G = E/[2(1+\nu)]\) y \(\lambda\); la forma de Menegotto-Pinto, \(R(\xi)\) y los valores por defecto de OpenSeesPy; las ramas de Kent-Scott-Park y \(E_0 = 2f'_c/\varepsilon_{c0}\); \(f'_{cc}\) y \(\varepsilon_{cc}\) de Mander; las fórmulas de \(A\), \(I_y\), \(I_z\), \(J\) de círculo, rectángulo, tubo cerrado y sección abierta; \(C_w = I_f h_o^{2}/4\); la ley de error \(1/n^{2}\) de la regla del punto medio; los factores de conversión \(L^{2}\), \(L^{4}\) y \(L^{6}\); el contrato de los módulos citados del repositorio.
- **Pendiente**: transcribir \(\varepsilon_{cu}\) confinada desde Mander et al. (1988) y fijar la tabla de factores \(k\) de cortante con su definición; cerrar `data/materials/concrete_confinement.json` y `data/sections/shear_factors.json`; decidir si la aritmética de `services/section_properties.py` se traslada a `core/sections/properties.py`.
- **Responsable de cerrar**: responsable de análisis del proyecto, con copia del artículo de Mander y del de Cowper.
