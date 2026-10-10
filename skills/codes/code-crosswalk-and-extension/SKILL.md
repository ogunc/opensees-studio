---
name: code-crosswalk-and-extension
description: >-
  Define el contrato que todo módulo normativo debe cumplir y cómo añadir un país
  o una edición nueva sin tocar el motor de cálculo: esquema de datos JSON para
  coeficientes, interfaz del objeto SeismicCode, registro por ubicación, pruebas
  obligatorias y tabla de equivalencias de parámetros entre RNC-07/NSCM-22,
  NTC-RCDF, NSR-10, E.030, NCh433, NEC-15 y ASCE 7-22. Úsala antes de escribir
  cualquier módulo de código, al migrar de edición normativa o al comparar
  demandas entre jurisdicciones.
metadata:
  track: codes
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [seismic, design, qa]
---

# Transversal — Contrato de módulos normativos y extensión a un país nuevo

## Cuándo usar esta skill

- Vas a implementar un código nacional nuevo (o una edición nueva de uno existente).
- Necesitas comparar demandas sísmicas entre jurisdicciones para un mismo modelo.
- Un proyecto cambia de ubicación y hay que resolver qué norma aplica.
- Necesitas saber **dónde** vive cada decisión normativa para no duplicarla.

## Alcance y límites

Cubre la **arquitectura** de la capa normativa: contrato, datos, registro,
pruebas. No reproduce la formulación de cada código: eso está en el skill del
país correspondiente. No cubre el solver ni el post-proceso.

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| Documento oficial de la edición vigente | no se implementa: los valores no se inventan |
| Ámbito geográfico (país, regiones, `bbox`) | no se registra el código |
| Sistema estructural y categoría de riesgo del proyecto | no se puede resolver \(R\)/\(Q\), \(I\) ni deriva |
| Clasificación de sitio (\(V_s\) o \(V_{s30}\)) | error explícito; nunca un suelo por defecto |
| Edición con la que se calculó un proyecto histórico | se conserva la registrada en el proyecto, no la vigente |

## Fundamento y formulación

1. **La norma es un dato, no un `if`.** Los coeficientes viven en archivos JSON
   versionados con cita y fecha de verificación. El código Python implementa
   *formas* (espectros, combinaciones, chequeos), no valores.
2. **Una norma, una forma.** Muchos códigos comparten estructura (meseta +
   hipérbola + cola); se implementan como *plantillas de espectro* reutilizables y
   cada país aporta sus parámetros y sus reglas de irregularidad.
3. **La edición es parte de la identidad.** Un proyecto guarda `code_id` +
   `edition`. Reabrir un proyecto de 2019 no debe recalcularlo con la edición 2024.
4. **Ningún módulo normativo importa Qt ni OpenSeesPy.** Vive en `core/`.
5. **Toda magnitud regulada es trazable**: la salida lleva norma, edición y
   artículo/tabla junto al número.

## Implementación en la plataforma

### 1. Interfaz `SeismicCode`

```python
# opensees_studio/core/codes/base.py   (core puro)
from typing import Protocol

class SeismicCode(Protocol):
    code_id: str          # "asce7-22", "nic-nscm22", "per-e030"
    edition: str          # "7-22", "NSCM-22 (2022)"
    jurisdiction: str     # "USA", "NIC", "PER"

    def site_class(self, vs30: float, **kw) -> str: ...
    def seismic_parameters(self, site, risk, system, **kw) -> dict: ...
    def spectrum(self, kind: str = "design", **kw) -> "Spectrum": ...
    def design_system(self, system_id: str) -> "DesignSystem": ...
    def load_combinations(self, method: str = "LRFD") -> list["LoadCombination"]: ...
    def drift_limit(self, system, risk, period: float, **kw) -> float: ...
    def analyze(self, model, procedure: str = "auto") -> "SeismicDemand": ...
    def checks(self) -> list["ComplianceCheck"]: ...
```

`Spectrum` es una curva \(T \to S_a\) con metadatos (`accel_unit`,
`damping=0.05`, `source`, `verified_on`). `SeismicDemand` devuelve fuerzas,
desplazamientos, derivas, \(\theta\), torsión y su envolvente, **con unidades
declaradas**.

### 2. Registro por ubicación

```python
# core/codes/registry.py
def resolve_code(lat: float, lon: float, *, override: str | None = None) -> SeismicCode:
    """Devuelve el codigo vigente para el punto. `override` fija la edicion."""
```

Reglas:

- La resolución es **explícita y registrada**: queda en el proyecto el `code_id`,
  la edición, la fecha de resolución y los datos de entrada (coordenada, Vs30,
  categoría de riesgo, sistema).
- Solapamiento (p. ej. Managua dentro de Nicaragua): gana el ámbito más
  específico, y el informe lo declara.
- Sin datos de sitio suficientes: **error**, nunca un valor por defecto silencioso.

### 3. Esquema de datos

```jsonc
{
  "code_id": "nic-nscm22",
  "title": "Norma Sismorresistente para la Ciudad de Managua",
  "jurisdiction": "NIC",
  "edition": "NSCM-22",
  "verified_on": "2026-02-14",
  "scope": {"bbox": [-86.35, 12.05, -86.15, 12.20]},
  "spectrum": {
    "template": "plateau_hyperbola_decay",
    "params": ["a0", "Fas", "I", "beta", "R0", "FSTb", "Tb", "FSTc", "Tc", "Td", "p", "q"],
    "reduced_floor_branch": true
  },
  "systems": [
    {"id": "concrete_smf", "label": "Marco especial a momento",
     "R0": 6.0, "Cd": 5.0, "gamma_max": 0.02,
     "source": "NSCM-22, tabla de coeficientes", "verified": false}
  ],
  "analysis": {"elf": {"height_regular": 12.0, "height_irregular": 6.0,
                        "forbidden_site_classes": ["E"]}},
  "combinations": {"LRFD": ["1.2D + 1.6L", "1.2D + 1.0E + 1.0L", "0.9D + 1.0E"]},
  "sources": [
    {"ref": "NSCM-22", "section": "8.2.1.3", "verified": true},
    {"ref": "NSCM-22", "section": "Tabla 6.5.1", "verified": false}
  ]
}
```

Campos obligatorios por coeficiente: `value`, `unit`, `source`, `verified`.
Un coeficiente con `"verified": false` hace que el informe marque el resultado
como **preliminar**.

## Datos normativos

### Tabla de equivalencias entre códigos

| Concepto | ASCE 7-22 | NSCM-22 | RNC-07 | NSR-10 | E.030 | NCh433 | NEC-15 |
|---|---|---|---|---|---|---|---|
| Peligro de partida | \(S_{MS}, S_{M1}\) multi-periodo | \(a_0\) roca + \(F_{as}\) | \(a_0\) por zona | \(A_a, A_v\) | \(Z\) | \(A_0\) | \(Z\) |
| Clasificación de sitio | A–F (Vs30) | A–E | I–IV (\(V_s\)) | A–F (\(V_s\), \(N\)) | S0–S4 (\(V_s\), \(N\)) | A–E | A–F |
| Amplificación por sitio | incorporada en \(S_{MS}\) | \(F_{as}\) | \(S\) | \(F_a, F_v\) | \(S\) | factores por suelo | \(F_a, F_d, F_s\) |
| Reducción por ductilidad | \(R\) | \(R_0\) | \(Q, Q'\) | \(R\) (DMO/DMI/DES) | \(R\) | \(R\) | \(R\) |
| Sobrerresistencia | \(\Omega_0\) | — | \(\Omega\) | \(\Omega_0\) | — | — | — |
| Importancia | \(I_e\) | \(I\) | grupo A/B/C | \(I\) | \(U\) | \(I\) | \(I\) |
| Amplificación de deriva | \(C_d\) | \(C_d\) | \(Q\Omega/2.5\) | — | — | — | — |
| Combinación direccional | 100/30 o SRSS | 100/30 | 100/30 | 100/30 | 100/30 | — | 100/30 |
| Cortante mínimo | \(0.044 S_{DS}I_e\) | \(C_{s,min}\) | \(c_{min}=Sa_0\) | — | — | — | — |

> ⚠️ VERIFICAR: las columnas de NSR-10, E.030, NCh433 y NEC-15 son un mapa de
> navegación, no una transcripción. Cada celda se confirma en el skill del país y
> en el documento oficial antes de usarse en un cálculo.

## Procedimiento

Para añadir un país, o una edición nueva de un código existente:

1. **Reunir el documento oficial** de la edición vigente y anotar
   `verified_on` (fecha de la revisión, no de la descarga).
2. Crear `data/<pais>/<code_id>/` con los JSON: `meta.json`, `zones.json`,
   `site_classes.json`, `systems.json`, `spectrum.json`, `combinations.json`,
   `drift.json`. Cada valor con `source` y `verified`.
3. Escribir `core/codes/<code_id>.py` implementando `SeismicCode`. Reutilizar la
   plantilla de espectro que corresponda.
4. Registrar el ámbito (país, regiones, `bbox`) en `core/codes/registry.py`.
5. Escribir los tests de `tests/unit/codes/test_<code_id>.py`:
   - cada tabla contra el documento (valor por valor),
   - cada rama del espectro en sus puntos de quiebre,
   - los pisos y los topes (mínimos, máximos de \(A_x\), \(\theta\)),
   - un caso completo calculable a mano.
6. Añadir un caso de integración que reproduzca un ejemplo publicado del código o
   del estudio de contraste, con tolerancia declarada.
7. Crear el skill `codes/<pais>-<code_id>/SKILL.md` a partir de la plantilla.
8. Registrar en `_meta/catalog.md` y ejecutar el validador.

## Verificación y casos de prueba

| Caso | Comprobación |
|---|---|
| Coherencia de datos | todo `value` tiene `unit`, `source` y `verified` |
| Cobertura | cada tabla citada en el skill existe como archivo de datos |
| Continuidad del espectro | \(A(T^-) \approx A(T^+)\) en \(T_b, T_c, T_d\) dentro de 1e-9 |
| Monotonía de ramas | rama descendente estrictamente decreciente |
| Registro | dos ámbitos solapados resuelven al más específico |
| Reproducibilidad | dos ejecuciones del mismo proyecto dan el mismo `code_id` y edición |
| Trazabilidad | todo número del informe tiene `source` no vacío |

## Errores frecuentes y trampas

1. Codificar tablas en Python "porque es más rápido": rompe la trazabilidad y la
   migración de edición.
2. Resolver la norma por nombre de ciudad en vez de por ámbito geográfico
   versionado.
3. Recalcular proyectos antiguos con la edición nueva sin avisar.
4. Reutilizar \(R\) de un código con \(Q\) de otro en el mismo modelo.
5. Suponer que "todos los códigos son ASCE con otro nombre": las formas de
   espectro, los pisos y las correcciones por irregularidad difieren.
6. Olvidar declarar la unidad de \(S_a\) (g vs m/s²) al exportar.
7. Permitir valores por defecto silenciosos para categoría de riesgo o suelo.
8. No separar el ámbito nacional del municipal (Nicaragua es el caso de prueba:
   RNC-07 nacional, NSCM-22 para Managua).

## Interfaz de salida

- `code_id`, edición y fecha de verificación de los datos en cada salida.
- Marca **preliminar** en cualquier resultado que dependa de un coeficiente con
  `verified: false`.
- Lista de `sources` efectivamente usadas por el cálculo, no las declaradas.

## Referencias

1. Skills por país de esta biblioteca (`codes/*`).
2. ASCE/SEI 7-22 — referencia de la plantilla de espectro más extendida.
3. `docs/architecture.md` y `docs/adr/ADR-0002-headless-gui-dep-split.md` — capas
   y separación de dependencias del proyecto.

## Registro de verificación

- **Verificado**: el contrato de datos, las reglas de registro y el flujo de
  extensión; la tabla de equivalencias como mapa conceptual.
- **Pendiente**: confirmar celda por celda la tabla de equivalencias contra cada
  documento oficial al implementar el skill del país.
