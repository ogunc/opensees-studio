---
name: actions-ci-and-quality-gates
description: >-
  Documenta la integración continua del repositorio en GitHub Actions —los
  flujos ci.yml (jobs lint, test y gui con su matriz de sistemas operativos y
  versiones de Python) y desktop.yml (paquete de escritorio y publicación del
  release)— y las puertas de calidad que bloquean una fusión: versiones de ruff
  y mypy fijadas, ratchet de mypy, import-linter, cobertura mínima 75 y el
  marcador slow. Úsala al editar cualquier archivo de .github/workflows/ o
  .github/actions/, al añadir un job, un paso o una plataforma a la matriz, al
  diagnosticar un flujo rojo o un job que falla solo en el CI, al reproducir el
  CI en local antes de abrir un pull request, al decidir qué comprobaciones
  exigir antes de mergear y al publicar un tag v*.
metadata:
  track: github
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [devops, ci]
---

# Integración continua y puertas de calidad en GitHub Actions

Todo lo afirmado aquí procede de los archivos del repositorio: `.github/workflows/ci.yml`, `.github/workflows/desktop.yml`, `.github/actions/windows-opengl/action.yml`, `.github/dependabot.yml`, `pyproject.toml`, `tools/typecheck.py`, `tools/mypy-budget.txt` y `CONTRIBUTING.md`. Lo que depende de la configuración del repositorio en GitHub y no del árbol de trabajo se marca con `VERIFICAR`.

## Cuándo usar esta skill

- Se crea o modifica cualquier archivo bajo `.github/workflows/` o `.github/actions/`, o hay que añadir un job, un paso, una versión de Python o un sistema operativo a la matriz.
- Un flujo aparece en rojo y hay que decidir si el fallo es del código, del entorno (Qt, OpenGL, caché, red) o del propio flujo.
- Antes de abrir un pull request: reproducir en local exactamente lo que el CI ejecuta, en el mismo orden.
- Hay que decidir qué comprobaciones marcar como obligatorias antes de fusionar y qué significa cada una.
- Se publica un tag `v*` y hay que comprobar que el release sale con notas y sumas de verificación.
- **No** usar esta skill para el detalle de firma y empaquetado (→ `packaging/README.md`) ni para el porqué de la dirección de dependencias (→ `platform/platform-architecture-and-services`).

## Alcance y límites

Cubre los dos flujos del repositorio y sus jobs, las puertas de calidad que ejecutan, el contrato de las acciones compuestas locales, y el uso de artefactos, permisos, secretos y caché, además del diagnóstico de un flujo rojo. No cubre el contenido de `CHANGELOG.md` ni la generación de notas (`tools/release_notes.py`), la construcción del paquete con PyInstaller (`packaging/build.py`), las reglas arquitectónicas en sí, ni la configuración de la rama protegida, que vive en los ajustes del repositorio y no en el árbol de trabajo.

## Entradas y supuestos

| Dato | Fuente | Si falta |
|---|---|---|
| Comandos exactos de lint y formato | `ci.yml`, job `lint` | no reconstruirlos de memoria: leerlos del flujo |
| Versiones de ruff y mypy | `ci.yml` (fijadas) | el presupuesto está medido con `mypy==2.4.0` |
| Presupuesto de errores de mypy | `tools/mypy-budget.txt` | solo puede bajar; lo aplica `tools/typecheck.py` |
| Umbral de cobertura | `ci.yml`: `--cov-fail-under=75` | no bajarlo sin justificarlo en el PR |
| Sistemas operativos y Pythons | matriz de los jobs `test` y `gui` | 3.12 obligatorio; 3.13 y 3.14 solo en Linux |
| Qué secretos de firma existen | ajustes del repositorio | `gh secret list` (ver bloque `VERIFICAR`) |

## Fundamento y formulación

### Del commit a la puerta de fusión

Un flujo se dispara por un evento y produce *check runs* asociados a una referencia; la rama protegida exige que estén en verde.

```text
 commit ──push/PR──▶ refs/heads/{main,develop}
                          ├─ "CI"      ─▶ lint ─▶ test (matriz) ─▶ gui (matriz)
                          └─ "Desktop" ─▶ bundle (matriz) ─▶ publish (solo tags v*)
                                        check runs ─▶ política de rama ─▶ merge
```

Consecuencias: un check que **nunca se reporta** bloquea la fusión igual que uno rojo, y `needs: lint` convierte `lint` en la puerta de entrada de los otros dos jobs, de modo que un fallo de formato no gasta la matriz completa.

### Artefacto frente a caché

Una caché nunca es fuente de verdad, y publicar resultados desde ella es un error, no una optimización.

| Concepto | Qué es | Persistencia | Uso aquí |
|---|---|---|---|
| Artefacto | Salida de un job, descargable, no se reescribe | 90 días por defecto; `desktop.yml` fija `retention-days: 14` | `coverage-xml`; los `*.zip` por plataforma |
| Caché | Almacén reutilizable indexado por el hash del archivo de dependencias | Invalidable, se puede perder | Hoy **no** se usa en `ci.yml` |

### Por qué las versiones están fijadas

| Herramienta | Versión | Razón |
|---|---|---|
| ruff | `0.16.8` | una regla o un formato nuevos ponen `ruff format --check` en rojo sin que nadie tocara el código |
| mypy | `2.4.0` | `tools/mypy-budget.txt` es un **conteo exacto**; otra versión de mypy o de typeshed mueve el número por razones ajenas al código |

`mypy` corre en el job `test` y no en `lint` porque el conteo contra un entorno **sin dependencias instaladas** no significa nada: sin los paquetes importables mypy reporta un número distinto y sin relación con el real. `lint` solo instala las dos herramientas para verificar formato.

### Cobertura y marcador `slow`

`--cov-fail-under=75` se aplica a `pytest tests/unit tests/integration tests/tools`, sin la suite GUI, y `[tool.coverage.run]` excluye `src/opensees_studio/views/*`: el 75 % es un suelo sobre el código verificable de forma estable en un runner headless, con `branch = true`. El marcador `slow` es comodidad del bucle local (`CONTRIBUTING.md` lo propone para iterar sobre un área); en CI **no** se usa `-m "not slow"`, porque omitir pruebas es como desaparece la cobertura sin que nadie lo note.

### Tags, SemVer y mínimo privilegio

- Un tag `v*` es la frontera entre "código en una rama" y "versión publicada": `desktop.yml` publica solo bajo `refs/tags/`, y `tools/release_notes.py` falla si el tag no tiene sección en `CHANGELOG.md`.
- `permissions` es mínimo privilegio: `ci.yml` no declara ninguna y hereda el valor por defecto del repositorio; `desktop.yml` pide `contents: write` porque adjunta archivos al release.
- El `GITHUB_TOKEN` de un `pull_request` desde un fork es de solo lectura y no recibe secretos: por eso un fork produce archivos sin firmar y el flujo no se rompe.

## Procedimiento

1. **Leer el flujo antes de tocarlo**; los comandos y las condiciones son la especificación.
   ```bash
   cat .github/workflows/ci.yml .github/workflows/desktop.yml
   cat .github/actions/windows-opengl/action.yml
   ```

2. **Reproducir el CI en local, en este orden.** El job `lint` es el más rápido y el que más falla; las dos puertas siguientes solo corren en el CI dentro de `test` (Linux 3.12) y necesitan las dependencias instaladas; la cobertura usa el mismo umbral.
   ```bash
   ruff check src tests
   ruff format --check src tests
   python tools/typecheck.py     # mypy con ratchet sobre tools/mypy-budget.txt
   lint-imports                  # capas de [tool.importlinter] en pyproject.toml
   QT_QPA_PLATFORM=offscreen pytest tests/unit tests/integration tests/tools \
     --cov --cov-report=xml --cov-report=term-missing --cov-fail-under=75
   pytest tests/gui              # Windows / macOS
   xvfb-run -a pytest tests/gui  # Linux, headless
   ```
   Comprobar el **código de salida** de la suite GUI, no solo el conteo: un `0xC0000374` de Windows con todo en verde sigue siendo un fallo de teardown.

3. **Añadir un paso**: `run` si es un comando, `uses` si es una acción. Toda acción de terceros va fijada por SHA o por tag de versión mayor, como ya hace la acción compuesta local.
   ```yaml
   - name: Layers (import-linter)
     if: runner.os == 'Linux' && matrix.python-version == '3.12'
     run: lint-imports
   ```

4. **Añadir un job**: declarar `needs`, matriz y `fail-fast: false` cuando cada celda deba reportar por separado.
   ```yaml
   jobs:
     packaging-smoke:
       needs: lint
       runs-on: ubuntu-latest
       strategy: {fail-fast: false, matrix: {python-version: ["3.12"]}}
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: {python-version: "3.12"}
         - run: pip install --retries 5 -e ".[packaging]"
   ```

5. **Añadir una plataforma a la matriz** arrastra tres consecuencias obligatorias: el paso de dependencias Qt de Linux (`if: runner.os == 'Linux'`), `./.github/actions/windows-opengl` en Windows, y `xvfb-run -a` en Linux para la suite GUI. Sin ellas el primer paso que abre una ventana o carga VTK falla.

6. **Activar caché y concurrencia** (hoy no existen en `ci.yml`). La caché de pip se indexa por el archivo que declara las dependencias; la concurrencia evita que una actualización forzada deje dos ejecuciones compitiendo, pero en `desktop.yml` la cancelación **no** debe alcanzar a un tag.
   ```yaml
   - uses: actions/setup-python@v5
     with: {python-version: "${{ matrix.python-version }}", cache: pip, cache-dependency-path: pyproject.toml}
   concurrency:
     group: ${{ github.workflow }}-${{ github.ref }}
     cancel-in-progress: ${{ github.event_name == 'pull_request' }}
   ```

7. **Leer un fallo** identificando job y paso antes de tocar el código.
   ```bash
   gh run list --workflow=ci.yml --limit 10
   gh run view <run-id> --log-failed
   gh run rerun <run-id> --failed          # reintenta solo lo que falló
   gh run view --job <job-id> --log        # log completo de un job
   ```
   Un fallo reproducible en local es del código; uno que solo aparece en el CI apunta a entorno (Qt, OpenGL, permisos, red) o a una diferencia de versión. Para más detalle, activar el secreto `ACTIONS_STEP_DEBUG` en el repositorio.

8. **Antes de mergear**, exigir en verde `lint`, `test` y `gui`; dentro de `test` van además el ratchet de mypy y `lint-imports` (Linux 3.12). Los nombres exactos de los checks son los que muestra la interfaz.

## Implementación en la plataforma

### Anatomía de `ci.yml`

| Job | `needs` | Matriz | Pasos propios |
|---|---|---|---|
| `lint` | — | ubuntu-latest, Python 3.12 | `pip install ruff==0.16.8 mypy==2.4.0`; `ruff check src tests`; `ruff format --check src tests` |
| `test` | `lint` | ubuntu/windows/macos × 3.12, más `include` de ubuntu 3.13 y 3.14; `fail-fast: false` | deps Qt en Linux, Mesa en Windows, `pip install --retries 5 -e ".[gui,dev]"`; `typecheck.py` y `lint-imports` solo Linux 3.12; pytest con `--cov-fail-under=75` y `QT_QPA_PLATFORM=offscreen`; sube `coverage-xml` con `if: always()` |
| `gui` | `lint` | ubuntu/windows/macos × 3.12; `fail-fast: false` | mismas deps Qt y Mesa; `xvfb-run -a pytest tests/gui` en Linux, `pytest tests/gui` en Windows y macOS |

`on:` es `push` y `pull_request` contra `[main, develop]`, sin filtros de ruta: cualquier cambio en esas ramas ejecuta la matriz completa.

### Anatomía de `desktop.yml`

| Job | Condición | Contenido |
|---|---|---|
| `bundle` | `workflow_dispatch`, tag `v*`, o PR que toque `packaging/**` o el propio flujo | matriz ubuntu/windows/macos; artefactos `OpenSeesStudio-linux`, `-windows`, `-macos`; Python 3.12 en todos; `pip install -e ".[gui,packaging]"`; `xvfb-run -a python packaging/build.py --gui-smoke` en Linux y `python packaging/build.py` en el resto; firma de macOS y Windows opcional, omitida si el secreto no existe; sube `dist/*.zip` con `retention-days: 14` |
| `publish` | `needs: bundle` y `startsWith(github.ref, 'refs/tags/')` | `download-artifact@v4` con `merge-multiple: true`; `SHA256SUMS.txt`; notas con `tools/release_notes.py "${{ github.ref_name }}"`; `softprops/action-gh-release@v2` con `fail_on_unmatched_files: true` |

Hay **un solo publicador** a propósito: antes cada plataforma adjuntaba su archivo al mismo release y competían por él; un zip mal nombrado llegó a reemplazar el de otra plataforma.

### Acción compuesta, permisos y rutas

`.github/actions/windows-opengl/action.yml` instala Mesa llvmpipe 24.3.0 en Windows con `pyvista/setup-headless-display-action` **fijada por SHA**, con `install-mesa3d-offscreen: false` (esa variante cambiaría VTK a `vtkOSOpenGLRenderWindow`, que Qt no puede alojar). El mismo paso aparece en `test` y en `gui` para que ambas suites usen el mismo driver.
```yaml
permissions:
  contents: write   # solo en desktop.yml: adjunta archivos al release
on:
  pull_request:
    paths:                       # solo en desktop.yml
      - "packaging/**"
      - ".github/workflows/desktop.yml"
```
Un filtro de rutas en un job que sea *check obligatorio* es una trampa: si el filtro no casa, el check no se reporta y el PR queda bloqueado esperándolo.

## Datos normativos

No aplica. Los valores que gobiernan estas puertas son versiones y presupuestos, no coeficientes normativos, y viven en el propio repositorio: `ruff==0.16.8` y `mypy==2.4.0` en `.github/workflows/ci.yml`, el presupuesto en `tools/mypy-budget.txt`, el umbral de cobertura en el job `test`, las reglas de dependencias en `[tool.importlinter]` de `pyproject.toml` y las notas de versión en `CHANGELOG.md` (consumidas por `tools/release_notes.py`).

## Verificación y casos de prueba

| Comprobación (comando o condición) | Resultado esperado |
|---|---|
| `ruff check src tests` | sin hallazgos; exit 0 |
| `ruff format --check src tests` | ningún archivo requeriría reformateo |
| `python tools/typecheck.py` | imprime `mypy: N error(s), budget B` con `N <= B` |
| `lint-imports` | todos los contratos en `KEPT`; exit 0 |
| `QT_QPA_PLATFORM=offscreen pytest tests/unit tests/integration tests/tools --cov --cov-fail-under=75` | pruebas en verde y cobertura ≥ 75 % |
| `pytest tests/gui` (un solo proceso) | exit 0; un código distinto de 0 con todo "passed" indica fuga de teardown |
| `gh run view <id> --json jobs` | los tres jobs `lint`, `test` y `gui`; `test` y `gui` arrancan tras `lint` |
| Matriz del job `test` | 5 celdas: 3 sistemas × 3.12 más ubuntu 3.13 y ubuntu 3.14 |
| Matriz del job `gui` | 3 celdas: ubuntu, windows y macos × 3.12 |
| `python tools/release_notes.py <tag>` | emite notas; **falla** si el tag no tiene sección en `CHANGELOG.md` |
| `ls dist` dentro de `publish`, en un tag `v*` | tres `*.zip` y `SHA256SUMS.txt` antes de publicar |

## Errores frecuentes y trampas

1. **Publicar sin notas de versión**: el tag existe y el release sale con cuerpo vacío. Escribir la sección en `CHANGELOG.md` **antes** de empujar el tag; `tools/release_notes.py` falla a propósito cuando falta.
2. **Duplicar el publicador**: añadir un paso que adjunte el archivo desde cada plataforma reintroduce la carrera que `publish` elimina; un nombre de zip equivocado reemplaza el de otra plataforma.
3. **Bump de un wheel atado al intérprete**: `openseespy`, `openseespywin` y `openseespylinux` están ignorados en `.github/dependabot.yml` porque en Windows `opensees.pyd` enlaza contra `python312.dll` y 3.13 no lo carga aunque pip lo instale.
4. **Correr mypy contra un entorno sin dependencias**: es exactamente lo que el job `lint` no hace; si se mueve allí, el conteo deja de compararse con el presupuesto y el ratchet se vuelve ruido.
5. **Cambiar la versión de ruff o de mypy en el CI sin mirar el presupuesto**: el número de `tools/mypy-budget.txt` está medido con `mypy==2.4.0`; subirlo para tapar errores nuevos está prohibido, solo puede bajar.
6. **Añadir `-m "not slow"` al CI**: oculta pruebas y hace que la cobertura baje en silencio; el marcador es para el bucle local.
7. **Fijar una acción de terceros por `@main` o por un tag móvil**: la acción compuesta local fija la de Mesa por SHA; lo contrario deja que el tag se mueva bajo los pies del flujo.
8. **Olvidar `needs: lint`**: la matriz de tres sistemas arranca aunque el formato esté mal y se gastan minutos de runner a cambio de nada.
9. **Publicar un tag sin que el bundle pase**: `desktop.yml` solo publica si `bundle` termina; el smoke test de `packaging/build.py` es lo que prueba que el paquete resuelve.
10. **Ampliar `permissions` por comodidad**: `contents: write` solo lo necesita `desktop.yml`, y solo para adjuntar archivos; en CI basta el valor por defecto de lectura.
11. **Asumir que el CI y el entorno local coinciden**: el flujo instala `-e ".[gui,dev]"` y usa `QT_QPA_PLATFORM=offscreen`; reproducir los comandos sin esas dos condiciones da fallos que el CI no tiene, y al revés.
12. **Ignorar el desajuste de mypy entre pre-commit y CI**: `.pre-commit-config.yaml` fija el hook en una revisión distinta de la que instala el CI; el conteo autoritativo es el del CI.

> ⚠️ VERIFICAR: hay tres datos que viven en GitHub, no en el árbol de trabajo, y ninguno puede afirmarse desde aquí.
> - **Protección de rama**: si `main` y `develop` la tienen y qué checks son obligatorios — `gh api repos/{owner}/{repo}/branches/main/protection` (y `.../branches/develop/protection`), o Settings → Branches. Hasta confirmarlo, esta skill describe qué comprobaciones *deberían* exigirse, no cuáles exige GitHub hoy.
> - **Secretos de firma**: si existen `MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`, `WINDOWS_CERT_PFX` y `WINDOWS_CERT_PASSWORD` — `gh secret list`, o Settings → Secrets and variables → Actions. El flujo funciona en ambos casos: los pasos de firma se omiten si el secreto no existe.
> - **Permisos por defecto del `GITHUB_TOKEN`**: deciden qué puede hacer `ci.yml`, que no declara `permissions` — `gh api repos/{owner}/{repo}/actions/permissions/workflow`. La política recomendada es `contents: read` por defecto y elevar por job.

## Interfaz de salida

- El CI expone tres checks por ejecución —`lint`, `test` y `gui`— más los derivados de la matriz, con el nombre del job y de la celda en la interfaz.
- Cada fallo llega como anotación con archivo y línea (ruff, mypy, pytest) y como log por paso; el código de salida del job es el veredicto.
- El artefacto `coverage-xml` (`coverage.xml`) se sube siempre, también cuando las pruebas fallan, y solo desde ubuntu 3.12.
- Un tag `v*` produce un release con los tres `*.zip`, `SHA256SUMS.txt` y un cuerpo con las notas tomadas de `CHANGELOG.md`.
- Lo que **no** se expone: la caché no se publica como resultado, y un archivo sin firmar no se distingue por su nombre — hay que mirar si el paso de firma se ejecutó.

## Referencias

1. `.github/workflows/ci.yml` — jobs `lint`, `test` y `gui`; versiones fijadas y umbral de cobertura.
2. `.github/workflows/desktop.yml` — `bundle` y `publish`; permisos, matriz y publicación del release.
3. `.github/actions/windows-opengl/action.yml` — acción compuesta de Mesa llvmpipe 24.3.0.
4. `.github/dependabot.yml` — agrupación de dependencias y paquetes ignorados.
5. `CONTRIBUTING.md` — comandos antes del PR, ratchet de mypy y estilo de commit.
6. `tools/typecheck.py` y `tools/mypy-budget.txt` — presupuesto de errores de mypy.
7. `pyproject.toml` — `[tool.importlinter]`, `[tool.pytest.ini_options]` y `[tool.coverage.run]`.
8. `CLAUDE.md` — trampas conocidas, incluida la suite GUI en un solo proceso.
9. GitHub Docs — *Workflow syntax for GitHub Actions*: <https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions>
10. GitHub Docs — *Caching dependencies to speed up workflows*: <https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows>
11. GitHub Docs — *Controlling permissions for GITHUB_TOKEN*: <https://docs.github.com/en/actions/security-guides/automatic-token-authentication>
12. GitHub Docs — *About protected branches*: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>; Git — *git-tag* y *git-push* (`--follow-tags`): <https://git-scm.com/docs/git-tag>

## Registro de verificación

- **Verificado (2026-02-14)**: la estructura de jobs, matrices, condiciones, pasos, versiones fijadas, umbral de cobertura, permisos de `desktop.yml`, acción compuesta de Mesa y publicador único se leyeron directamente de los archivos de `.github/` y de `tools/`.
- **Pendiente**: cerrar el bloque `VERIFICAR` (protección de rama, secretos de firma y permisos por defecto del token) contra los ajustes del repositorio; mientras siga abierto, `status` es `draft`. Confirmar además si se activan la caché de pip y el bloque `concurrency`, que hoy no existen en `ci.yml`.
