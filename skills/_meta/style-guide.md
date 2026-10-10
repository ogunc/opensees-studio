# Guía de estilo y verificación

Reglas obligatorias para toda skill de esta biblioteca. El validador comprueba
solo lo mecánico; lo de abajo lo revisa una persona.

## 1. Voz y estructura

- Español técnico, tercera persona, frases cortas. Los términos normativos
  (*design spectral response acceleration*, *deriva*, *sobrerresistencia*) se
  conservan en su idioma original la primera vez, con traducción entre paréntesis.
- Una idea por párrafo. Nada de introducciones motivacionales.
- Encabezados `##` exactamente con los nombres de la plantilla, en el mismo orden.
- Longitud objetivo: 120–300 líneas. Menos de 120 suele significar que falta
  verificación; más de 300, que hay que partir la skill en dos.

## 2. Unidades y signos

- Internamente **SI coherente**: longitud m, fuerza N, masa kg, tiempo s, tensión Pa,
  aceleración m/s². La gravedad se escribe \(g = 9.80665\ \text{m/s}^2\).
- Las aceleraciones espectrales se expresan **en g** cuando el código las publica en
  g, declarándolo: \(S_{DS} = 1.0\,g\). Nunca se mezcla \(g\) con m/s² en la misma
  fórmula.
- Toda magnitud lleva unidad en la primera aparición y en las tablas.
- Convención de signos explícita: ejes locales del elemento, sentido de las cargas,
  criterio de momentos (antihorario positivo o el del solver), y cómo se convierte.
- Los ángulos en radianes salvo indicación contraria.

## 3. Trazabilidad normativa

Formato de cita en línea: `(ASCE 7-22, §12.8.1)` o `(RNC-07, Art. 24)` o
`(NSR-10, A.4.3)`. Toda tabla reproducida lleva encabezado con la cita completa en
la primera fila del bloque.

Prohibido escribir un coeficiente sin cita: \(R\), \(C_d\), \(\Omega_0\), \(Q\),
\(Q'\), \(\Omega\), \(I\), \(S\), límites de deriva, factores de sitio,
combinaciones de carga, \(\phi\), \(\lambda\).

## 4. Incertidumbre explícita

Cuando un valor no se pudo comprobar contra el documento oficial (tabla escaneada,
figura, norma de pago, edición no disponible):

```markdown
> ⚠️ VERIFICAR: la Tabla 6.5.1 (valores de \(F_{STb}\), \(F_{STc}\)) no se pudo
> leer del PDF oficial. Se comprueba en la copia impresa de NSCM-22, cap. 6.
> Mientras tanto el programa debe **leer el valor de un archivo de datos**
> versionado y no incluirlo en el código.
```

Un `VERIFICAR` no es un defecto: es la forma de que el programa no codifique un
número inventado. Toda skill con `VERIFICAR` abiertos se marca `status: draft`.

## 5. Datos numéricos dentro del programa

Regla de arquitectura derivada de lo anterior:

- Los coeficientes normativos viven en **archivos de datos versionados**
  (JSON/CSV) con campo `source` (norma, edición, tabla) y `verified_on`.
- El código consume el archivo; nunca incrusta la tabla en la lógica.
- Cada entrada de datos tiene prueba unitaria contra la tabla publicada.
- Cambiar de edición de norma = cambiar el archivo de datos, no el motor.

## 6. Verificabilidad

Cada procedimiento relevante termina en una tabla de casos de prueba con:
entrada, resultado esperado, tolerancia y fuente (cálculo a mano, libro, programa
de referencia). Tolerancias típicas recomendadas:

| Magnitud | Tolerancia razonable |
|---|---|
| Desplazamientos | 1 % relativo o 1e-6 m absoluto |
| Fuerzas internas | 1 % relativo |
| Períodos propios | 0.5 % relativo |
| Factores de participación / masa modal | 0.1 % absoluto |
| Comprobaciones normativas (D/C) | exactitud al 0.1 % sobre la fórmula implementada |

## 7. Cosas que nunca se hacen

- Copiar texto normativo extenso (violación de derechos de autor). Se reproduce
  solo lo imprescindible: fórmulas, símbolos y valores, con cita.
- Presentar un resultado normativo sin declarar el nivel de análisis y la
  combinación que lo produjo.
- Redondear resultados intermedios antes de la comprobación final.
- Mezclar el sistema de unidades del modelo con el de la biblioteca de perfiles
  sin declarar la conversión.
- Escribir una skill que dependa de la GUI para funcionar: el núcleo de cálculo
  debe ser utilizable sin interfaz gráfica.
