# Tutorial 2 — Un edificio con losas rígidas: modos, espectro de respuesta y derivas

[English](02-building-spectrum-drift.md) · **Español**

Un marco de hormigón de tres pisos con un diafragma rígido por piso: vas a leer
sus modos, correr un espectro de respuesta con CQC y verificar las derivas de
piso contra NCh433.

**Necesitas:** un solver (Options → Solver) y
`examples/building_3storey_diaphragm.osmodel` (regenéralo con
`python examples/building_3storey_diaphragm.py`).

## 1. El modelo

File → **Open…** → `examples/building_3storey_diaphragm.osmodel`.

- 2 × 2 vanos (6 m en X, 5 m en Y), pisos de 3.5 m, columnas de 500 × 500 mm y
  vigas de 300 × 600 mm de hormigón C30 (25 kN/m³).
- **Define → Storeys…**: Story1 a Story3, leídos de las líneas de grilla en Z,
  como ETABS lee sus pisos.
- **Assign → Joint → Diaphragm…**: un diafragma rígido por piso. Su nodo maestro
  está en el centro de masa (6, 5) y no toca ningún elemento, así que el runner
  fija sus grados de libertad fuera del plano. Todos los nudos del piso lo siguen
  en el plano de la losa.
- **Define → Mass Source…**: DEAD (carga de vigas más peso propio) + 0.3 LIVE,
  convertidos en masa y concentrados en cada nodo maestro con la inercia
  rotacional del piso.

## 2. Modos

**Analyze → Run All Cases** corre DEAD, EQX, el caso modal y el espectro.

El caso modal usa el solver de autovalores denso hasta 500 grados de libertad
libres, así que los modos son los mismos en cada corrida y en cada máquina (ver el
README, *Modal analysis: deterministic results*). El modo 1 es el desplazamiento
lateral en X: **T₁ = 0.69 s**, con el **80 %** de la masa participando. Elige el
caso modal en **Display → Show Results Of…** y usa **Display → Animate Mode
Shape** para verlo.

## 3. Espectro de respuesta

El caso **RSX-CQC** combina los modos por CQC (el valor por defecto de los casos
de espectro nuevos) bajo un espectro aproximado del Eurocódigo 8 Tipo 1, suelo B,
con ag = 0.30 g. El modo 1 lee de él Sa(0.69 s) = 7.16 m/s².

Los resultados de espectro son **picos**: positivos, con el signo perdido en la
combinación. Las reacciones, los esfuerzos en los miembros y las resultantes de
las cáscaras son cada uno la combinación de la respuesta estática de cada modo,
nunca derivados de los desplazamientos combinados. La tabla de pisos del panel
**Results** muestra desplazamiento, deriva y corte de piso, combinados piso por
piso.

## 4. Verificación de derivas

**Design → Storey Drift Check…**

![La verificación de derivas del edificio con el preset de NCh433](img/building-drift.png)

- **Code** → *NCh433, centre of mass (0.002 h)*, **Amplification** 1.
- **Check** lista cada caso estático y de espectro con resultado, piso por piso.
  Una razón mayor que 1 excede el límite, y su fila se pone roja.

Las derivas del espectro quedan muy por encima de 0.002 h porque este espectro es
**elástico**: NCh433 verifica la deriva bajo el espectro de diseño reducido por
R\*, así que escala el espectro (o pon la amplificación en 1/R\*) antes de leer
esto como un veredicto. Lo que este tutorial enseña es el flujo de trabajo: pisos,
diafragmas, fuente de masa, modos, CQC y un límite de deriva, todo en un modelo.

## 5. Qué sigue

- **Design → Steel Frame Check** funciona igual en un edificio de acero
  ([Tutorial 1](01-steel-frame-design.es.md)).
- **Define → Seismic Loads (Equivalent Lateral Force)…** construye el patrón
  sísmico estático de ASCE 7 con los mismos pisos y masas.
- El [Manual de Verificación](../verification-manual.md) muestra los casos de un
  grado de libertad y del voladizo que fijan los solvers modal y de espectro a la
  solución cerrada.
