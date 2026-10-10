# Plantilla canónica de `SKILL.md`

Copia esta plantilla al crear una skill. No borres secciones: si una no aplica,
escribe `No aplica` y por qué (una sección vacía es una señal de que la skill no
está terminada).

````markdown
---
name: nombre-del-directorio
description: >-
  Qué hace esta habilidad y CUÁNDO usarla, en tercera persona. Menciona las
  señales concretas que disparan su uso (archivos, tareas, errores, preguntas).
  Entre 200 y 800 caracteres. Sin "yo", sin marketing.
metadata:
  track: core | seismic | codes | design | platform
  jurisdiction: agnostic | NIC | MEX | COL | PER | CHL | ECU | USA
  edition: "edición exacta del documento normativo, o 'n/a'"
  status: ready | draft | stub
  verified_on: "AAAA-MM-DD"          # última revisión técnica
  scope: [analysis, design, seismic, ui, qa]
---

# Título legible

## Cuándo usar esta skill
Situaciones concretas. Qué preguntas del usuario, qué archivos, qué fallo en el
programa. Incluye los casos en que **no** debe usarse y a qué skill derivar.

## Alcance y límites
Qué cubre y qué queda fuera. Supuestos de partida (tipo de estructura, régimen,
material, nivel de análisis).

## Entradas y supuestos
Datos que la skill necesita del modelo o del usuario: geometría, cargas, masas,
clasificación de sitio, sistema estructural, categoría de riesgo, unidades.
Qué hacer si falta un dato (¿bloquear?, ¿valor por defecto documentado?).

## Fundamento y formulación
Ecuaciones con definición de cada símbolo **y su unidad**. Diagramas en ASCII o
tablas si ayudan. Aquí va la teoría que el implementador necesita para no
equivocarse.

## Procedimiento
Pasos numerados, en orden de ejecución, con el criterio de decisión de cada rama.

## Implementación en la plataforma
Interfaz propuesta: módulo, clase/función, firma, entradas/salidas, errores que
debe lanzar. Ejemplo de uso (pseudocódigo o Python/OpenSeesPy si aplica). Evita
acoplarse a la GUI.

## Datos normativos
Tablas y coeficientes reproducidos **con cita** (norma · edición · artículo o
tabla). Si el valor se lee de una figura o de una tabla que no pudiste verificar:

> ⚠️ VERIFICAR: <qué falta> — se comprueba en <documento, tabla/sección>.

## Verificación y casos de prueba
| Caso | Entrada | Resultado esperado | Tolerancia | Fuente |
|---|---|---|---|---|
Ejemplos calculables a mano o contra un programa de referencia reconocido.

## Errores frecuentes y trampas
Lista de fallos reales: unidades, signos, ejes locales, convenciones de la norma
frente a la del solver, redondeos, casos límite.

## Interfaz de salida
Qué debe exponer el programa al usuario: valores, unidades, envolventes, avisos,
trazabilidad (norma, edición, artículo, pasos intermedios).

## Referencias
Lista numerada de documentos, con edición y año. Enlaces solo si son estables.

## Registro de verificación
- Qué se comprobó, contra qué fuente y cuándo.
- Qué quedó pendiente y quién debe cerrarlo.
````

## Reglas del frontmatter

- `name`: kebab-case, idéntico al nombre del directorio contenedor. El validador lo
  exige.
- `description`: es lo único que un agente ve antes de cargar la skill; debe
  contener el *cuándo*, no solo el *qué*.
- `metadata.edition`: la edición importa más que el nombre. `"ASCE 7-22"` y
  `"NSCM-22"` son valores válidos; `"última"` no lo es.
- `metadata.verified_on`: fecha de la última revisión técnica del contenido, no de
  la última edición del archivo.
