---
name: gh-cli-and-collaboration
description: >-
  Opera el repositorio con la CLI de GitHub y su flujo de colaboración:
  autenticación y scopes, remotos y bifurcaciones, incidencias, pull requests
  con la plantilla del proyecto, revisiones con comentarios de línea,
  estrategias de fusión, ejecuciones y artefactos de los flujos de trabajo, la
  API para lo que no tiene subcomando, releases, secretos y variables. Úsala
  cuando haya que abrir o revisar un PR contra main o develop, esperar a que
  pasen las comprobaciones de CI, descargar el artefacto coverage-xml, disparar
  el empaquetado de escritorio a demanda, inspeccionar o publicar un tag v*, o
  automatizar cualquiera de esas tareas en bash; también ante errores de
  autenticación, listados truncados por paginación o consultas --json mal
  escritas.
metadata:
  track: github
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [devops]
---

# CLI de GitHub y flujo de colaboración

## Cuándo usar esta skill

- Hay que abrir un PR contra `main` o `develop` con el cuerpo de la plantilla del repositorio, o revisar el que ya está abierto.
- CI falla y hay que identificar el job y el paso exactos: `lint`, `test`, `gui` o el empaquetado de escritorio.
- Se necesita un dato que ningún subcomando `gh` expone (protección de rama, artefactos de una ejecución, comentario en una línea del diff), o hay que disparar a mano el flujo «Desktop bundle» y descargar sus `.zip`, o inspeccionar los activos de un release y su `SHA256SUMS.txt`.
- Se configuran secretos o variables de CI (firma de macOS/Windows, o secretos de Dependabot), o se automatiza en bash la espera de comprobaciones de un PR y el listado de incidencias etiquetadas.
- Se depura un `404`, un `403` de scope insuficiente o un listado que devuelve solo los primeros 30 elementos.

**No usar** para decidir dónde vive un módulo o qué capa importa qué (→ `platform/platform-architecture-and-services`), ni para formulación o coeficientes normativos de otras pistas.

## Alcance y límites

Cubre el uso práctico de `gh` y `git` contra este repositorio: autenticación y scopes, remotos, incidencias, pull requests, revisiones, fusiones, ejecuciones, artefactos, releases, secretos, variables y automatización en bash. No cubre escribir o modificar los flujos de `.github/workflows/`, la política de ramas ni la administración de la organización, y no decide si un cambio es correcto: solo lo entrega, lo revisa y lo publica. Se asume `develop` para desarrollo activo, `main` para versiones liberadas y CI disparado en `push` y `pull_request` contra ambas.

## Entradas y supuestos

| Dato | Obligatorio | Si falta |
|---|---|---|
| Repositorio `OWNER/REPO` | sí | se infiere del remoto con `gh repo view --json nameWithOwner` |
| Rama base (`develop` o `main`) | sí | nunca se asume: `--base develop` explícito |
| `gh` autenticado con scopes suficientes | sí | `gh auth status`; si falla, detenerse y no inventar un token |
| Número de PR o de ejecución | no | se obtiene de la rama actual o de `gh run list` |

## Fundamento y formulación

### 1. Grafo de commits y refs
Git es un grafo acíclico dirigido de commits; una rama es un puntero móvil y un tag un puntero fijo. La estrategia de fusión cambia la forma del grafo, no solo el historial:

```
--merge   main: A---B---C-------M      M = merge commit
--squash  main: A---B---C---S          S = un commit por PR
--rebase  main: A---B---C---D'--E'     commits reescritos
```

Un `push --force` sobre una rama con PR abierto rompe el grafo que otros ya descargaron: se usa `--force-with-lease`, nunca `--force` a secas.

### 2. Estado de un pull request
```
draft ─ready─▶ open ─approve─▶ open ─merge(CLEAN)─▶ merged
                 │  └─changes─▶ changes_requested ─approve─▶ open
                 └─checks: pending ─▶ success | failure    └─close─▶ closed
```

| Campo JSON | Significado | Acción |
|---|---|---|
| `mergeable` | `MERGEABLE`, `CONFLICTING`, `UNKNOWN` | `UNKNOWN` obliga a reintentar: GitHub lo calcula en diferido |
| `mergeStateStatus` | `CLEAN`, `BLOCKED`, `BEHIND`, `DIRTY`, `DRAFT`, `UNSTABLE` | `BEHIND` exige actualizar la rama; `BLOCKED`, revisión o check |
| `statusCheckRollup` | checks con su `conclusion` | `null` mientras corren; no es un fallo |
| `headRefOid` | SHA de la cabeza | es el `commit_id` de un comentario de línea |

### 3. Artefacto, caché y ejecución
| Concepto | Vida | Inmutable | Comando |
|---|---|---|---|
| Ejecución (*run*) | historial del flujo | sí | `gh run list`, `gh run view` |
| Artefacto | adjunto a una ejecución, con retención (14 días aquí) | sí | `gh run download` |
| Caché de acciones | clave con expiración, desalojable | no | no se descarga desde `gh` |

Un artefacto es la prueba de lo que produjo una ejecución; una caché solo evita trabajo y nunca se cita como evidencia.

### 4. Versionado semántico y publicación
Los tags `v*` publican. La nota de versión no se escribe a mano en el PR ni en el release: se toma de `CHANGELOG.md` con `tools/release_notes.py <tag>`, que falla si el tag no tiene sección. Hay un solo publicador a propósito (el job `publish` de «Desktop bundle»): antes cada plataforma adjuntaba su archivo y competían por el mismo release.

### 5. Mínimo privilegio
| Scope del token | Para qué | Síntoma si falta |
|---|---|---|
| `repo` | incidencias, PR, releases, artefactos | `404` en repositorio privado |
| `workflow` | `gh workflow run`; push que toca `.github/workflows/` | `403` «refusing to allow a token to create or update workflow» |
| `read:org` | listar miembros y equipos | `403` al pedir revisores por equipo |

`GH_TOKEN` / `GITHUB_TOKEN` tienen prioridad sobre la sesión guardada: un token de CI exportado en la shell explica la mayoría de los `403` «inexplicables». Los secretos se leen, nunca se imprimen; las variables son texto plano y no sirven como credenciales.

## Procedimiento

1. **Autenticarse y comprobar el contexto.**
   ```bash
   gh auth status && gh auth login --hostname github.com --web
   gh auth refresh -s workflow,read:org          # solo si falta un scope
   gh repo view --json nameWithOwner,defaultBranchRef
   ```
2. **Clonar y fijar remotos** (en un fork, `origin` es el fork y `upstream` el canónico).
   ```bash
   gh repo clone OWNER/REPO && cd REPO
   gh repo fork --remote --remote-name origin    # bifurcar el repo actual
   git switch -c feat/mi-cambio develop
   ```
3. **Trabajar contra la incidencia** y vincularla con `Closes #N` en el cuerpo del PR.
   ```bash
   gh issue list --state open --label bug --limit 100 \
     --json number,title --jq '.[] | "\(.number)\t\(.title)"'
   gh issue create --title "fix: resultado vacío en modo modal" --body "Pasos…" --label bug
   gh issue comment 42 --body "Reproducido en develop." && gh issue close 42 --reason "not planned"
   ```
4. **Abrir el PR con el cuerpo de la plantilla** (la plantilla no se rellena sola al crear por API).
   ```bash
   git push -u origin HEAD
   gh pr create --base develop --title "fix: corrige el modo modal" \
     --body-file .github/pull_request_template.md --draft
   gh pr ready
   ```
5. **Leer el PR y su diff.**
   ```bash
   gh pr view --json number,url,state,mergeable,mergeStateStatus,headRefOid
   gh pr diff && gh pr status
   ```
6. **Esperar las comprobaciones** (los jobs `lint`, `test` y `gui`).
   ```bash
   gh pr checks --watch --fail-fast
   gh pr checks --required          # solo los exigidos por la rama
   gh run list --workflow=ci.yml --limit 10 --json databaseId,status,conclusion,headBranch
   ```
7. **Revisar.** `gh pr review` solo acepta el cuerpo general; la línea va por la API con el SHA de la cabeza.
   ```bash
   gh pr review 123 --comment --body "Revisión de la dirección de dependencias."
   gh pr review 123 --request-changes --body "Falta prueba unitaria."
   gh api "repos/{owner}/{repo}/pulls/123/comments" \
     -f body='Aquí falta el type hint de retorno.' \
     -f path='src/opensees_studio/core/model.py' -F line=42 -f side=RIGHT \
     -f commit_id="$(gh pr view 123 --json headRefOid --jq .headRefOid)"
   ```
8. **Fusionar** con la estrategia elegida y borrar la rama.
   ```bash
   gh pr merge 123 --squash --delete-branch     # o --merge / --rebase
   ```
9. **Inspeccionar ejecuciones y descargar artefactos.**
   ```bash
   gh run view --log-failed && gh run watch --exit-status && gh run rerun --failed
   gh run download --name coverage-xml --dir /tmp/cov
   gh run download --pattern '*windows*' --dir /tmp/dist
   ```
10. **Usar la API para lo que no tiene subcomando**, con `--jq` y paginación.
    ```bash
    gh api repos/{owner}/{repo}/branches/main/protection
    gh api repos/{owner}/{repo}/actions/runs --paginate \
      --jq '.workflow_runs[] | select(.conclusion=="failure") | .databaseId'
    gh api repos/{owner}/{repo}/releases --paginate --jq '.[].tag_name'
    ```
11. **Releases:** comprobar la nota de versión y los activos antes de publicar o descargar.
    ```bash
    python tools/release_notes.py v0.4.0 > /tmp/notes.md
    gh release view v0.4.0 --json tagName,assets --jq '.assets[].name'
    gh release download v0.4.0 --pattern '*.zip' --dir dist
    ```
12. **Secretos, variables y disparo a demanda del empaquetado.**
    ```bash
    gh secret list && gh secret set MACOS_CERT_P12 --body "$(base64 < cert.p12)"
    gh variable set OPENSEES_MIRROR --body "https://…"
    gh workflow list && gh workflow run desktop.yml --ref main
    ```
13. **Recetas de automatización.**
    ```bash
    # PR de la rama actual (cadena vacía si no hay)
    PR=$(gh pr view --json number --jq '.number' 2>/dev/null || true)
    PR=${PR:-$(gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --state open \
      --limit 1 --json number --jq '.[0].number // empty')}
    # Esperar el CI de la rama actual hasta que termine
    RID=$(gh run list --workflow=ci.yml --limit 20 --json databaseId,headBranch \
      --jq ".[] | select(.headBranch==\"$(git rev-parse --abbrev-ref HEAD)\") | .databaseId" | head -1)
    gh run watch "$RID" --exit-status || echo "CI en rojo: $RID"
    # Incidencias etiquetadas, sin abrir el paginador
    GH_PAGER= gh issue list --label bug --state open --limit 100 \
      --json number,title --jq '.[] | "#\(.number) \(.title)"'
    ```

## Implementación en la plataforma

La pista `github` no añade código al paquete: opera sobre los artefactos de proceso que ya existen.

| Elemento del repositorio | Cómo se opera desde `gh` |
|---|---|
| `.github/workflows/ci.yml` (jobs `lint`, `test`, `gui`) | `gh pr checks`, `gh run view --log-failed`, `gh run rerun --failed` |
| `.github/workflows/desktop.yml` («Desktop bundle») | `gh workflow run desktop.yml`, `gh run download` de `OpenSeesStudio-*` |
| job `publish` (solo si la referencia es `refs/tags/`) | `gh release view`, `gh release download`, `SHA256SUMS.txt` |
| `.github/pull_request_template.md` y `.github/ISSUE_TEMPLATE/*.yml` | `gh pr create --body-file`; `gh issue create` (los formularios son de la web) |
| `.github/dependabot.yml` | sus PR se revisan y fusionan como cualquier otro |
| `tools/release_notes.py` + `CHANGELOG.md` | nota de versión; sin sección, el tag no se publica |

Si la automatización necesita un script, vive en `tools/` con type hints y docstring, y su prueba en `tests/tools/`. Un script que solo orquesta `gh` no pertenece a `src/`: no es código del producto.

## Datos normativos

No aplica: esta skill no reproduce coeficientes de norma. El dato real que gobierna la publicación vive en `CHANGELOG.md` (sección `## [X.Y.Z]`), en `.github/workflows/desktop.yml` (gatillos y retención) y en el repositorio remoto (protección de rama, secretos), que se consulta con `gh api`.

> ⚠️ VERIFICAR: no se pudo comprobar si `main` y `develop` tienen protección de rama, revisiones exigidas o checks obligatorios. Se comprueba con `gh api repos/{owner}/{repo}/branches/main/protection` (404 = sin protección) y `gh api repos/{owner}/{repo}/rulesets`.

> ⚠️ VERIFICAR: no se pudo comprobar si el repositorio permite auto-fusión ni qué estrategias de fusión están habilitadas. Se comprueba con `gh repo view --json autoMergeAllowed,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed,deleteBranchOnMerge`.

> ⚠️ VERIFICAR: no se pudo comprobar si existen los secretos de firma (`MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`, `WINDOWS_CERT_PFX`, `WINDOWS_CERT_PASSWORD`); los pasos de firma se omiten si el secreto no existe. Se comprueba con `gh secret list` (requiere administración) y en los ajustes del repositorio.

> ⚠️ VERIFICAR: no se pudo comprobar el nombre de los remotos de este clon (`origin` frente a un `upstream` de fork). Se comprueba con `git remote -v` y `gh repo view --json nameWithOwner,isFork,parent`.

## Verificación y casos de prueba

| Comprobación | Comando | Resultado esperado |
|---|---|---|
| Sesión válida y scopes | `gh auth status` | sin errores; incluye `repo` y `workflow` |
| Checks en verde | `gh pr checks --watch --fail-fast` | salida 0 |
| Artefacto de cobertura | `gh run download --name coverage-xml -D /tmp/cov` | `coverage.xml` presente |
| Nota de versión | `python tools/release_notes.py v0.4.0` | texto no vacío; error si falta la sección |
| Activos del release | `gh release view v0.4.0 --json assets --jq '.assets[].name'` | los `OpenSeesStudio-*` y `SHA256SUMS.txt` |
| Comentario de línea | `gh api repos/{owner}/{repo}/pulls/123/comments` | el comentario con su `path` y `line` |
| Paginación completa | `gh api repos/{owner}/{repo}/releases --paginate --jq 'length'` | igual al número real de releases |
| Empaquetado a demanda | `gh workflow run desktop.yml --ref main` | nueva ejecución visible en `gh run list` |

## Errores frecuentes y trampas

1. **Publicar sin notas de versión.** Un tag sin sección en `CHANGELOG.md` deja la página del release vacía; `tools/release_notes.py` existe para que el paso falle en vez de publicar en blanco.
2. **Duplicar el publicador del release.** Si cada plataforma adjunta su archivo al mismo release, compiten y un nombre mal puesto reemplaza el de otra plataforma; por eso hay un solo job `publish`.
3. **Hacer bump de un wheel atado al intérprete.** `openseespywin` y `openseespylinux` se ignoran en Dependabot: el `.pyd` de Windows enlaza contra `python312.dll` y subir la versión de Python rompe el binario aunque pip instale el wheel.
4. **Correr mypy contra un entorno sin dependencias.** El conteo de errores no significa nada; por eso el job `lint` no lo ejecuta y el presupuesto se mide con `python tools/typecheck.py` en el job `test` de Linux con 3.12.
5. **Fusionar sin mirar `mergeStateStatus`.** `UNKNOWN` no es «listo» (GitHub calcula la fusionabilidad en diferido) y `BEHIND` exige actualizar la rama.
6. **Creer que `gh pr review` admite comentarios de línea.** Solo acepta el cuerpo general; la línea se publica por la API con `commit_id`, `path`, `line` y `side`, y da `422` («line must be part of the diff») si la línea no está en un hunk o el SHA ya cambió.
7. **Autenticación mal diagnosticada.** Un push que toca `.github/workflows/` sin scope `workflow` se rechaza con `403` (se arregla con `gh auth refresh -s workflow`), y un `GH_TOKEN` exportado en la shell tiene prioridad sobre la sesión guardada y produce `403`/`404` que no se explican por el login.
8. **Confundir artefacto con caché.** La caché es desalojable y no prueba nada; el artefacto sí, pero caduca (14 días en «Desktop bundle»).
9. **Listados truncados.** `gh issue list`, `gh pr list` y compañía devuelven una página (30 por defecto): hay que pasar `--limit` y, en `gh api`, `--paginate`; sin él, cualquier recuento es falso.

## Interfaz de salida

El agente reporta: repositorio y rama base; número y URL del PR (o de la incidencia); resultado de `gh pr checks` con los jobs en rojo y su paso exacto; si hubo revisión, el tipo (`--comment`, `--approve`, `--request-changes`) y los comentarios de línea como `path:line`; la estrategia de fusión aplicada y el SHA resultante; y, si hubo publicación, el tag, los activos descargados y el contenido de `release-notes.md` / `SHA256SUMS.txt`. Todo dato que se afirme sobre protección de rama, secretos o revisores exigidos viaja con su comando de comprobación, no como suposición.

## Referencias

1. GitHub CLI, manual y páginas de cada subcomando (`gh help`, `gh pr help`, `gh api help`, `gh run help`) — <https://cli.github.com/manual/>.
2. GitHub REST API, «Pull request review comments» y «Actions» — <https://docs.github.com/rest>.
3. Git, `git help commit`, `git help push` (`--force-with-lease`), `git help rebase` — <https://git-scm.com/docs>.
4. Pro Git, cap. 3 «Git Branching» (grafo de commits y fusiones).
5. `.github/workflows/ci.yml` y `.github/workflows/desktop.yml` — jobs `lint`, `test`, `gui`, «Desktop bundle» con su matriz de artefactos, y job `publish` con un solo publicador.
6. `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/bug_report.yml` y `feature_request.yml`, y `.github/dependabot.yml` — plantillas de colaboración y grupos de actualización.
7. `CONTRIBUTING.md` y `CLAUDE.md` — comandos previos al PR, reglas arquitectónicas y trampas conocidas.
8. `CHANGELOG.md` y `tools/release_notes.py` — fuente de la nota de versión.
9. `tools/typecheck.py`, `tools/mypy-budget.txt` y `pyproject.toml` (`[tool.importlinter]`, dependencias, `requires-python`).

## Registro de verificación

- **Verificado el 2026-02-14**: gatillos y jobs de `.github/workflows/ci.yml` y `desktop.yml`, plantillas de `.github/`, grupos de Dependabot, comandos de `CONTRIBUTING.md` y mecánica de `tools/release_notes.py` contra `CHANGELOG.md`.
- **Pendiente**: los cuatro avisos `VERIFICAR` de «Datos normativos» (protección de rama, auto-fusión y estrategias, secretos de firma, nombre de los remotos). Los cierra quien tenga administración del repositorio; al hacerlo, esta skill pasa a `status: ready`.
- **Mantenimiento**: revisar si cambian los nombres de los flujos, la retención de artefactos o la política de ramas.
