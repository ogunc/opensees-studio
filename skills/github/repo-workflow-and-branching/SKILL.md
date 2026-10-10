---
name: repo-workflow-and-branching
description: >-
  Documenta el flujo de trabajo con Git y GitHub del repositorio OpenSees
  Studio: modelo de ramas main y develop, ramas de trabajo por cambio,
  Conventional Commits, ciclo completo de un pull request con la plantilla
  del proyecto, revisión arquitectónica exigida (dirección de dependencias,
  core sin Qt ni OpenSeesPy, type hints y docstrings, trabajo de más de 50 ms
  fuera del hilo de la GUI, ratchet de mypy que solo baja), plantillas de
  issue, etiquetas e hitos, sincronización de un fork, resolución de
  conflictos, sincronización de develop con main tras una release, archivos
  que no deben versionarse y política de ramas protegidas. Úsala al abrir o
  revisar un pull request, al preparar un tag v*, al arreglar un fork
  desincronizado o al decidir en qué rama y con qué mensaje va un cambio.
metadata:
  track: github
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [devops, qa]
---

# Flujo de trabajo del repositorio y ramas

## Cuándo usar esta skill

- Hay que abrir un pull request y no está claro contra qué rama va ni qué debe contener el cuerpo.
- Una revisión pide comprobar la dirección de dependencias, el ratchet de mypy, el hilo de la GUI o la ausencia de Qt en `core/`.
- Se prepara una release por tag `v*` y hay que decidir qué exige el CHANGELOG.
- Un fork está desincronizado, el PR arrastra commits ajenos o hay conflicto en `CHANGELOG.md` o en un archivo generado.
- Alguien pregunta quién puede fusionar, qué ramas están protegidas o qué no debe versionarse.

No usar para el contrato detallado entre capas (→ `platform/platform-architecture-and-services`), la construcción y firma de los binarios (→ `packaging/README.md`) ni la formulación numérica (→ `core/fem-formulation-core`): esta skill gobierna el *cómo se entrega*, no el *qué* se calcula.

## Alcance y límites

Cubre el ciclo de vida de un cambio desde la rama hasta `main`: elección de rama base, estilo de commit, cuerpo del PR, revisión arquitectónica, fusión, borrado
de rama, sincronización de `develop` con `main`, sincronización de un fork y control de versiones de artefactos.

No cubre la redacción del CHANGELOG (prosa de producto, no de proceso), la configuración de secretos de firma, la administración del repositorio en la web de
GitHub ni la política de licencias. Tampoco decide *si* un cambio entra: solo cómo se propone, se revisa y se publica.

## Entradas y supuestos

| Dato | Si falta |
|---|---|
| Remoto de trabajo: aquí `origin` es `ogunc/opensees-studio` (upstream) y `fork` es `marcel1983/opensees-studio` | `git remote -v`; el nombre es el inverso a la convención habitual, no asumirlo |
| Rama base: `develop` para desarrollo, `main` para lo ya liberado | preguntar; un PR contra la rama equivocada se rehace |
| Issue que el PR cierra | `Closes #` puede quedar vacío solo en `chore:`/`ci:` triviales |
| Sección del CHANGELOG para el tag por publicar | el job `publish` **falla** si no existe; se escribe antes de etiquetar |
| Versión de Python del entorno | 3.12 exacto: el `.pyd` de OpenSees en Windows enlaza `python312.dll` |
| Permiso de escritura en el remoto | sin él, el cambio va por fork más PR, nunca por push directo |

## Fundamento y formulación

**1. El historial es un grafo, no una lista de carpetas.** Una rama es un puntero a un commit; `develop` es la punta de integración, `main` la punta liberada, y
una rama de trabajo es un camino que sale de `develop` y solo vuelve por fusión.

```
main      A---B-----------M2------M3      solo releases; el tag v* se pone aquí
               \         /       /
develop         C---D---E---F---G          integración continua
                     \     /
feat/x                H---I                rama de trabajo; se borra al fusionar
```

**2. Un PR es un diff más sus comprobaciones** y recorre `draft → abierto → revisado → fusionado`. Un cambio no liberado propuesto contra `main` mete commits
en la rama de la que salen las releases; `lint`, `test` y `gui` son condición de entrada, no adorno.

**3. Artefacto frente a caché.** Se versiona lo irreproducible y se ignora lo que una herramienta regenera; la prueba es si puede reconstruirse con un comando
más el contenido del repositorio.

| Se versiona | Se ignora (`.gitignore`) |
|---|---|
| `src/`, `tests/`, `tools/`, `packaging/`, `examples/*.py`, `docs/`, `skills/`, `.github/` | `.venv/`, `venv/`, `env/` |
| `pyproject.toml`, `requirements-lock.txt`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CLAUDE.md` | `build/`, `dist/`, `*.egg-info/` |
| Ejemplos `.osmodel` revisados y el `src/opensees_studio/data/` normativo con cita | `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `coverage.xml`, `*.run-snapshot.osmodel`, `results/`, `*.h5`, `scratch/` |

**4. Versionado semántico con salvedad pre-alpha.** El CHANGELOG declara Keep a Changelog y SemVer y avisa de que en pre-alpha las versiones menor y de parche
pueden cambiar el esquema `.osmodel`: el archivo lleva `schema_version` y uno más nuevo que el soportado se rechaza, no se rebaja en silencio.

**5. Mínimo privilegio y un solo publicador.** El job `publish` es el único con `permissions: contents: write`; `bundle` no toca el release. Antes cada plataforma
adjuntaba su archivo y competían por el mismo release: un nombre mal puesto reemplazó el binario de otra. Esa duplicación está prohibida.

## Procedimiento

1. **Sincronizar y crear la rama.** Prefijos `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`, `ci/` más una descripción corta en kebab-case.
   ```bash
   git remote -v                    # origin = ogunc (upstream), fork = marcel1983
   git fetch --all --prune
   git switch develop && git pull --ff-only origin develop
   git switch -c feat/portal-frame-wizard
   ```
2. **Preparar el entorno una vez por máquina.**
   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[gui,dev]" && pre-commit install
   ```
3. **Commitear en pasos atómicos con Conventional Commits**, cada uno revertible por sí solo.

   | Mensaje | Cuándo |
   |---|---|
   | `feat: add the portal frame wizard to Define` | funcionalidad visible nueva |
   | `fix: guard the run-failure report against a closed box` | corrección de un fallo real |
   | `refactor: name the copy-loop variables in commands/transforms.py` | sin cambio de comportamiento |
   | `ci: pin mypy to 2.4.0 in the lint job` | flujos de trabajo |
   | `chore: lower the mypy budget to 367` | mantenimiento, incluida la bajada del presupuesto |

4. **Pasar las compuertas locales** antes de abrir el PR, como pide `CONTRIBUTING.md`; el bucle rápido local puede usar `pytest -m "not slow"`, CI nunca.
   ```bash
   ruff check src tests && ruff format --check src tests
   python tools/typecheck.py && lint-imports
   pytest tests/unit tests/integration tests/tools
   pytest tests/gui        # un solo proceso; comprobar el código de salida
   ```
5. **Abrir el pull request**: la plantilla se carga sola y el cuerpo lleva sus cinco bloques (`Summary`, `Closes #<issue>`, tipo de cambio, las cuatro casillas
   arquitectónicas respondidas con honestidad y cómo se verificó). Un PR que toca `packaging/**` o `desktop.yml` dispara además el flujo *Desktop bundle*.
   ```bash
   git push -u fork feat/portal-frame-wizard
   gh pr create --repo ogunc/opensees-studio --base develop \
     --head marcel1983:feat/portal-frame-wizard \
     --title "feat: add the portal frame wizard" --body-file /tmp/pr.md
   ```
6. **Someter a revisión.** El revisor comprueba la dirección única `views → commands → viewmodels → services → core`; que `core/` no importe Qt ni OpenSeesPy;
   que `services/` no importe Qt salvo `services/qt_workers.py`; que `views/` no importe OpenSeesPy directo; los type hints y docstrings en lo público; la
   validación Pydantic de entidades nuevas; el trabajo de más de 50 ms fuera del hilo de la GUI; y que `tools/mypy-budget.txt` no suba.
7. **Fusionar y borrar la rama.**
   ```bash
   gh pr checks --watch
   gh pr merge --squash --delete-branch
   git switch develop && git pull --ff-only origin develop
   ```
8. **Publicar la release por tag**, con la sección del CHANGELOG ya fusionada en `main`.
   ```bash
   python tools/release_notes.py v0.0.5     # falla si el tag no tiene sección
   git switch main && git pull --ff-only origin main
   git tag -a v0.0.5 -m "v0.0.5" && git push origin v0.0.5
   gh run watch                             # bundle ×3 y después publish
   ```
9. **Devolver `main` a `develop` tras la release**, para que la integración contenga lo liberado.
   ```bash
   git switch develop
   git merge --no-ff main -m "chore: merge main back into develop after v0.0.5"
   git push origin develop
   ```
10. **Sincronizar el fork y rebasar la rama.** Si la rama quedó atrás: `git rebase origin/develop` y `git push --force-with-lease` (nunca `--force` a secas).
    ```bash
    gh repo sync marcel1983/opensees-studio --source ogunc/opensees-studio --branch develop
    git fetch fork && git switch develop && git reset --hard fork/develop
    ```
11. **Resolver conflictos.** En `CHANGELOG.md`, conservar las dos secciones y reordenar; en generados (`skills/index.json`, `*_rc.py`), regenerar, no editar.
    ```bash
    git fetch origin && git rebase origin/develop
    git add <archivos> && git rebase --continue   # o git rebase --abort y fusionar develop dentro de la rama
    ```
12. **Política de ramas y permisos.** No hay `CODEOWNERS` ni equivalente en el repositorio: la política vive en los ajustes de GitHub, no en el control de versiones.

    > ⚠️ VERIFICAR: si `main` y `develop` tienen protección de rama (revisiones exigidas, checks obligatorios, push directo prohibido), quién puede fusionar y
    > con qué estrategia. Se comprueba con `gh api repos/ogunc/opensees-studio/branches/main/protection` y `.../develop/protection` (con la cuenta `marcel1983`,
    > de solo lectura, ambas responden `404 Not Found` sin distinguir "sin protección" de "sin permiso"), sobre el fork (hoy `Branch not protected`) y en
    > *Settings → Branches*. Mientras no se compruebe, no se asume ninguna protección.

    > ⚠️ VERIFICAR: qué etiquetas e hitos son obligatorios. Hoy solo existen las etiquetas por defecto de GitHub (`bug`, `documentation`, `duplicate`,
    > `enhancement`, `good first issue`, `help wanted`, `invalid`, `question`, `wontfix`) y no hay hitos. Se comprueba con `gh label list -R
    > ogunc/opensees-studio` y `gh api repos/ogunc/opensees-studio/milestones`.

    > ⚠️ VERIFICAR: si están configurados los secretos de firma (`MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`,
    > `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`, `WINDOWS_CERT_PFX`, `WINDOWS_CERT_PASSWORD`). Los flujos omiten sus pasos si el secreto no existe, así
    > que un fork produce igualmente zip sin firmar. Se comprueba con `gh secret list -R ogunc/opensees-studio` (requiere administración) y en *Settings →
    > Secrets and variables → Actions*.

13. **Abrir issues con la plantilla.** Un fallo va por `.github/ISSUE_TEMPLATE/bug_report.yml` y una propuesta por `feature_request.yml`; son formularios YAML,
    así que los campos son obligatorios por construcción y no se abre un issue en blanco para evitarlos.

## Implementación en la plataforma

| Archivo | Papel en el flujo |
|---|---|
| `.github/workflows/ci.yml` | `lint` (ruff 0.16.8), `test` (matriz; en Linux 3.12 corre `tools/typecheck.py` y `lint-imports`; cobertura con umbral 75) y `gui`; se dispara en push y PR contra `main` y `develop`; los jobs `test` y `gui` usan la acción compuesta `.github/actions/windows-opengl/action.yml` (Mesa llvmpipe) |
| `.github/workflows/desktop.yml` | `workflow_dispatch`, tags `v*` y PR limitado a `packaging/**`; `bundle` por plataforma y un `publish` único con `contents: write` |
| `.github/dependabot.yml` | pip semanal (grupos `runtime-patch` y `qt-and-vtk`; ignora `openseespy*`) y `github-actions` en un solo grupo `actions` |
| `.github/pull_request_template.md` y `.github/ISSUE_TEMPLATE/*.yml` | bloques obligatorios del PR y formularios de issue |
| `tools/release_notes.py` | extrae la sección del CHANGELOG para el tag; falla si no existe |
| `tools/typecheck.py` + `tools/mypy-budget.txt` + `[tool.importlinter]` | ratchet de mypy (hoy 367, solo puede bajar) y capas verificadas por `lint-imports` |
| `.pre-commit-config.yaml` y `.gitignore` | ganchos locales y qué no se versiona |

## Datos normativos

No aplica. Esta skill no reproduce coeficientes normativos: el dato real vive en archivos de datos versionados con cita (`source`, `verified_on`) consumidos por
`core/codes/` y `core/design/`, con el contrato descrito en `codes/code-crosswalk-and-extension`. La "norma" de este skill es el propio repositorio:
`CONTRIBUTING.md`, `CLAUDE.md` y los archivos de `.github/`.

## Verificación y casos de prueba

| Comprobación | Comando o condición | Resultado esperado |
|---|---|---|
| Nombre y contrato del skill | `python3 skills/scripts/validate_skills.py --quiet` | 0 errores |
| Secciones y longitud | el mismo validador sobre este archivo | 12 secciones, 150–260 líneas |
| Estilo y tipos | `ruff check src tests`, `ruff format --check src tests`, `python tools/typecheck.py` | sin hallazgos; errores ≤ presupuesto (367) |
| Capas | `lint-imports` | sin violaciones |
| Pruebas | `pytest tests/unit tests/integration tests/tools` | todo pasa |
| GUI | `pytest tests/gui` | código de salida 0, no solo 0 fallos |
| CI y PR | `gh run list --workflow=ci.yml --limit 5` y `gh pr checks` | los tres jobs en verde antes de fusionar |
| Plantilla | `gh pr view <n>` | cuerpo con Summary, Closes, tipo, checklist y pruebas |
| Basura sin trackear | `git status --porcelain --ignored` | `.venv/`, `dist/`, `results/` aparecen como ignorados |
| Ignorados exactos | `git check-ignore -v .venv .pytest_cache results/ foo.h5 foo.run-snapshot.osmodel` | las cinco rutas ignoradas |
| Notas de release | `python tools/release_notes.py v9.9.9` (ausente) y `v0.0.4` (presente) | código 1 con `CHANGELOG.md has no notes`; código 0 con la sección |
| Sincronía del fork | `gh repo sync ... && git status -sb` | `## develop...fork/develop`, sin divergencia |

## Errores frecuentes y trampas

1. **Publicar un tag sin sección en el CHANGELOG.** `publish` invoca `tools/release_notes.py` con el tag y falla si no hay sección. Hoy existen los tags
   `v0.0.1`, `v0.0.3` y `v0.0.4`, el CHANGELOG cubre 0.0.2 a 0.0.4 y en GitHub solo hay la release `v0.0.1`: la sección se escribe **antes** de etiquetar.
2. **Publicar sin notas de versión.** La 0.0.4 se publicó con la página vacía mientras sus notas estaban en `CHANGELOG.md`; `tools/release_notes.py` existe para
   que eso no se repita. El cuerpo de una release no se edita a mano.
3. **Duplicar el publicador del release.** Antes cada plataforma adjuntaba su archivo al mismo release y competían; un nombre mal puesto reemplazó el binario de
   otra. Hoy hay un solo `publish` con `merge-multiple` y `SHA256SUMS.txt`; no se añade un segundo paso que suba artefactos.
4. **Hacer bump de un wheel atado al intérprete.** `openseespy`, `openseespywin` y `openseespylinux` están atados a la versión de Python (en Windows el `.pyd`
   enlaza `python312.dll`), y por eso Dependabot los ignora. Un rango relajado deja a pip instalarlos en 3.13 y el import falla en ejecución.
5. **Correr mypy contra un entorno sin dependencias.** El job `lint` no ejecuta mypy a propósito: sin dependencias instaladas el conteo no significa nada. El
   presupuesto se mide con mypy 2.4.0 (el de CI), `python_version = "3.12"` y el objetivo `src/opensees_studio`.
6. **Confundir los dos mypy.** El gancho de `pre-commit` usa `v1.10.0` y solo mira `core|services|viewmodels`; el presupuesto se mide con el mypy fijado en `ci.yml`. Pasar el gancho no prueba que el presupuesto se respete.
7. **Subir el presupuesto de mypy.** El número de `tools/mypy-budget.txt` solo puede bajar. Si una actualización de mypy, typeshed o una dependencia mueve el
   conteo, se actualiza en ese mismo commit y se dice en el mensaje; subirlo para tapar código nuevo rompe el ratchet.
8. **Versionar un entorno virtual, una caché o un artefacto de build**: `.venv/`, `venv/`, `env/`, `build/`, `dist/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `coverage.xml`.
9. **Versionar resultados o instantáneas**: `*.run-snapshot.osmodel`, `results/`, `*_results/`, `*.h5`, `*.hdf5`, `scratch/`. La instantánea es el mecanismo de recuperación ante caída y vive junto al proyecto, no en el repositorio.
10. **Versionar archivos generados** como `*_rc.py` o `skills/index.json`: se regeneran con su herramienta y sus conflictos se resuelven regenerando.
11. **Abrir el PR contra `main`** en vez de `develop`: mete en la rama liberada cambios que todavía no son release.
12. **Fusionar sin borrar la rama**: deja ramas muertas y PRs fantasma, y CI se dispara en cada push a cualquier rama.
13. **Anclar `-m "not slow"` en CI**: es comodidad del bucle local porque CI corre todo, incluidas las pruebas que lanzan intérpretes adicionales.
14. **Añadir Qt a `core/` o `services/` "solo para un tipo".** `lint-imports` lo detecta y el job `test` falla, pero el coste real es romper el uso sin interfaz.

## Interfaz de salida

- Todo PR expone: resumen, issue cerrado, tipo de cambio, checklist arquitectónico respondido y evidencia de prueba con el comando ejecutado.
- Toda revisión emite un veredicto explícito sobre las reglas arquitectónicas y sobre el presupuesto de mypy, no solo sobre el comportamiento funcional.
- Toda release expone: tag `v*`, notas tomadas del CHANGELOG, los tres zip (`OpenSeesStudio-linux`, `OpenSeesStudio-windows`, `OpenSeesStudio-macos`) y `SHA256SUMS.txt`.
- Toda afirmación de proceso que no pueda comprobarse desde el repositorio viaja como bloque `VERIFICAR` con el comando que la resuelve.

## Referencias

1. GitHub Docs — *About pull requests*, *About protected branches*, *About forks*, *About releases* (docs.github.com).
2. Git — `git-merge(1)`, `git-rebase(1)`, `git-switch(1)`, `git-check-ignore(1)`; *Pro Git*, cap. 3 (ramas) y cap. 6 (GitHub).
3. Conventional Commits 1.0.0 (conventionalcommits.org); Keep a Changelog 1.1.0; Semantic Versioning 2.0.0.
4. `.github/workflows/ci.yml` y `.github/workflows/desktop.yml` — compuertas, matrices, `bundle` y `publish` único.
5. `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml` y `.github/dependabot.yml` — plantillas, grupos y dependencias ignoradas.
6. `CONTRIBUTING.md` — setup, comandos previos al PR, reglas arquitectónicas y ratchet; `CLAUDE.md` y `docs/adr/` — trampas conocidas y decisiones de arquitectura.
7. `tools/release_notes.py`, `tools/typecheck.py`, `tools/mypy-budget.txt`; `.gitignore`; `pyproject.toml` (`[tool.importlinter]`, `[tool.mypy]`).

## Registro de verificación

- **Verificado el 2026-02-14**: los flujos `ci.yml` y `desktop.yml` con sus disparadores, matrices y jobs; el reparto de permisos con un solo publicador; las
  plantillas de PR e issue; `dependabot.yml`; el ratchet de mypy (367) y el mypy de `pre-commit` (v1.10.0); los patrones de `.gitignore` con `git check-ignore`;
  la salida de `tools/release_notes.py` con un tag inexistente; y el estado real de etiquetas, hitos y releases, consultado con `gh` contra `ogunc/opensees-studio`.
- **Pendiente**: cerrar los tres bloques `VERIFICAR` (protección de ramas y permisos de fusión, etiquetas e hitos obligatorios, secretos de firma), que requieren
  permiso de administración o la lectura de *Settings*. Mientras estén abiertos, este skill queda en `status: draft` y ninguna afirmación de protección de rama
  debe darse por buena.
