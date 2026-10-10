---
name: releases-versioning-and-distribution
description: >-
  Documenta el ciclo de publicación de OpenSees Studio: versionado semántico de
  una aplicación de escritorio, la sección de CHANGELOG.md que se convierte en
  las notas del release, el tag v* sobre main, el flujo "Desktop bundle" (matriz
  de tres sistemas, Python 3.12, smoke test del CLI, firma y notarización
  opcionales, SHA256SUMS.txt, publicador único) y la verificación posterior.
  Úsala antes de cortar un tag, al preparar la sección del changelog, cuando el
  flujo falla o publica una página vacía, y al diagnosticar un zip con el nombre
  de otra plataforma, un hash que no cuadra o un release que hay que rehacer.
metadata:
  track: github
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [devops, release]
---

# Publicación, versionado y distribución de versiones

## Cuándo usar esta skill

- Se va a cortar una versión: hace falta el orden versión → changelog → PR a `main` → tag `v*` → flujo → verificación.
- El flujo `Desktop bundle` falla en `bundle` o en `publish`, o publica una página de release vacía.
- Hay que publicar un hotfix urgente sobre una versión ya liberada.
- Un release salió mal (asset equivocado, notas erróneas, tag mal puesto) o hay que firmar, notarizar y comprobar hashes.

No cubre la CI de lint, typecheck y pruebas (`ci.yml`), que se revisa en `CONTRIBUTING.md`, ni las trampas internas del empaquetado (el shim de `vtk`, el módulo mypyc de PyVista, por qué VTK no se recorta), documentadas en `packaging/README.md`.

## Alcance y límites

| Cubre | No cubre |
|---|---|
| SemVer aplicado a una app de escritorio pre-alfa | Compatibilidad del esquema `.osmodel` (ver `CHANGELOG.md`) |
| `CHANGELOG.md` ↔ tag ↔ notas del release | Protección de rama, revisiones exigidas y reglas de tag |
| Disparadores, matriz y pasos de `desktop.yml` | Contenido del `.spec` de PyInstaller |
| Firma/notarización opcionales y sus secretos | Emisión y custodia de los certificados |
| `SHA256SUMS.txt`, retención de artefactos, publicador único | Firma reproducible o attestations de terceros |
| Hotfix y reversión de un release | Política de soporte a versiones antiguas (no existe) |

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| Versión `X.Y.Z` a publicar | se decide por el contenido: `feat` → minor, `fix` → patch, ruptura → major |
| Sección `## [X.Y.Z]` en `CHANGELOG.md` | **bloquear**: sin ella `publish` falla por diseño |
| Rama que debe shipear (`main`) | no se etiqueta; `develop` es desarrollo activo |
| CI verde del commit que se etiqueta | no se etiqueta: el push del tag no vuelve a correr `ci.yml` |
| Secretos de firma | se publica sin firmar; los pasos se omiten y el flujo sigue verde |

## Fundamento y formulación

```text
develop  ──●──●──●──●──●──●──●      desarrollo activo
                  \       \
main     ──●──●────●───●───●───●    versiones liberadas
                  │       │   └─ (futuro tag)
                 v0.0.3  v0.0.4 ──▶ release: 3 zips + SHA256SUMS.txt
```

Un tag es un ref inmutable en la práctica: nombra un commit, y el release es un objeto aparte que lo referencia. Reapuntar un tag ya consumido rompe a quien haya descargado; la corrección se publica como versión nueva. `main` es la rama etiquetable; `develop` acumula trabajo no liberado.

| | Pull request | Release |
|---|---|---|
| Cambia con | cada push | nunca (inmutable) |
| Lo produce | revisión + merge | `publish`, solo si la ref empieza por `refs/tags/` |
| Efecto externo | ninguno | descarga pública de ~700 MB por plataforma |

Artefacto frente a caché: el zip viaja dos veces. Como **artefacto de Actions** (`upload-artifact@v4`, `retention-days: 14`) vive 14 días y lo consume el job `publish`; como **asset del release** es permanente y lo lee el usuario. Un artefacto caducado no es un release perdido.

SemVer en una app de escritorio: `CHANGELOG.md` sigue Keep a Changelog y las versiones siguen SemVer, con la salvedad explícita de que el proyecto es pre-alfa y las versiones minor y patch pueden cambiar el esquema `.osmodel` (que lleva `schema_version` y rechaza un archivo más nuevo en lugar de rebajarlo). `MAJOR` = ruptura de contrato o del formato; `MINOR` = funcionalidad nueva; `PATCH` = corrección compatible, hotfix incluido. La versión vive en un solo lugar: `[tool.hatch.version]` apunta a `src/opensees_studio/__init__.py`, el mismo valor que muestra «Acerca de».

Mínimo privilegio y publicador único: `permissions: contents: write` se declara a nivel de flujo en `desktop.yml` (solo para adjuntar assets), el job `publish` es uno solo y el ámbito de escritura no se amplía. Las notas tienen un único origen:

```text
CHANGELOG.md ## [X.Y.Z] → tools/release_notes.py vX.Y.Z → release-notes.md
                                    │
                    softprops/action-gh-release@v2 (body_path)
```

`tools/release_notes.py` lanza `LookupError` —y el paso termina con código 1— si la versión no tiene sección o está vacía: mejor un flujo rojo que una página de release en blanco.

## Procedimiento

### 0. Comprobación previa (debe ser cierta antes del tag)

```bash
git switch main && git pull --ff-only && git status --porcelain   # sin cambios
python tools/typecheck.py            # ratchet de mypy: el presupuesto solo baja
lint-imports                         # dirección de dependencias
ruff check src tests && ruff format --check src tests
pytest tests/unit tests/integration tests/tools
pytest tests/gui                     # un solo proceso; comprobar el código de salida
gh run list --workflow=ci.yml --branch main --limit 3
```

`ci.yml` filtra por rama (`main`, `develop`), no por tag: el push del tag no reejecuta lint ni pruebas. La garantía es la corrida verde del commit de `main` que se etiqueta.

### 1. Fijar la versión y la sección del changelog

```bash
$EDITOR src/opensees_studio/__init__.py     # __version__ = "0.0.5", única fuente
$EDITOR CHANGELOG.md                        # ## [0.0.5] — 2026-02-20, con Added/Fixed
python tools/release_notes.py v0.0.5        # imprime la sección; salida 0
python tools/release_notes.py v9.9.9; echo $?   # has no notes for 9.9.9 → 1
```

### 2. Integrar en la rama que libera y cortar el tag

```bash
git switch -c release/0.0.5
git add CHANGELOG.md src/opensees_studio/__init__.py
git commit -m "chore(release): 0.0.5" && git push -u origin release/0.0.5
gh pr create --base main --title "Release 0.0.5" --fill     # plantilla del repositorio
git switch main && git pull --ff-only
git tag -a v0.0.5 -m "OpenSees Studio 0.0.5" && git push origin v0.0.5
```

El push del tag `v*` es el disparador: `desktop.yml` declara `on.push.tags`, `workflow_dispatch` y un `pull_request` limitado a `packaging/**` y al propio archivo del flujo.

### 3. Seguir el flujo `Desktop bundle`

| Plataforma | Comando de empaquetado | Artefacto (14 días) |
|---|---|---|
| ubuntu-latest | `xvfb-run -a python packaging/build.py --gui-smoke` | `OpenSeesStudio-linux` |
| windows-latest | `python packaging/build.py` | `OpenSeesStudio-windows` |
| macos-latest | `python packaging/build.py` | `OpenSeesStudio-macos` |

Cada `bundle` usa **Python 3.12** (el `.pyd` de OpenSees en Windows enlaza contra `python312.dll`), instala `pip install --retries 5 -e ".[gui,packaging]"`, las bibliotecas Qt/VTK del sistema en Linux (incluido `zip`) y Mesa llvmpipe en Windows con la acción compuesta `./.github/actions/windows-opengl`. El smoke test del CLI, que corre en las tres, resuelve `examples/cantilever.osmodel` (caso 1, estático «Tip-Load») con el ejecutable congelado y exige `manifest.json` y un `.h5`; `--gui-smoke` solo se añade en Linux porque abrir una ventana en la sesión hospedada no es fiable para bloquear un release.

| Firma opcional (se omite si falta el secreto) | Secretos | Momento |
|---|---|---|
| macOS | `MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD` | `codesign` sobre el bundle desempaquetado, `notarytool submit --wait`, `stapler staple` y re-zipear |
| Windows | `WINDOWS_CERT_PFX`, `WINDOWS_CERT_PASSWORD` | `signtool sign` + `signtool verify` sobre `OpenSeesStudio.exe` |

`publish` espera a las tres plataformas: descarga los artefactos con `merge-multiple: true`, escribe `SHA256SUMS.txt` (`sha256sum ./*.zip`), genera `release-notes.md` con `python tools/release_notes.py "${{ github.ref_name }}"` y publica con `softprops/action-gh-release@v2` (`body_path`, los tres zips y el archivo de hashes, `fail_on_unmatched_files: true`).

### 4. Verificación posterior

```bash
gh release view v0.0.5 --json tagName,body,assets \
  --jq '{tag: .tagName, notas: (.body|length), assets: [.assets[].name]}'
mkdir -p /tmp/rel && gh release download v0.0.5 -D /tmp/rel
cd /tmp/rel && sha256sum -c SHA256SUMS.txt
unzip -l OpenSeesStudio-linux.zip | head    # contiene OpenSeesStudio/OpenSeesStudio
```

Descomprimir y ejecutar el bundle de la plataforma propia, resolver un ejemplo y comprobar que se escriben el `.h5` y `manifest.json`.

### 5. Hotfix urgente

```bash
git switch main && git pull --ff-only && git switch -c hotfix/0.0.6
# corrección mínima + prueba que falla sin ella; sección [0.0.6] con ## Fixed
git commit -am "fix: <el fallo>" && git push -u origin hotfix/0.0.6
gh pr create --base main --fill
git switch main && git pull --ff-only
git tag -a v0.0.6 -m "OpenSees Studio 0.0.6" && git push origin v0.0.6
```

La corrección vuelve a `develop` (merge o cherry-pick) para que el siguiente release no la pierda.

### 6. Si el release salió mal

| Síntoma | Acción |
|---|---|
| `bundle` falló; nada publicado | corregir y `gh run rerun <run-id> --failed` |
| `publish` falló por tag sin sección | borrar release y tag, añadir la sección en `main`, re-etiquetar y volver a empujar |
| Asset con nombre de otra plataforma | borrar el release y republicar desde los artefactos; nunca parchear a mano |
| Notas vacías o erróneas | `gh release edit v0.0.5 --notes-file release-notes.md`, sin tocar el tag |
| Tag en el commit equivocado, nadie descargó | `gh release delete v0.0.5 --yes --cleanup-tag`, `git tag -d v0.0.5`, `git push origin :refs/tags/v0.0.5` y re-etiquetar |
| Usuarios ya descargaron | no mover el tag: publicar `0.0.6` como `PATCH` |

Comunicar la corrección en las notas de la versión nueva: editar una página en silencio no avisa a quien ya descargó.

## Implementación en la plataforma

| Ruta | Contrato |
|---|---|
| `CHANGELOG.md` | Secciones `## [X.Y.Z] — fecha`; el ayudante extrae la del tag |
| `tools/release_notes.py` | `release_notes(tag, *, changelog=CHANGELOG) -> str`; acepta `v0.0.5` o `0.0.5`; `LookupError` si falta o está vacía; CLI `python tools/release_notes.py <tag>` (0/1/2) |
| `tests/unit/test_release_notes.py` | Cubre tag con y sin `v`, sección ausente, sección vacía y changelog alternativo |
| `src/opensees_studio/__init__.py` | `__version__`, fuente única vía `[tool.hatch.version]` |
| `pyproject.toml` | `dynamic = ["version"]`; extra `packaging` para el bundle |
| `packaging/build.py` | `--no-smoke`, `--gui-smoke`, `--no-clean`, `--zip`, `--zip-only`; zip `dist/OpenSeesStudio-<linux\|windows\|macos>.zip` según `sys.platform` |
| `.github/workflows/desktop.yml` | Disparadores, matriz, firma condicional, `upload-artifact@v4` (14 días), `publish` único |
| `.github/actions/windows-opengl/action.yml` | Acción compuesta usada por `test`, `gui` y `bundle` |

## Datos normativos

No aplica. Aquí no hay edición de norma ni coeficiente que reproducir: el dato versionado es la versión del programa, en `src/opensees_studio/__init__.py` (leída por `[tool.hatch.version]`), y su historial en `CHANGELOG.md`. Los coeficientes normativos viven en el catálogo versionado descrito en `codes/code-crosswalk-and-extension`.

## Verificación y casos de prueba

| Comprobación (comando o condición) | Resultado esperado |
|---|---|
| `python tools/release_notes.py v0.0.4` | imprime la sección del changelog; salida 0 |
| `python tools/release_notes.py v9.9.9; echo $?` | `CHANGELOG.md has no notes for 9.9.9`; salida 1 |
| `python -m pytest tests/unit/test_release_notes.py -q` | todo pasa |
| `git tag --list 'v*'` antes del tag | el tag a publicar no aparece todavía |
| `python -c "import opensees_studio as m; print(m.__version__)"` | coincide con el tag sin el `v` |
| `git merge-base --is-ancestor vX.Y.Z main` | salida 0: la versión está en `main` |
| `gh run view <run-id> --json jobs --jq '.jobs[] \| .name + " " + .conclusion'` | los tres `bundle` y `publish` en `success` |
| `gh release view vX.Y.Z --json body --jq '.body \| length'` | mayor que 0: nunca página vacía |
| `gh release view vX.Y.Z --json assets --jq '[.assets[].name]'` | los tres zips más `SHA256SUMS.txt` |
| `cd /tmp/rel && sha256sum -c SHA256SUMS.txt` tras `gh release download` | cada zip `OK` |
| `unzip -l OpenSeesStudio-linux.zip \| head` | contiene `OpenSeesStudio/OpenSeesStudio` |
| Ejecutar el bundle descomprimido y resolver un ejemplo | se escriben el `.h5` y `manifest.json` |

## Errores frecuentes y trampas

1. **Publicar sin notas de versión.** Un tag sin sección produjo una página de release vacía; desde entonces `publish` ejecuta el ayudante y **falla** en vez de publicar en blanco, y un flujo rojo tras construir tres bundles es la otra cara de la misma trampa. La nota vive en `CHANGELOG.md` o no vive.
2. **Hacer bump de un wheel atado al intérprete.** `openseespy`, `openseespywin` y `openseespylinux` están excluidos en `dependabot.yml` a propósito; actualizarlos a ciegas rompe el bundle, que se construye con Python 3.12 porque el `.pyd` de Windows enlaza contra `python312.dll`.
3. **Duplicar el publicador del release.** Un job por plataforma adjuntando su archivo hace que los tres hagan PATCH del mismo release y compitan; un zip de macOS mal nombrado llegó a sustituir el de Linux. Un solo `publish`, con los artefactos reunidos, evita la carrera; el sufijo de plataforma sale de `sys.platform`, no de `os.name` (que es `posix` también en macOS).
4. **Correr mypy contra un entorno sin dependencias.** En CI el typecheck solo corre en Linux con 3.12 y con las dependencias instaladas; contra un entorno pelado el conteo no significa nada y el presupuesto (`tools/mypy-budget.txt`) solo puede bajar.
5. **Firmar después de comprimir.** La firma se aplica al bundle desempaquetado y la compresión va después; en macOS, tras `stapler staple` hay que reescribir el zip para que el ticket viaje en lo descargado. De ahí `--zip-only`.
6. **Dar por hecho que los binarios están firmados.** Los pasos se omiten si el secreto no existe y un fork produce zips sin firmar que funcionan pero disparan Gatekeeper/SmartScreen; el camino de firma aún no se ha probado contra un certificado real (`packaging/README.md`, «Signing»).
7. **Confundir artefacto de Actions con asset del release.** Los artefactos caducan a los 14 días; los assets, no. Un artefacto ausente no significa release perdido.
8. **Mover un tag ya publicado.** El tag nombra un commit: reapuntarlo cambia lo que descarga quien llega después. Si alguien ya descargó, se publica un `PATCH`.
9. **Etiquetar `develop` o suponer que el tag reejecuta la CI.** El tag va sobre `main`; `ci.yml` filtra por rama, así que la corrida verde que respalda la versión es la del commit etiquetado. La corrección de un hotfix vuelve a `develop`.

## Interfaz de salida

| Salida | Dónde | Contenido |
|---|---|---|
| Tag | repositorio | `vX.Y.Z` sobre `main` |
| Página de release | GitHub Releases | cuerpo con la sección del changelog; sin firmar si no hay secretos |
| Assets | release | los tres `OpenSeesStudio-<plataforma>.zip` y `SHA256SUMS.txt` |
| Artefactos de flujo | Actions | los tres zips, `retention-days: 14` |
| Instrucciones de integridad | `packaging/README.md` | `sha256sum -c`, `shasum -a 256 -c`, `certutil -hashfile` |
| Aviso de firma | README del proyecto | Gatekeeper/SmartScreen cuando no hay certificado |

Cada release deja versión, fecha, sección del changelog, hashes y los tres zips, y responde «¿este binario es el de este tag?» con `sha256sum -c SHA256SUMS.txt`.

## Referencias

1. GitHub Docs — *Managing releases*: https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
2. GitHub Docs — *Workflow syntax* (`permissions`, `matrix`, `needs`, `if`) y *Events that trigger workflows* (`push.tags`, `workflow_dispatch`): https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions
3. GitHub Docs — *Store and share data* (`upload-artifact`, `download-artifact`, retención): https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/store-and-share-data
4. GitHub CLI — `gh release` (`create`, `edit`, `delete`, `download`, `view`): https://cli.github.com/manual/gh_release
5. `softprops/action-gh-release` v2 (`body_path`, `fail_on_unmatched_files`): https://github.com/softprops/action-gh-release
6. Git — `git-tag(1)`: https://git-scm.com/docs/git-tag
7. Semantic Versioning 2.0.0: https://semver.org/spec/v2.0.0.html · Keep a Changelog 1.1.0: https://keepachangelog.com/en/1.1.0/
8. `.github/workflows/desktop.yml`, `.github/workflows/ci.yml`, `.github/actions/windows-opengl/action.yml` — flujos y acción compuesta.
9. `tools/release_notes.py`, `tests/unit/test_release_notes.py`, `packaging/build.py`, `packaging/README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `.github/dependabot.yml`, `pyproject.toml`, `src/opensees_studio/__init__.py`.

## Registro de verificación

- **Verificado el 2026-02-14** contra el repositorio: `desktop.yml` (disparadores, matriz y nombres de artefacto, `permissions: contents: write`, firma condicional, re-zip de macOS, `publish` único con `SHA256SUMS.txt` y `release_notes.py`), `ci.yml` (jobs y filtro por rama), `tools/release_notes.py` y su prueba, `packaging/build.py` (`--zip-only`, `--gui-smoke`, smoke sobre `examples/cantilever.osmodel`, sufijo de `sys.platform`), `packaging/README.md`, `CONTRIBUTING.md`, `pyproject.toml` y `src/opensees_studio/__init__.py` (`__version__ = "0.0.4"`).
- **Estado observado de tags y changelog**: `git tag` lista `v0.0.1`, `v0.0.3` y `v0.0.4`; `CHANGELOG.md` tiene secciones para `0.0.4`, `0.0.3` y `0.0.2`. Las discrepancias históricas no afectan a un tag nuevo, que debe tener su sección.
- **Pendiente**: cerrar las verificaciones de abajo antes de pasar la skill a `ready`.

> ⚠️ VERIFICAR: no consta en el repositorio qué protege `main`: protección de rama, revisiones exigidas, reglas de tag ni quién puede empujarlos; tampoco el propietario y el remoto reales. Se comprueba con `gh repo view --json nameWithOwner,defaultBranchRef`, `gh api repos/{owner}/{repo}/branches/main/protection` y `gh api repos/{owner}/{repo}/rulesets`, o en Settings → Branches/Rules. `pyproject.toml` apunta a `github.com/ogunc/opensees-studio`, pero un fork tiene otro `nameWithOwner` y los comandos `gh` de esta skill asumen el repositorio del checkout. Mientras no se confirme, esta skill no afirma que un PR no pueda saltarse la revisión.

> ⚠️ VERIFICAR: la existencia de los secretos de firma (`MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`, `WINDOWS_CERT_PFX`, `WINDOWS_CERT_PASSWORD`) no es visible desde el código; se comprueba con `gh secret list` (permisos de administración) o en Settings → Secrets and variables → Actions. Si faltan, el release sale sin firmar y el flujo sigue verde.

> ⚠️ VERIFICAR: la firma y notarización están escritas pero no se han ejercitado contra un certificado real (`packaging/README.md`, «Signing»). Se comprueba en el primer release firmado, revisando los pasos «Sign and notarize (macOS, when configured)» y «Sign (Windows, when configured)» y validando el binario con `codesign --verify` / `signtool verify`.
