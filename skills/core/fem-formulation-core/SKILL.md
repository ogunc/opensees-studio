---
name: fem-formulation-core
description: >-
  Formulación e implementación de los elementos finitos estructurales del núcleo:
  barra/armadura 3D, viga-columna de Euler-Bernoulli y Timoshenko con matriz local
  12x12, transformación a ejes locales, rigidez geométrica, quad de 4 nodos de
  tensión plana y de placa, y sólidos. Cubre ensamblaje, numeración de GDL,
  condiciones de borde, diafragma rígido, restricciones multipunto (penalización
  frente a transformación), liberaciones de extremo y condensación estática. Úsala
  al escribir o auditar el ensamblador y la biblioteca de elementos, ante avisos de
  matriz singular o modos de cuerpo rígido espurios, al depurar la orientación de
  los ejes locales, al implementar diafragmas y MPC, y al montar las verificaciones
  analíticas (PL^3/3EI, 5wL^4/384EI, patch test, equilibrio de reacciones).
metadata:
  track: core
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [analysis, qa]
---

# Elementos finitos: formulación del núcleo de cálculo

## Cuándo usar esta skill
- Se implementa o audita el ensamblador de rigidez, la biblioteca de elementos o el mapa de GDL de `core/`.
- El solver avisa de matriz singular, pivote nulo o un número inesperado de modos de cuerpo rígido.
- Hay que decidir cómo imponer un diafragma rígido, un `equalDOF`, una liberación de extremo o una MPC.
- Los desplazamientos no tienen sentido físico: reacciones que no cierran, voladizo que se dobla en el plano equivocado, placa excesivamente rígida.
- Hay que construir la tabla de verificación analítica de un elemento nuevo antes de conectarlo al solver.

**No usar** para: procedimientos de solución y convergencia (→ `core/analysis-procedures-and-solution`); plasticidad, fibras y no linealidad (→ `core/material-and-section-nonlinearity`); requisitos normativos de diseño (→ track `codes/`); arquitectura de capas (→ `platform/platform-architecture-and-services`).

## Alcance y límites
Cubre la formulación lineal y la geometría de barra/armadura 3D, viga-columna de Euler-Bernoulli y de Timoshenko, rigidez geométrica de segundo orden, quad isoparamétrico de 4 nodos en tensión plana y en placa, y hexaedro de 8 nodos. Cubre ensamblaje, numeración de GDL, condiciones de borde, diafragma rígido, MPC, liberaciones de extremo y condensación estática.
**Fuera de alcance**: láminas avanzadas (MITC4, EAS, DKT), formulaciones *corotational* con grandes desplazamientos, contacto, y todo lo que dependa del integrador temporal. Tampoco cubre la elección del solver ni el almacenamiento de resultados. Supuestos: pequeñas deformaciones, material elástico lineal isótropo, secciones prismáticas y ejes principales de inercia alineados con los ejes locales.

## Entradas y supuestos
| Dato | Obligatorio | Si falta |
|---|---|---|
| Coordenadas nodales \((X,Y,Z)\), m | sí | bloquear: no hay geometría |
| Incidencia nodo–elemento y tipo de elemento | sí | bloquear |
| \(E\), \(G\) (Pa) y \(\nu\) (–) | sí | bloquear; no hay valores por defecto |
| \(A\) (m²), \(I_y, I_z, J\) (m⁴) | sí en pórticos | bloquear el elemento, no el modelo |
| Espesor \(t\) (m) y comportamiento (tensión/deformación plana) | sí en quad | bloquear el elemento |
| Vector de orientación local \(\mathbf{v}_{xz}\) | sí en 3D | derivarlo del triedro global y **avisar** de la ambigüedad |
| GDL y valor de cada apoyo | sí | bloquear |
| Nodos del diafragma y nodo maestro | sí | diafragma inactivo, con aviso |
| \(A_s\) o \(k_s\) en Timoshenko | Timoshenko | leer del archivo de sección; si no existe, avisar |

Las unidades internas son SI coherente (m, N, kg, s, Pa, rad) y ninguna rutina del núcleo convierte unidades: la conversión ocurre en la lectura del proyecto.

## Fundamento y formulación
### 1. Ejes locales y convención de GDL
Para un elemento de dos nodos con \(\mathbf{X}_i,\mathbf{X}_j\) (m) y \(L=\lVert\mathbf{X}_j-\mathbf{X}_i\rVert\) (m):
$$\hat{\mathbf{x}}=\frac{\mathbf{X}_j-\mathbf{X}_i}{L},\qquad \hat{\mathbf{z}}=\frac{\hat{\mathbf{x}}\times\mathbf{v}_{xz}}{\lVert\hat{\mathbf{x}}\times\mathbf{v}_{xz}\rVert},\qquad \hat{\mathbf{y}}=\hat{\mathbf{z}}\times\hat{\mathbf{x}}$$
con \(\mathbf{v}_{xz}\) (adimensional) el vector de referencia que fija el plano local \(x\)–\(z\). El orden de GDL por nodo es \(u_x,u_y,u_z,\theta_x,\theta_y,\theta_z\) (m y rad), positivos según la regla de la mano derecha. Con \(\boldsymbol{\Lambda}=[\hat{\mathbf{x}}^\top;\hat{\mathbf{y}}^\top;\hat{\mathbf{z}}^\top]\): \(\mathbf{T}=\mathrm{diag}(\boldsymbol{\Lambda},\boldsymbol{\Lambda},\boldsymbol{\Lambda},\boldsymbol{\Lambda})\) y \(\mathbf{k}_g=\mathbf{T}^\top\mathbf{k}_l\mathbf{T}\).

> ⚠️ VERIFICAR: el signo exacto de \(\hat{\mathbf{z}}\) respecto de `vecxz` (\(\hat{\mathbf{x}}\times\mathbf{v}_{xz}\) frente a \(\mathbf{v}_{xz}\times\hat{\mathbf{x}}\)) cambia la orientación de la sección y el signo de los momentos locales. Se comprueba en la documentación y el código fuente de la versión fijada de OpenSeesPy, y con el caso «voladizo con \(I_y\ne I_z\) cargado en dos planos» de la tabla de verificación. Hasta entonces el trieje local se dibuja en la GUI y se contrasta a mano.

### 2. Barra/armadura 3D
Solo rigidez axial; las direcciones transversales no aportan. Con \(E\) en Pa, \(A\) en m² y \(L\) en m:
$$\mathbf{k}_l=\frac{EA}{L}\begin{bmatrix}1&0&0&-1&0&0\\0&0&0&0&0&0\\0&0&0&0&0&0\\-1&0&0&1&0&0\\0&0&0&0&0&0\\0&0&0&0&0&0\end{bmatrix}\quad(u_x^i,u_y^i,u_z^i,u_x^j,u_y^j,u_z^j)$$
La matriz es singular por construcción: el elemento solo existe dentro de una malla arriostrada.

### 3. Viga-columna 3D: matriz local 12×12 (Euler-Bernoulli)
Bloques en el orden \(\{u,v,w,\theta_x,\theta_y,\theta_z\}\) de cada nodo, con \(\mathbf{k}_{ji}=\mathbf{k}_{ij}^\top\) y \(E,G\) en Pa, \(A\) en m², \(I_y,I_z,J\) en m⁴, \(L\) en m:
$$\mathbf{k}_{ii}=\begin{bmatrix}\frac{EA}{L}&0&0&0&0&0\\0&\frac{12EI_z}{L^3}&0&0&0&\frac{6EI_z}{L^2}\\0&0&\frac{12EI_y}{L^3}&0&-\frac{6EI_y}{L^2}&0\\0&0&0&\frac{GJ}{L}&0&0\\0&0&-\frac{6EI_y}{L^2}&0&\frac{4EI_y}{L}&0\\0&\frac{6EI_z}{L^2}&0&0&0&\frac{4EI_z}{L}\end{bmatrix},\qquad \mathbf{k}_{jj}=\begin{bmatrix}\frac{EA}{L}&0&0&0&0&0\\0&\frac{12EI_z}{L^3}&0&0&0&-\frac{6EI_z}{L^2}\\0&0&\frac{12EI_y}{L^3}&0&\frac{6EI_y}{L^2}&0\\0&0&0&\frac{GJ}{L}&0&0\\0&0&\frac{6EI_y}{L^2}&0&\frac{4EI_y}{L}&0\\0&-\frac{6EI_z}{L^2}&0&0&0&\frac{4EI_z}{L}\end{bmatrix}$$
$$\mathbf{k}_{ij}=\begin{bmatrix}-\frac{EA}{L}&0&0&0&0&0\\0&-\frac{12EI_z}{L^3}&0&0&0&\frac{6EI_z}{L^2}\\0&0&-\frac{12EI_y}{L^3}&0&-\frac{6EI_y}{L^2}&0\\0&0&0&-\frac{GJ}{L}&0&0\\0&0&\frac{6EI_y}{L^2}&0&\frac{2EI_y}{L}&0\\0&-\frac{6EI_z}{L^2}&0&0&0&\frac{2EI_z}{L}\end{bmatrix}$$
Los términos \(\theta\)–\(v\) llevan signo \(+\) y los \(\theta\)–\(w\), signo \(-\), porque \(\theta_z=\mathrm{d}v/\mathrm{d}x\) y \(\theta_y=-\mathrm{d}w/\mathrm{d}x\). La matriz es simétrica y el elemento libre tiene seis autovalores nulos (seis movimientos de cuerpo rígido). Fuerzas nodales equivalentes de una carga transversal uniforme \(w\) (N/m) positiva hacia \(+\hat{\mathbf{y}}\): \(\mathbf{f}_l=[0,\frac{wL}{2},0,0,0,\frac{wL^2}{12},\,0,\frac{wL}{2},0,0,0,-\frac{wL^2}{12}]^\top\).

### 4. Viga-columna de Timoshenko
Con \(A_s=k_sA\) (m²) y \(k_s\) adimensional: \(\phi=\frac{12EI}{GA_sL^2}\). La rigidez de flexión del plano gobernado por \(I\) pasa a \(\frac{EI}{L^3(1+\phi)}\) multiplicando:
$$\begin{bmatrix}12&6L&-12&6L\\6L&(4+\phi)L^2&-6L&(2-\phi)L^2\\-12&-6L&12&-6L\\6L&(2-\phi)L^2&-6L&(4+\phi)L^2\end{bmatrix}\quad(v_i,\theta_i,v_j,\theta_j)$$
El cortante de extremo es \(V=\frac{12EI}{L^3(1+\phi)}\delta+\frac{6EI}{L^2(1+\phi)}\theta\), de modo que el voladizo con carga puntual da \(\delta=\frac{PL^3}{3EI}+\frac{PL}{GA_s}\). Con \(k_s=5/6\) la formulación coincide con la viga de Timoshenko clásica.

> ⚠️ VERIFICAR: \(k_s\) para secciones no rectangulares (círculo, tubo, perfil I) sale de una tabla; no se interpola ni se inventa. Se comprueba en la bibliografía de cortante efectivo (Timoshenko, *Strength of Materials*) y en la definición de propiedades de sección del programa. Debe vivir en `data/fem/shear-factors.json` con campo `source` (referencia, edición, tabla) y prueba unitaria por fila. La forma cerrada \(k_s=5/6\) de la sección rectangular maciza sí se usa directamente.

### 5. Matriz de rigidez geométrica
Con \(P\) (N) el axil **positivo en tracción** y los GDL de flexión \((v_i,\theta_i,v_j,\theta_j)\):
$$\mathbf{k}_g=\frac{P}{30L}\begin{bmatrix}36&3L&-36&3L\\3L&4L^2&-3L&-L^2\\-36&-3L&36&-3L\\3L&-L^2&-3L&4L^2\end{bmatrix}$$
El axil no aporta rigidez geométrica propia. La inestabilidad se detecta cuando \(\mathbf{K}+\mathbf{K}_g\) deja de ser definida positiva; \(P\) debe proceder del **mismo** caso de carga cuya estabilidad se evalúa.

### 6. Quad de 4 nodos: tensión plana y placa
Elemento isoparamétrico bilineal con \((\xi,\eta)\in[-1,1]^2\) y \(t\) (m) constante:
$$\mathbf{x}=\sum_{a=1}^{4}N_a\mathbf{x}_a,\qquad \mathbf{J}=\frac{\partial(x,y)}{\partial(\xi,\eta)},\qquad \mathbf{k}=\int_{-1}^{1}\!\!\int_{-1}^{1}\mathbf{B}^\top\mathbf{D}\mathbf{B}\,t\lvert\mathbf{J}\rvert\,\mathrm{d}\xi\,\mathrm{d}\eta$$
En tensión plana, con \(E\) en Pa y \(\nu\) adimensional, \(\boldsymbol{\sigma}=[\sigma_{xx},\sigma_{yy},\tau_{xy}]^\top\):
$$\mathbf{D}=\frac{E}{1-\nu^2}\begin{bmatrix}1&\nu&0\\\nu&1&0\\0&0&\frac{1-\nu}{2}\end{bmatrix}$$
En placa de Reissner-Mindlin hay 3 GDL por nodo \((w,\theta_x,\theta_y)\) y hace falta integración reducida selectiva del cortante (2×2 en flexión, 1×1 en cortante) para no bloquearse. Una lámina plana combina tensión plana y placa más un GDL de talón (*drilling*).

> ⚠️ VERIFICAR: la rigidez ficticia del GDL de talón no tiene un valor de bibliografía único. Se comprueba en el código fuente del elemento de lámina de la versión fijada de OpenSeesPy y en la documentación de `ShellMITC4`/`ShellDKGQ`. Debe leerse de `data/fem/shell-drilling.json` con `source` y `verified_on`, nunca escribirse en la lógica del ensamblador.

### 7. Sólidos
Hexaedro de 8 nodos, 3 traslaciones por nodo (24 GDL), Gauss 2×2×2, \(\mathbf{k}=\int\mathbf{B}^\top\mathbf{D}\mathbf{B}\lvert\mathbf{J}\rvert\mathrm{d}V\) con \(\mathbf{D}\) isótropo 3D. Con \(\nu\to0.5\) aparece bloqueo volumétrico y con integración reducida 1×1×1, modos de *hourglass*. El tetraedro de 4 nodos es de deformación constante y resulta excesivamente rígido en mallas gruesas.

### 8. Ensamblaje, numeración de GDL y condensación
Con \(\mathbf{A}_e\) la matriz booleana de GDL locales a globales: \(\mathbf{K}=\sum_e\mathbf{A}_e^\top\mathbf{k}_{g,e}\mathbf{A}_e\) y \(\mathbf{f}=\sum_e\mathbf{A}_e^\top\mathbf{f}_{g,e}\). La numeración asigna un índice a cada par (nodo, GDL) y separa libres de restringidos; un reordenamiento por reverso de Cuthill-McKee reduce el ancho de banda. Condensación estática de los GDL internos o liberados (\(c\)) respecto de los retenidos (\(r\)):
$$\mathbf{K}^{*}=\mathbf{K}_{rr}-\mathbf{K}_{rc}\mathbf{K}_{cc}^{-1}\mathbf{K}_{cr},\qquad \mathbf{f}^{*}=\mathbf{f}_{r}-\mathbf{K}_{rc}\mathbf{K}_{cc}^{-1}\mathbf{f}_{c}$$
Una liberación de extremo es exactamente esto: el GDL liberado se declara interno y se condensa con fuerza nula. La condensación se aplica **antes** del ensamblaje y por igual a rigidez elástica, geométrica, masa y vector de cargas.

### 9. Condiciones de borde, diafragma rígido y MPC
Apoyo puntual: se elimina la ecuación o se impone el valor prescrito reduciendo el RHS, \(\mathbf{f}\leftarrow\mathbf{f}-\mathbf{K}_{:,c}u_c\), antes de anular fila y columna. Diafragma rígido horizontal con maestro \(m\) y esclavo \(s\) (las traslaciones verticales y las rotaciones de los esclavos quedan libres):
$$\begin{bmatrix}u_x^{s}\\u_y^{s}\end{bmatrix}=\begin{bmatrix}1&0&-(y_s-y_m)\\0&1&(x_s-x_m)\end{bmatrix}\begin{bmatrix}u_x^{m}\\u_y^{m}\\\theta_z^{m}\end{bmatrix}$$
Con \(\mathbf{C}\mathbf{u}=\mathbf{0}\), la transformación \(\mathbf{u}=\mathbf{T}\tilde{\mathbf{u}}\) da \(\tilde{\mathbf{K}}=\mathbf{T}^\top\mathbf{K}\mathbf{T}\) y \(\tilde{\mathbf{f}}=\mathbf{T}^\top\mathbf{f}\), mientras que la penalización añade \(\mathbf{K}\leftarrow\mathbf{K}+\alpha\mathbf{C}^\top\mathbf{C}\). La transformación es exacta pero exige restricciones acíclicas y consistentes (un esclavo no puede ser maestro de otro); la penalización admite ciclos a cambio de un residuo \(\lVert\mathbf{C}\mathbf{u}\rVert=O(\lVert\mathbf{f}\rVert/\alpha)\) y de degradar el número de condición en \(O(\alpha/\lVert K\rVert)\). Un \(\alpha\) único mezcla unidades de traslación (N/m) y de rotación (N·m/rad): hay que ponderar cada ecuación por la escala de su fila.

> ⚠️ VERIFICAR: el factor de penalización por defecto del `ConstraintHandler Penalty` de OpenSeesPy no se transcribe aquí. Se comprueba en la documentación y el código fuente de la versión fijada (3.8.0.0) y se guarda en `data/fem/constraint-defaults.json` con `source`. Regla: el núcleo nunca usa el valor implícito del solver, lo pasa explícito.

## Procedimiento
1. Validar geometría: \(L>0\), \(\lvert\mathbf{J}\rvert>0\) en todos los puntos de Gauss, \(\lVert\hat{\mathbf{x}}\times\mathbf{v}_{xz}\rVert>\varepsilon\), sin nodos coincidentes.
2. Calcular propiedades de sección y áreas efectivas (\(A_s=k_sA\)); abortar si falta una propiedad requerida por el tipo de elemento.
3. Construir \(\boldsymbol{\Lambda}\), \(\mathbf{T}\) y las matrices locales \(\mathbf{k}_l\), \(\mathbf{k}_{g,l}\), \(\mathbf{m}_l\), \(\mathbf{f}_l\).
4. Aplicar liberaciones y condensación estática **antes** de transformar al global.
5. Transformar y ensamblar; sumar la contribución geométrica si el caso la pide.
6. Construir las restricciones: transformación para diafragmas y `equalDOF` acíclicos; penalización solo con ciclos o redundancia.
7. Eliminar GDL restringidos y ensamblar cargas con la reducción de RHS.
8. Verificar antes de resolver: conteo de modos de cuerpo rígido, simetría de \(\mathbf{K}\), residuo de restricciones, número de condición estimado.
9. Resolver (fuera de `core/`), recuperar reacciones \(\mathbf{R}=\mathbf{K}\mathbf{u}-\mathbf{f}\) en los GDL restringidos y comprobar equilibrio global de fuerzas y momentos.
10. Recalcular fuerzas de extremo locales con \(\mathbf{k}_l\mathbf{u}_l+\mathbf{f}_l\) y devolverlas con su convención de signos declarada.

## Implementación en la plataforma
```python
# src/opensees_studio/core/fem/        (núcleo puro: sin Qt, sin openseespy)
#   axes.py        local_axes(xi, xj, vecxz) -> Axes
#   elements.py    bar3d_k, beam3d_k, beam3d_kg, beam3d_timoshenko_k,
#                  quad4_plane_stress_k, quad4_plate_k, hex8_k
#   assembly.py    DofMap, assemble_k, assemble_f, apply_sp_constraints
#   constraints.py RigidDiaphragm, EqualDof, equal_dof_transformation, penalty_terms
#   condense.py    static_condense(k, f, internal_dofs) -> (k_star, f_star)
#   checks.py      rigid_body_mode_count, patch_test, reaction_balance

def beam3d_k(E: float, G: float, A: float, Iy: float, Iz: float, J: float,
             L: float) -> np.ndarray:
    """Matriz local 12x12 (N/m, N·m/rad) en el orden u,v,w,tx,ty,tz por nodo."""

def static_condense(k: np.ndarray, f: np.ndarray, internal: Sequence[int]
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Condensa GDL internos/liberados. Lanza SingularCondensation si K_cc es singular."""

def equal_dof_transformation(dof_map: DofMap, pairs: Sequence[tuple[int, int]]
                             ) -> scipy.sparse.csr_matrix:
    """T con u = T @ u_tilde. Lanza CyclicConstraint si el grafo maestro-esclavo tiene ciclos."""
```
Reglas de arquitectura:
- Todo vive en `core/`: **sin Qt y sin OpenSeesPy**; solo `numpy` (y `scipy.sparse` si ya es dependencia del núcleo).
- El solver se invoca únicamente desde `services/`; `core/` produce matrices y verifica, no resuelve sistemas.
- La emisión de comandos `element`, `geomTransf` y `rigidDiaphragm` al motor corresponde a `services/opensees_script.py`; el núcleo expone datos, no comandos.
- Los valores no derivables (\(k_s\) de secciones no rectangulares, factor de talón, factor de penalización) se leen de `data/fem/*.json` con `source` y `verified_on`.
- Cada función de elemento tiene prueba unitaria contra las formas cerradas de la tabla siguiente; ninguna se conecta al solver sin pasarla.

## Datos normativos
No aplica reproducción de coeficientes normativos: la skill es agnóstica de código y no cita ningún reglamento. Los únicos valores externos son propiedades de material y de sección, más parámetros de formulación.

| Dato | Origen | ¿Verificado? |
|---|---|---|
| Matriz local 12×12 de Euler-Bernoulli y su simetría | Przemieniecki (1968), cap. 6; McGuire et al. (2000), cap. 5 | sí (álgebra comprobada) |
| \(\theta_z=\mathrm{d}v/\mathrm{d}x\), \(\theta_y=-\mathrm{d}w/\mathrm{d}x\) | McGuire et al. (2000), §5.4 | sí |
| Rigidez geométrica \(\frac{P}{30L}[\cdot]\) | Przemieniecki (1968), cap. 12; McGuire et al. (2000) | sí |
| Formulación en \(\phi=\frac{12EI}{GA_sL^2}\) | Przemieniecki (1968); Cook et al. (2001) | sí |
| \(k_s=5/6\) en sección rectangular maciza | Timoshenko, *Strength of Materials* | sí |
| \(k_s\) de otras secciones | tabla de cortante efectivo | **no** — `VERIFICAR`, `data/fem/shear-factors.json` |
| Rigidez de talón (*drilling*) de la lámina | código fuente del elemento en OpenSeesPy 3.8.0.0 | **no** — `VERIFICAR` |
| Factor de penalización por defecto | documentación de OpenSeesPy 3.8.0.0 | **no** — `VERIFICAR` |
| Orientación \(\hat{\mathbf{z}}\) frente a `vecxz` | doc. de `geomTransf` de OpenSeesPy 3.8.0.0 | **no** — `VERIFICAR` |

## Verificación y casos de prueba
Datos de ensayo (no constantes del programa): \(E=2.0\times10^{11}\) Pa, \(G=7.7\times10^{10}\) Pa, \(\nu=0.3\).

| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
| Voladizo, carga puntual | \(L=3\) m, \(I=1\times10^{-4}\) m⁴, \(P=1000\) N, 1 elemento | \(\delta=PL^3/3EI=4.5\times10^{-4}\) m | 1e-10 rel | forma cerrada |
| Voladizo, carga repartida | \(L=3\) m, \(w=5000\) N/m, 4 elementos | \(\delta=wL^4/8EI=2.53125\times10^{-3}\) m | 1e-9 rel | forma cerrada |
| Viga simplemente apoyada, UDL | \(L=6\) m, \(w=1\times10^{4}\) N/m, 2 elementos (nodo central) | \(\delta_{c}=5wL^4/384EI=8.4375\times10^{-3}\) m | 1e-9 rel | forma cerrada |
| Barra axial | \(L=2\) m, \(A=1\times10^{-3}\) m², \(P=5\times10^{4}\) N | \(\delta=PL/EA=5.0\times10^{-4}\) m | 1e-12 rel | forma cerrada |
| Timoshenko, voladizo | \(L=2\) m, \(A=0.12\) m², \(I=1.6\times10^{-3}\) m⁴, \(P=1\times10^{5}\) N, 1 elemento | \(\delta=PL^3/3EI+PL/(k_sGA)=8.59307\times10^{-4}\) m | 1e-6 rel | forma cerrada |
| Modos de cuerpo rígido | 1 elemento viga 3D libre, \(\mathbf{K}\) sin restringir | 6 autovalores con \(\lambda/\lambda_{max}<10^{-9}\) | conteo exacto | álgebra |
| Patch test, deformación constante | cuadrado unitario, quad4, \(u=\varepsilon x\), \(v=-\nu\varepsilon y\), \(\varepsilon=10^{-3}\) | \(\sigma_{xx}=E\varepsilon\), \(\sigma_{yy}=0\), \(\tau_{xy}=0\) en los 4 puntos de Gauss | 1e-10 rel | MacNeal (1994) |
| Patch test, malla distorsionada | 8 quads, nodos interiores desplazados 0.1 m | idéntico al caso anterior | 1e-10 rel | MacNeal (1994) |
| Liberación de momento | viga biempotrada con liberación en \(j\), \(q=10^{4}\) N/m | \(M_j=0\) exacto | 1e-8 rel a \(M_{max}\) | estática |
| Diafragma rígido | losa 4×4 m, 4 nodos, par \(T=10^{4}\) N·m | \(\theta_z=T/K_{\theta}\); \(u\) de cada nodo según la forma rígida | 1e-12 m absoluto | cinemática |
| Equilibrio de reacciones | cualquiera de los casos anteriores | \(\sum R=\sum F\) y \(\sum M=0\) | 1e-8 rel | equilibrio |
| Orientación de ejes | voladizo con \(I_y\ne I_z\), carga en \(+\hat y\) y en \(+\hat z\) | flechas \(PL^3/3EI_z\) y \(PL^3/3EI_y\) | 1e-9 rel | forma cerrada |

## Errores frecuentes y trampas
1. **Copiar el bloque 2D del plano \(x\)–\(y\) al \(x\)–\(z\) sin invertir los términos acoplados** (\(-6EI_y/L^2\)): la matriz deja de ser simétrica bajo reflexión y solo se detecta cargando en los dos planos.
2. **`vecxz` paralelo al eje del elemento**: \(\boldsymbol{\Lambda}\) degenera y aparecen NaN sin excepción. Hay que comparar contra una tolerancia y lanzar un error nombrado.
3. **Orden de nodos invertido** (Jacobiano negativo) en quad o hexaedro: la matriz sigue siendo simétrica y cuadrada, pero el resultado es basura. Se comprueba \(\lvert\mathbf{J}\rvert>0\) en todos los puntos de Gauss.
4. **Un \(\alpha\) único de penalización** para restricciones de traslación y de rotación: las unidades no son homogéneas y el número de condición se dispara. Subir \(\alpha\) «hasta que cierre» enmascara un error de topología de la restricción.
5. **Condensar un GDL liberado que lleva carga aplicada** sin condensar el vector de cargas: la carga se pierde y las reacciones no cierran aunque los desplazamientos parezcan razonables.
6. **Liberar la rigidez elástica y no la geométrica** (o la masa): el pandeo y los modos salen mal. La condensación se aplica a todas las matrices del elemento.
7. **Anular fila y columna del apoyo sin reducir el RHS** con \(\mathbf{K}_{fc}u_c\): los desplazamientos interiores salen bien y las reacciones mal; el gráfico de la deformada no lo delata.
8. **Numeración de GDL 1-based frente a 0-based** entre el modelo y `equalDOF`/`rigidDiaphragm`: se restringe el GDL contiguo equivocado. El mapa de GDL debe ser el único punto de conversión, con prueba de ida y vuelta.
9. **Diafragma con la dirección perpendicular equivocada** en modelos con \(Y\) arriba frente a \(Z\) arriba: se restringe la traslación vertical y desaparecen modos reales del edificio.
10. **Mass lumping descartando los términos rotacionales**: el modo de torsión del diafragma sale a frecuencia infinita y el período fundamental, mal.
11. **Ensamblar solo el triángulo superior y no espejar** (o espejar y además usar un solver que recorre la matriz completa): desplazamientos al doble o a la mitad, con aspecto plausible.
12. **Contar modos de cuerpo rígido con tolerancia absoluta**: con \(K\) del orden de \(10^{10}\) N/m, un umbral de \(10^{-6}\) cuenta decenas de modos espurios. El criterio debe ser relativo a \(\lambda_{max}\) y el informe debe declarar el umbral.
13. **Verificar el patch test solo con malla regular**: la malla regular no detecta el error de Jacobiano ni el de orden de nodos; la distorsionada sí.
14. **Mezclar unidades de material y de sección** (\(E\) en MPa con \(I\) en m⁴) sin declarar la conversión: rigidez equivocada por \(10^{6}\) y flechas que «parecen pequeñas».

## Interfaz de salida
- Trieje de ejes locales por elemento, con el \(\mathbf{v}_{xz}\) usado y el ángulo de orientación de la sección (grados, sentido declarado).
- Formulación efectiva del elemento (Euler-Bernoulli o Timoshenko), \(\phi\), \(A_s\), \(k_s\) y el archivo de datos con su `source`.
- Número de ecuaciones, GDL restringidos y eliminados, y ancho de banda.
- Conteo de modos de cuerpo rígido con el umbral relativo aplicado y los autovalores más pequeños ordenados.
- Informe de restricciones: tipo (transformación o penalización), \(\alpha\) usado, residuo \(\lVert\mathbf{C}\mathbf{u}\rVert\) y pares maestro–esclavo.
- Reacciones y residuo de equilibrio global (\(\sum F\), \(\sum M\)) con su tolerancia.
- Resultado del patch test y de cada caso de la tabla de verificación, con valor analítico, valor calculado y diferencia relativa.
- Avisos nombrados: ejes degenerados, Jacobiano no positivo, condensación singular, restricción cíclica, número de condición por encima del umbral.

## Referencias
1. Przemieniecki, J. S., *Theory of Matrix Structural Analysis*, McGraw-Hill, 1968 (reimpresión Dover, 1985).
2. McGuire, W., Gallagher, R. H. y Ziemian, R. D., *Matrix Structural Analysis*, 2.ª ed., 2000.
3. Bathe, K.-J., *Finite Element Procedures*, 2.ª ed., 2014.
4. Zienkiewicz, O. C. y Taylor, R. L., *The Finite Element Method*, vol. 1, 7.ª ed., 2013.
5. Cook, R. D., Malkus, D. S., Plesha, M. E. y Witt, R. J., *Concepts and Applications of Finite Element Analysis*, 4.ª ed., 2001.
6. MacNeal, R. H., *Finite Elements: Their Design and Performance*, 1994 (patch test).
7. Timoshenko, S. P., *Strength of Materials*, parte I (cortante efectivo).
8. OpenSeesPy, documentación de `element elasticBeamColumn`, `geomTransf`, `rigidDiaphragm`, `equalDOF` y `constraints`, versión 3.8.0.0 (la fijada en `pyproject.toml`).
9. Wilson, E. L., *Static and Dynamic Analysis of Structures*, 4.ª ed., 2002 (modos incompatibles y quad isoparamétrico).

## Registro de verificación
- **Verificado (2026-02-14)**: bloques \(\mathbf{k}_{ii}\), \(\mathbf{k}_{ij}\), \(\mathbf{k}_{jj}\) y simetría \(\mathbf{k}_{ji}=\mathbf{k}_{ij}^\top\); signos \(\theta_z=\mathrm{d}v/\mathrm{d}x\) y \(\theta_y=-\mathrm{d}w/\mathrm{d}x\); rigidez geométrica \(\frac{P}{30L}[\cdot]\); formulación en \(\phi\) y flecha \(\frac{PL^3}{3EI}+\frac{PL}{GA_s}\); \(k_s=5/6\) en sección rectangular; formas cerradas de la tabla de casos; seis modos de cuerpo rígido de un elemento viga 3D libre; álgebra de la condensación estática y de \(\mathbf{T}^\top\mathbf{K}\mathbf{T}\).
- **Pendiente**: orientación de \(\hat{\mathbf{z}}\) frente a `vecxz` en OpenSeesPy 3.8.0.0; \(k_s\) de secciones no rectangulares; factor de penalización por defecto; rigidez ficticia del GDL de talón. Los cuatro exigen el código fuente o la documentación de la versión fijada, no una fuente secundaria.
- **Mientras estén abiertos**: el status de esta skill es `draft` y el programa lee los tres valores de `data/fem/*.json`; ninguna rama del ensamblador los incrusta.
- **Responsable de cerrar**: quien implemente `core/fem/`, con una prueba unitaria por cada valor transcrito.
