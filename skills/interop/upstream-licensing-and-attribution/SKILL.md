---
name: upstream-licensing-and-attribution
description: >-
  Fija el marco legal y de atribución para incorporar capacidades de terceros
  (gidopensees y opstool, ambos GPL-3.0) en un proyecto AGPL-3.0: qué permite el
  artículo 13 de ambas licencias al combinar obras, qué obligaciones sobreviven
  (conservar avisos, entregar el código fuente correspondiente, la cláusula de
  red y la prohibición de relicenciar como propietario), la diferencia entre
  copiar código, traducirlo y reimplementar comportamiento, y entre derivar de
  los esquemas .mat/.cnd y usar un programa como herramienta externa. Úsala
  antes de traer código, datos o dependencias de gidopensees u opstool, al
  revisar las cabeceras GPL del catálogo generado, al registrar procedencia por
  archivo con versión y commit, o al publicar un binario o un servicio en red.
metadata:
  track: interop
  jurisdiction: agnostic
  edition: "GPL-3.0 y AGPL-3.0"
  status: draft
  verified_on: "2026-02-14"
  scope: [interop, legal, qa]
---

# Licencias y atribución de proyectos de terceros

## Cuándo usar esta skill

- Se va a incorporar código, esquemas, tablas o comportamiento de `gidopensees` u `opstool` al proyecto.
- Se regenera `src/opensees_studio/core/catalog/generated/` y hay que confirmar que la cabecera de atribución sobrevive.
- Falla `tests/tools/test_codegen_drift.py` o alguien editó a mano un archivo de `generated/` (prohibido por `core/catalog/README.md`).
- Se evalúa añadir `opstool` como dependencia, extra o herramienta de post-proceso.
- Se publica un binario (`packaging/build.py`) o un servicio en red (`opensees-studio-web`) y hay que decidir qué se entrega como Corresponding Source.
- Se redacta un ADR o un análisis de brechas que trae material de terceros (`docs/adr/ADR-0001-gidopensees-schema-import.md`, `docs/gap-analysis-gidopensees.md`).

**No usar** para la gramática de los BOOK ni el pipeline de esquemas (→ `interop/gid-problem-type-schemas`), para la paridad Tcl/Python (→ `interop/opensees-tcl-python-parity`) ni para decidir en qué capa vive un módulo (→ `platform/platform-architecture-and-services`). Esta skill no da asesoría jurídica: fija el procedimiento y los artefactos que el repositorio ya usa.

## Alcance y límites

Cubre: identificación de licencias, compatibilidad GPL-3.0 ↔ AGPL-3.0, obligaciones que sobreviven, modos de reutilización, marca, registro de procedencia por archivo y lista de comprobación previa.

No cubre: patentes, control de exportaciones, protección de datos, derechos de autor de documentos normativos (ver `skills/_meta/style-guide.md` §7) ni la formulación de los objetos importados. No sustituye la revisión de un abogado para una distribución comercial.

Supuestos: el proyecto es AGPL-3.0 y **no cambia de licencia**; los repositorios de terceros están clonados en local (`/tmp/gidopensees`, `/tmp/opstool-src`) y no se copian dentro del árbol; `schemas.json` y `core/catalog/generated/` están comprometidos en git.

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| `LICENSE` del upstream y commit exacto del clon | no se reutiliza nada: sin commit no hay atribución reproducible |
| Ruta del archivo upstream del que deriva cada archivo local | el archivo local no entra: la procedencia es obligatoria |
| Modo de reutilización (copiar, traducir, reimplementar, derivar datos, herramienta externa) | se asume el más restrictivo (copiar) |
| Licencia del proyecto (`LICENSE`, AGPL-3.0) | no se toca: es una decisión ya aceptada |
| Compatibilidad de intérprete y dependencias del upstream | se descarta la dependencia; nunca se degrada el intérprete del proyecto |
| Marca o nombre registrado del upstream | el nombre no se usa en la interfaz ni en extras |

## Fundamento y formulación

### 1. Licencias verificadas

| Proyecto | Archivo | Licencia | Evidencia |
|---|---|---|---|
| gidopensees | `LICENSE` | GPL-3.0 | «GNU GENERAL PUBLIC LICENSE / Version 3, 29 June 2007» |
| opstool | `LICENCE.txt` | GPL-3.0 | «GNU GENERAL PUBLIC LICENSE / Version 3, 29 June 2007» |
| OpenSees Studio | `LICENSE` | AGPL-3.0 | «GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007»; `pyproject.toml` `license = { file = "LICENSE" }` y classifier «GNU Affero General Public License v3» |

Ambos upstream publican la misma sección 13, «Use with the GNU Affero General Public License» (gidopensees `LICENSE`; opstool `LICENCE.txt` línea 164), que autoriza expresamente combinar la obra cubierta con una obra AGPL-3.0. La dirección permitida es la que el proyecto usa: **GPL-3.0 → AGPL-3.0**, nunca al revés. AGPL-3.0 §13 («Remote Network Interaction; Use with the GNU General Public License», `LICENSE` línea 540) concede la combinación recíproca y añade:

> «the special requirements of the GNU Affero General Public License, section 13, concerning interaction through a network will apply to the combination as such».

### 2. Obligaciones que sobreviven

1. **Conservar los avisos** (GPL-3.0 §5): copyright, licencia, ausencia de garantía y el aviso de la sección 13 en cada archivo derivado.
2. **Entregar el código fuente correspondiente** (GPL-3.0 §6, AGPL-3.0 §6): la forma preferida de modificar la obra, no solo el binario.
3. **No relicenciar como propietario**: la parte derivada sigue siendo GPL-3.0; el conjunto se distribuye bajo AGPL-3.0 y la licencia del proyecto no puede volverse propietaria ni MIT.
4. **Cláusula de red** (AGPL-3.0 §13): si el programa modificado se ofrece por red, hay que ofrecer a los usuarios remotos el Corresponding Source, que incluye el de la parte GPL-3.0 incorporada.
5. **Sin garantía**: el binario no puede insinuar respaldo del upstream ni del laboratorio AUTh.

### 3. Cinco modos de reutilización (no dos)

| Modo | Ejemplo en el proyecto | Obligación |
|---|---|---|
| Copiar código | copiar un `bas/*.bas` a `services/` | avisos + fuente + AGPL-3.0 |
| Traducir código | portar `bas/Materials/Uniaxial/Steel02.bas` a Python línea a línea | idéntica a copiar |
| Derivar de datos | `OpenSees.mat`/`.cnd` → `tools/gidopensees_import/schemas.json` → `core/catalog/generated/` | la obra derivada es GPL-3.0 |
| Reimplementar comportamiento | escribir un emisor propio tras leer el argumento posicional del `.bas` | no hay derivación si no se reproduce su expresión |
| Herramienta externa | invocar `opstool` en su propio entorno | el proceso aislado no elimina la obligación si se distribuye el programa |

La frontera real no es el proceso ni el lenguaje: es si se reprodujo la expresión protegida. Los esquemas `.mat`/`.cnd` **son contenido GPL** y de ellos ya deriva `src/opensees_studio/core/catalog/generated/` (ADR-0001 §1, «Licensing compatibility»).

### 4. Marca

`opstool/utils/consts.py` define `PKG_NAME = "OPSTOOL™"` y `PKG_PREFIX`. La marca y el nombre no se reutilizan en la interfaz, en nombres de extras, en logs ni en nombres de módulos; solo se menciona la compatibilidad de forma factual («lee el ODB de opstool 1.0.26»).

## Procedimiento

1. **Identificar** el upstream, su archivo de licencia y el commit del clon: `git -C /tmp/gidopensees rev-parse HEAD` y `git -C /tmp/opstool-src rev-parse HEAD`.
2. **Clasificar** el modo de reutilización con la tabla de §3. En caso de duda, tratarlo
   como copia y cumplir todas sus obligaciones.
3. **Comprobar compatibilidad**: intérprete y dependencias del upstream contra `requires-python = ">=3.12"` y las dependencias base del proyecto.
4. **Escribir el análisis de brechas** (`docs/gap-analysis-gidopensees.md` es el modelo: qué cubre el upstream, qué cubre el proyecto, qué falta) y, si cambia un contrato, el **ADR** (`docs/adr/ADR-0001-gidopensees-schema-import.md`: estado, fecha, autor, proyecto origen con licencia, sección de compatibilidad y sección «What we are NOT doing»).
5. **Registrar la procedencia** por archivo: ruta upstream, `sha256` del archivo, versión, commit, ruta local y modo.
6. **Insertar el aviso** en cada archivo derivado, desde una plantilla única, no a mano.
7. **Fijar la herramienta fuera de `src/`**, como `tools/gidopensees_import/`: el código de terceros entra como *entrada* de una herramienta de construcción, nunca como import del paquete instalable (ADR-0001 §2.2).
8. **Verificar** con las comprobaciones de la tabla de esta skill, incluida la deriva del catálogo.
9. **Documentar el descarte**: lo que no se reutiliza se declara (ADR-0001 §1: plantillas `bas/`, los `TKWIDGET` de `tcl/`, emisión al solver).
10. **Revisar la distribución**: binario congelado, servicio en red y oferta de Corresponding Source.

## Implementación en la plataforma

Se **reimplementa**: el registro de procedencia, el verificador de avisos, la carga de avisos para el «Acerca de» y la comprobación de compatibilidad de dependencias. Se **descarta**: copiar `bas/*.bas`, `tcl/*.tcl`, `exe/` o `geo/` de gidopensees; importar `opstool` desde `core/` o `views/`; añadir `opstool` (con `xarray`, `zarr`, `netcdf4`, `imageio[ffmpeg]`) a las dependencias base; usar la marca OPSTOOL™.

| Ruta propuesta | Capa | Contenido |
|---|---|---|
| `tools/interop/provenance.py` | fuera de `src/` | registro por archivo, verificación de avisos, compatibilidad |
| `docs/legal/upstream-provenance.json` | datos | upstream, commit, versión, licencia SPDX, derivaciones |
| `src/opensees_studio/data/THIRD_PARTY_NOTICES.md` | datos (existe `data/`) | avisos agregados, junto a `LICENSE-steelpy.txt` |
| `services/notices.py` | `services/` | `load_notices()`, sin Qt y sin solver |
| `tools/gidopensees_import/codegen.py` | build-time (existe) | extender `_HEADER` y `_source_stamp` |
| `tests/tools/test_provenance.py` | pruebas | aviso presente, digests y commit registrados |

```python
# tools/interop/provenance.py   (build-time; sin Qt, sin solver)
@dataclass(frozen=True)
class UpstreamSource:
    repo: str            # "https://github.com/rclab-auth/gidopensees"
    commit: str          # sha1 del clon usado para generar
    version: str         # OpenSees.xml declara 3.0.0
    license_spdx: str    # "GPL-3.0-only"

@dataclass(frozen=True)
class Derivation:
    upstream_file: str   # "OpenSees.mat"
    upstream_sha256: str
    local_path: str      # "src/opensees_studio/core/catalog/generated/steel02.py"
    mode: str            # copy | translate | data | behavior
    notice: str          # texto exacto insertado por codegen

def scan_generated(root: Path) -> list[Derivation]: ...
def check_notices(registry: Path, generated: Path) -> list[str]:
    """Devuelve la lista de violaciones; vacía = conforme."""
def check_compat(pyproject: Path, upstream_pyproject: Path) -> list[str]:
    """Rechaza el upstream si su rango de Python no corta con requires-python."""
```

La plantilla de aviso ya existe en `tools/gidopensees_import/codegen.py` (`_HEADER`, `CODEGEN_VERSION = 2`) y emite las cuatro líneas de atribución en cada archivo; su sello real es `# Generated from schemas.json sha256:42032585df71, codegen v2`. Ese sello **no** incluye el commit del upstream: el registro debe añadirlo.

Reglas de capa: `core/` sigue sin Qt ni openseespy (la comprobación de cabeceras es de construcción, no de ejecución); `views/` nunca lee archivos de licencia — los pide al viewmodel, que llama a `services/notices.py`; ninguna importación de terceros ocurre en el hilo de la GUI porque no hay importación de terceros en tiempo de ejecución.

## Datos normativos

No aplica: no hay norma de diseño en juego. El dato real vive en los textos de licencia y en las cabeceras de los archivos upstream — `LICENSE` del proyecto (AGPL-3.0 §13, línea 540), `LICENSE` de gidopensees y `LICENCE.txt` de opstool (GPL-3.0 §13, línea 164), y el bloque de aviso de `OpenSees.prb`, `OpenSees.mat`, `OpenSees.cnd` y `OpenSees.tcl`, que reproduce el copyright, la lista de autores y el aviso GPL completo:

```text
# GiD + OpenSees Interface - An Integrated FEA Platform
# Copyright (C) 2016-2022
# Lab of R/C and Masonry Structures / School of Civil Engineering, AUTh
# Development Team: T. Kartalis-Kaounis, V.K. Papanikolaou
# This program is free software: ... GNU General Public License ... version 3 ...
```

Ningún texto de licencia se incrusta en el código: se copia el archivo tal cual y se referencia.

## Verificación y casos de prueba

| Caso | Comando, dato o condición | Resultado esperado |
|---|---|---|
| Aviso en el catálogo | `grep -rL "Combined here under AGPL-3.0 per GPL section 13." src/opensees_studio/core/catalog/generated/` | sin salida |
| Deriva del catálogo | `pytest tests/tools/test_codegen_drift.py -q` | pasa; árbol idéntico byte a byte |
| Idempotencia | `pytest tests/tools/test_codegen_idempotent.py -q` | pasa |
| Digest del esquema | `sha256sum tools/gidopensees_import/schemas.json \| cut -c1-12` | `42032585df71`, igual al sello del archivo generado |
| Commit del upstream | `python -m tools.interop.provenance check` | `source.commit` no vacío y == `git -C /tmp/gidopensees rev-parse HEAD` |
| Núcleo puro | `python -c "import opensees_studio.core, sys; assert 'PySide6' not in sys.modules"` | sin error |
| Sin opstool en runtime | `grep -rn "opstool" src/opensees_studio/` | solo el archivo de avisos; cero imports |
| Dependencias base | `grep -n "xarray\|zarr\|netcdf4\|opstool" pyproject.toml` | sin coincidencias en `dependencies` |
| Compatibilidad | `grep -n "python =" /tmp/opstool-src/pyproject.toml` | `>=3.10,<3.13`; intersección con `>=3.12` declarada |
| LICENSE intacto | `git diff --exit-code LICENSE` | código 0 |
| Aviso en el binario | `python packaging/build.py` y listar `dist/` | contiene `LICENSE` y `THIRD_PARTY_NOTICES.md` |
| Marca | `grep -rn "OPSTOOL" src/opensees_studio/views/` | sin salida |
| Precisión | datos de un ODB de opstool (`dtype` int32/float32) contra `result_store` | promoción explícita a float64, diferencia registrada |

## Errores frecuentes y trampas

1. **Relicenciar como propietario.** Cambiar `LICENSE` o el classifier a MIT/BSD «porque solo usamos los esquemas» incumple GPL-3.0 §5 y AGPL-3.0 §13.
2. **Perder la cabecera al regenerar.** `_HEADER` de `codegen.py` es la única fuente del aviso; una plantilla editada sin regenerar deja archivos sin atribución y `test_codegen_drift.py` no lo detecta si el árbol se regeneró con la plantilla nueva.
3. **Confundir reimplementar con traducir.** Escribir un emisor «propio» copiando el orden de argumentos de `bas/Materials/Uniaxial/Steel02.bas` (ramas por `Formulation`: Stress-Strain, Force-Deformation, momento-rotación) es una traducción, con las obligaciones de copia.
4. **Creer que el proceso hijo aísla la licencia.** Invocar `opstool` como herramienta externa no cambia nada si el programa se distribuye o se ofrece por red: la cláusula §13 sigue aplicando.
5. **Buscar el aviso en el archivo equivocado.** De 163 archivos `bas/*.bas`, ninguno lleva cabecera; el aviso completo está en `OpenSees.prb`, `OpenSees.mat`, `OpenSees.cnd` y `OpenSees.tcl`. Tomar el aviso de un `.bas` deja la atribución incompleta (falta la lista de autores).
6. **Atribuir solo al laboratorio.** La cabecera upstream nombra el *Development Team* y los *Project Contributors*; el aviso del proyecto (`core/catalog/README.md`, `generated/steel02.py`) solo nombra al laboratorio AUTh.
7. **No registrar el commit.** `schemas.json` guarda únicamente su propio `sha256`; sin el commit del upstream, dos generaciones con el mismo digest pueden provenir de árboles distintos.
8. **Añadir opstool a las dependencias base.** `opstool` exige Python `>=3.10,<3.13` y arrastra `xarray`, `zarr`, `netcdf4` e `imageio[ffmpeg]`: en el entorno fijado (Python 3.12, `openseespy==3.8.0.0`, `h5py`) puede resolver a versiones incompatibles. Va en un extra o en un entorno separado, nunca en `dependencies`.
9. **Usar la marca.** `OPSTOOL™` en el nombre de un extra, en un log (`PKG_PREFIX`) o en la interfaz.
10. **Pérdida de precisión al leer datos derivados.** El `dtype` por defecto de opstool es int32/float32; el proyecto escribe float64 (`services/result_store.py`). Comparar o volcar sin promover produce diferencias de 1e-7 que parecen errores del solver.
11. **Olvidar la cláusula de red.** Un backend web que sirva el programa modificado debe ofrecer el Corresponding Source, incluido el de la parte GPL-3.0.
12. **No distribuir la licencia.** `packaging/opensees-studio.spec` arma `datas = []` y añade solo `aisc_v16.csv`, `README.md` y `LICENSE-steelpy.txt` (del paquete `data/`): hoy el binario congelado no incluye `LICENSE` ni un archivo de avisos de terceros.

## Interfaz de salida

- `docs/legal/upstream-provenance.json`: por cada upstream, `repo`, `commit`, `version`, `license_spdx`, y por cada derivación `upstream_file`, `upstream_sha256`, `local_path`, `mode`, `notice`, `verified_on`.
- `src/opensees_studio/data/THIRD_PARTY_NOTICES.md`: avisos agregados, distribuido con el binario y accesible desde «Acerca de» a través de `services/notices.py`.
- El verificador `python -m tools.interop.provenance check` devuelve `0` conforme, `1` violación (archivo sin aviso, digest o commit ausente, dependencia incompatible) y `3` upstream no disponible en local (se omite, no se aprueba).
- Cada resultado o informe que use datos derivados declara el upstream, su versión y su commit junto al dato.
- Avisos al usuario: atribución incompleta, dependencia de terceros fuera de su rango de intérprete y ODB leído con precisión reducida.

## Referencias

1. GNU Affero General Public License v3 — `LICENSE` del proyecto, §13 en la línea 540 («Remote Network Interaction; Use with the GNU General Public License»).
2. gidopensees, <https://github.com/rclab-auth/gidopensees>, GPL-3.0: `LICENSE` (§13 «Use with the GNU Affero General Public License»), `README.md` (copyright 2016-2023, Lab of R/C and Masonry Structures, AUTh), `OpenSees.mat` / `OpenSees.cnd` / `OpenSees.prb` / `OpenSees.tcl` (bloque de aviso), `OpenSees.xml` (`<Version>3.0.0</Version>`).
3. opstool 1.0.26, <https://github.com/yexiang92/opstool>, GPL-3.0: `LICENCE.txt` (§13 en la línea 164), `pyproject.toml` (`python = ">=3.10,<3.13"`), `opstool/utils/consts.py` (`PKG_NAME = "OPSTOOL™"`, `PKG_PREFIX`).
4. Proyecto: `docs/adr/ADR-0001-gidopensees-schema-import.md` (estado, compatibilidad GPL-3.0/AGPL-3.0, alcance y exclusiones), `docs/gap-analysis-gidopensees.md`, `docs/architecture.md`, `CLAUDE.md`, `CONTRIBUTING.md`.
5. Proyecto: `tools/gidopensees_import/codegen.py` (`_HEADER`, `_source_stamp`, `CODEGEN_VERSION = 2`), `tools/gidopensees_import/schemas.json`, `src/opensees_studio/core/catalog/README.md`, `src/opensees_studio/core/catalog_material.py`, `src/opensees_studio/services/catalog_emitters.py`.
6. Proyecto: `src/opensees_studio/data/README.md` y `LICENSE-steelpy.txt` (precedente de licencia de terceros junto al dato), `packaging/opensees-studio.spec`, `tests/tools/`.
7. `skills/_meta/style-guide.md` §7 y `skills/_meta/skill-template.md` — reglas de reproducción de contenido ajeno.

## Registro de verificación

- **Verificado (2026-02-14)** leyendo los repositorios clonados: gidopensees `LICENSE` es GPL-3.0 con la sección 13 y el clon apunta al commit `74809b8faa9e0413c0320ccdbd96174603d514b5`; `OpenSees.xml` declara `<Version>3.0.0</Version>`; el bloque de aviso con autores está en `OpenSees.prb`/`.mat`/`.cnd`/`.tcl` y **ninguno** de los 163 `bas/*.bas` lo lleva; opstool `LICENCE.txt` es GPL-3.0 con la sección 13 en la línea 164, su `pyproject.toml` declara `python = ">=3.10,<3.13"` y `consts.py` define `PKG_NAME = "OPSTOOL™"`. Del proyecto: `LICENSE` AGPL-3.0 con §13 en la línea 540; `pyproject.toml` con `license = { file = "LICENSE" }` y `requires-python = ">=3.12"`; `codegen.py` ya emite las cuatro líneas de atribución y sella `sha256:42032585df71, codegen v2`, digest que coincide con `sha256sum tools/gidopensees_import/schemas.json`; `packaging/opensees-studio.spec` no añade `LICENSE`.
- **Pendiente**:
  > ⚠️ VERIFICAR: si el `schemas.json` comprometido se generó a partir del commit `74809b8f…` del clon y no de otro árbol. Se comprueba regenerando con `python -m tools.gidopensees_import.parse_schemas` sobre `/tmp/gidopensees/OpenSees.mat` y `.cnd` y comparando el digest resultante con `42032585df71` y con `git -C /tmp/gidopensees rev-parse HEAD`.
  > ⚠️ VERIFICAR: si «OPSTOOL™» es una marca registrada y en qué clases y jurisdicciones. Se comprueba en el `README.md` y la documentación de opstool-doc.readthedocs.io y en el registro de marcas correspondiente; mientras tanto se trata como marca no registrada y no se usa.
  > ⚠️ VERIFICAR: si el binario congelado debe incluir el aviso completo o basta el puntero al repositorio, y cómo lo entrega la oferta de Corresponding Source del backend web. Se comprueba listando `dist/` tras `python packaging/build.py` y revisando el `THIRD_PARTY_NOTICES.md` que se propone; lo cierra quien mantenga `packaging/`.
