---
name: security-and-supply-chain
description: >-
  Gobierna la seguridad del repositorio y de la cadena de suministro de OpenSees
  Studio: mínimo privilegio del token del flujo, secretos frente a variables,
  rotación de los secretos de firma, protección de ramas y reglas de revisión,
  firma de commits y tags, análisis de secretos filtrados y protección de push,
  alertas de Dependabot frente a los grupos runtime-patch y qt-and-vtk y frente a
  la exclusión deliberada de los wheels de OpenSees atados al intérprete, fijado
  de acciones por SHA, análisis estático, SBOM y atestaciones de procedencia, y
  política de divulgación. Úsala al tocar `.github/workflows/`,
  `.github/dependabot.yml` o `.pre-commit-config.yaml`, al publicar un tag `v*`,
  al rotar un secreto de firma o al atender una alerta de seguridad.
metadata:
  track: github
  jurisdiction: agnostic
  edition: "n/a"
  status: draft
  verified_on: "2026-02-14"
  scope: [devops, security]
---

# Seguridad del repositorio y de la cadena de suministro

## Cuándo usar esta skill

- Se edita `.github/workflows/ci.yml`, `.github/workflows/desktop.yml`, `.github/actions/windows-opengl/action.yml`, `.github/dependabot.yml` o `.pre-commit-config.yaml` y hay que decidir permisos, secretos o versiones de acción.
- Se publica un tag `v*` y hay que comprobar que el release y sus archivos son verificables.
- Se añade, rota o retira un secreto de firma, o se investiga por qué un paso de firma se omitió.
- Llega una alerta de Dependabot, de análisis de secretos o de análisis de código, o un reporte privado de vulnerabilidad.
- Se revisa un PR que toca `packaging/**` o `.github/**`: es un cambio de cadena de suministro, no de producto.
- **No** se usa para decidir dónde vive una funcionalidad (→ `platform/platform-architecture-and-services`) ni para redactar las notas de una versión desde `CHANGELOG.md` (→ skill de versionado y publicación del track `github`).

## Alcance y límites

Cubre: permisos del `GITHUB_TOKEN`, secretos y variables, protección de ramas y firmas, dependencias del CI y de pre-commit, integridad de los artefactos publicados y divulgación de vulnerabilidades.

No cubre: seguridad del código de la aplicación, criptografía de los certificados ni cumplimiento legal. El análisis estático admisible aquí es `ruff`, `mypy` con presupuesto e `import-linter`; ningún flujo del repositorio ejecuta un escáner de seguridad de código, y añadirlo es una decisión de repositorio, no de código.

Supuestos: un solo repositorio en GitHub con Actions como CI; la entrega al usuario es un zip por plataforma publicado desde un tag `v*`; quien aplica esta skill tiene permiso de administración (si no lo tiene, solo puede proponer el cambio y debe declararlo).

## Entradas y supuestos

| Dato | Cómo se obtiene | Si falta |
|---|---|---|
| Repositorio y rol del operador | `gh repo view --json nameWithOwner` | no tocar ajustes; reportar |
| Permiso por defecto del `GITHUB_TOKEN` | `gh api repos/$REPO/actions/permissions/workflow` | **no asumirlo**: bloquear la decisión |
| Permisos declarados en cada flujo | `grep -n "permissions" .github/workflows/*.yml` | leer el archivo completo a mano |
| Secretos y variables (nombres, nunca valores) | `gh secret list`; `gh variable list` | no rotar a ciegas |
| Protección de ramas y reglas de revisión | `gh api repos/$REPO/rulesets`; `/branches/main/protection` | no prometer que CI bloquea un merge |
| Firmas de commits y tags exigidas | `gh api repos/$REPO/branches/main/protection/required_signatures` | no afirmar que están exigidas |
| Alertas activas | `gh api repos/$REPO/dependabot/alerts?state=open` | no cerrar un reporte sin evidencia |
| SHA de una versión de acción | `gh api repos/<org>/<action>/git/ref/tags/<tag> --jq .object.sha` | no fijar a un tag mutable |

> ⚠️ VERIFICAR: el permiso por defecto del `GITHUB_TOKEN` y quién puede cambiarlo —
> `gh api repos/$REPO/actions/permissions/workflow`, o Settings → Actions → General
> → Workflow permissions.

> ⚠️ VERIFICAR: si `main` y `develop` tienen protección o ruleset (revisiones
> obligatorias, checks requeridos, force-push prohibido, firmas exigidas) —
> `gh api repos/$REPO/branches/develop/protection` (404 = sin protección) y
> `gh api repos/$REPO/rulesets`; en la interfaz, Settings → Rules.

> ⚠️ VERIFICAR: qué secretos de firma existen y su caducidad (`MACOS_CERT_P12`,
> `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`,
> `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`, `WINDOWS_CERT_PFX`,
> `WINDOWS_CERT_PASSWORD`) — `gh secret list` y la ficha del certificado. Los pasos
> de firma se omiten en silencio si el secreto no existe.

## Fundamento y formulación

**Grafo de commits y estado de un PR.** Un tag es un puntero a un commit, no una copia: sin protección de rama, un force-push puede dejar el tag apuntando a un árbol que nadie revisó. Un PR es una propuesta cuyos checks van ligados a un `head_sha`: aprobar y luego empujar no es la misma revisión.

```text
main      A---B---C---(tag v0.4.0)
               \         \
develop         D---E---F---G
                     \
feature/security      H---I    <- cada push mueve los checks del PR

trazabilidad exigida:  tag -> commit -> run -> digest del artefacto
```

**Mínimo privilegio.** Si un flujo o un job declara `permissions`, los ámbitos no listados quedan en `none`; sin bloque `permissions` se aplica el valor por defecto del repositorio. Un bloque a nivel de flujo lo heredan **todos** sus jobs.

| Ámbito | Para qué se necesita aquí | Quién |
|---|---|---|
| `contents: read` | clonar el repositorio | todos los jobs |
| `contents: write` | crear el release y adjuntar los zip | solo `publish` |
| `id-token: write` | firma de la atestación por OIDC | solo `publish` (si se atestigua) |
| `attestations: write` | publicar la procedencia | solo `publish` (si se atestigua) |

**Artefacto frente a caché.** El zip publicado es inmutable y verificable con `SHA256SUMS.txt` y, si existe, con una atestación. Una caché de Actions se reescribe en cada corrida y no tiene comprobación de integridad: acelera la instalación de dependencias, nunca es prueba de lo entregado.

**Secretos frente a variables.** `secrets.*` se enmascara en los registros y no se entrega a los PR de fork; `vars.*` es texto plano visible en registros y en el YAML. Un secreto promovido a `env:` de job queda en el entorno de **todos** sus pasos: eso hace hoy `desktop.yml` con los dos secretos de certificado, porque un `if:` de paso no puede leer `secrets`.

**Versionado semántico y ABI.** El proyecto versiona con SemVer y avisa de que es pre-alpha: los cambios del esquema `.osmodel` pueden llegar en minor o patch. Los wheels de OpenSees son otra cosa: `openseespywin` y `openseespylinux` 3.8.0.0 exigen 3.12 y en Windows `opensees.pyd` enlaza contra `python312.dll`. Un bump de esas tres distribuciones no es una actualización de versión, es un cambio de intérprete; por eso quedan excluidas en Dependabot.

## Procedimiento

1. **Reconocer el estado real**, que no vive en el árbol de trabajo:

```bash
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
gh api "repos/$REPO" --jq '.permissions, .security_and_analysis'
gh api "repos/$REPO/actions/permissions/workflow"
for b in main develop; do gh api "repos/$REPO/branches/$b/protection" >/dev/null 2>&1 \
  && echo "$b protegida" || echo "$b SIN protección"; done
gh secret list; gh variable list
```
2. **Fijar los permisos por job**: mínimo en el flujo, elevación solo en el publicador. Hoy `desktop.yml` declara `contents: write` a nivel de flujo, así que el job `bundle` —que ejecuta `pip install` de terceros— también podría escribir en el repositorio:

```yaml
permissions:
  contents: read          # mínimo del flujo
jobs:
  publish:
    permissions:
      contents: write     # crear el release y adjuntar los zip
      id-token: write     # OIDC para la atestación
      attestations: write # publicar la procedencia
```
3. **Separar secreto de variable**: material de firma por `gh secret set`, configuración no sensible por `gh variable set`; un secreto nunca se imprime ni viaja por la línea de comandos de un paso que lo registre.
4. **Rotar los secretos de firma**: generar el par nuevo, cargarlo, comprobar la lista y revocar el certificado anterior en la autoridad.

```bash
base64 -w0 cert.p12 > cert.p12.b64
gh secret set MACOS_CERT_P12 < cert.p12.b64
gh secret list --json name,updatedAt
```
5. **Comprobar la firma local de commits y tags**; no se afirma que el repositorio las exija: `git config --get commit.gpgsign`, `git log --show-signature -3`, `git tag -v v0.4.0`.
6. **Fijar cada acción por SHA** con el tag como comentario. Hoy solo lo hace `.github/actions/windows-opengl/action.yml` con `pyvista/setup-headless-display-action@c103a2ff... # v5.1.0`; los demás `uses:` van por etiqueta:

```bash
gh api repos/actions/checkout/git/ref/tags/v4 --jq .object.sha
# -> uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4
```
7. **Revisar dependencias sin tocar lo atado al intérprete.** Los grupos vigentes son `runtime-patch` (pydantic, numpy, h5py, imageio, pyqtgraph; minor y patch) y `qt-and-vtk` (PySide6, shiboken6, vtk, pyvista; solo patch); `openseespy`, `openseespywin` y `openseespylinux` están ignorados a propósito:

```bash
gh api "repos/$REPO/dependabot/alerts?state=open" \
  --jq '.[] | [.security_advisory.severity, .dependency.package.name] | @tsv'
gh api "repos/$REPO/automated-security-fixes"
```
8. **Verificar el artefacto, no la corrida**: `sha256sum -c SHA256SUMS.txt` y, si hay atestación, `gh attestation verify dist/OpenSeesStudio-linux.zip --repo "$REPO"`.
9. **Generar SBOM y atestación de procedencia** (propuesta: hoy ningún flujo del repositorio produce ninguna de las dos). El SBOM se calcula sobre el entorno instalado; la atestación firma el digest de los zip ya empaquetados:

```bash
pip install cyclonedx-bom
cyclonedx-py environment --output-format json -o dist/sbom.cdx.json
```

```yaml
      - uses: actions/attest-build-provenance@<sha> # v2
        with:
          subject-path: dist/*.zip
```
10. **Cerrar la divulgación**: el repositorio no tiene `SECURITY.md`; el reporte privado se activa en los ajustes y se comprueba con `gh api "repos/$REPO/private-vulnerability-reporting"` y `gh api -X PUT "repos/$REPO/automated-security-fixes"`.
11. **Registrar el hallazgo** con comando, salida y arreglo mínimo, y dejar cerradas las marcas de verificación que sigan abiertas.

## Implementación en la plataforma

| Ruta | Papel en la cadena de suministro |
|---|---|
| `.github/workflows/ci.yml` | jobs `lint`, `test` (matriz de 3 SO, más 3.13 y 3.14 en Linux; `tools/typecheck.py` y `lint-imports` solo en Linux 3.12) y `gui`; sin bloque `permissions` |
| `.github/workflows/desktop.yml` | `bundle` por plataforma y un único `publish`; `permissions: contents: write` a nivel de flujo; firma condicionada a secretos; `SHA256SUMS.txt` |
| `.github/actions/windows-opengl/action.yml` | acción compuesta compartida por `test` y `gui`; único `uses:` fijado por SHA |
| `.github/dependabot.yml` | pip y github-actions semanales; grupos `runtime-patch`, `qt-and-vtk`, `actions` |
| `.pre-commit-config.yaml` | ganchos de terceros por etiqueta que ejecutan código en la máquina del desarrollador |
| `packaging/README.md` | §"Signing and checksums": tabla de secretos y verificación de sumas |
| `tools/release_notes.py`, `CHANGELOG.md` | notas del tag; el ayudante falla si la versión no tiene sección |
| `requirements-lock.txt` | registro del entorno bueno; **no** es un fichero de restricciones |
| `tools/typecheck.py`, `tools/mypy-budget.txt` | presupuesto de mypy, que solo puede bajar |

El endurecimiento mínimo es el del paso 2 más la atestación del paso 9; ninguno de los dos cambia el resultado del empaquetado, solo quién puede escribir y qué se puede demostrar sobre lo escrito.

## Datos normativos

No aplica. Los datos reales viven fuera de la skill y no se reproducen aquí: la tabla de secretos de firma y la verificación de sumas, en `packaging/README.md` §"Signing and checksums"; las notas de cada versión, en `CHANGELOG.md`; los grupos y exclusiones de dependencias, en `.github/dependabot.yml`; el presupuesto de tipos, en `tools/mypy-budget.txt`.

## Verificación y casos de prueba

| Comprobación (comando o condición) | Resultado esperado |
|---|---|
| `gh api repos/$REPO/actions/permissions/workflow` | muestra el permiso por defecto; si es `write`, elevarlo a `read` |
| `grep -n "permissions" .github/workflows/*.yml` | cada flujo declara un mínimo; solo `publish` eleva |
| `grep -rn "secrets\." .github/workflows/` | todo secreto se consume en un paso; nunca se imprime |
| `grep -rn "vars\." .github/workflows/` | ninguna variable contiene material sensible |
| `gh secret list` | solo los secretos de firma esperados, con fecha reciente |
| `gh api repos/$REPO/branches/develop/protection` | 200 con revisiones y checks requeridos, o la marca abierta |
| `git tag -v v0.4.0` | "Good signature", o queda documentado que no se firma |
| `grep -rn "uses:" .github/workflows .github/actions` | toda acción externa con `@<sha> # vX.Y.Z` |
| `gh api "repos/$REPO/dependabot/alerts?state=open" --jq 'length'` | 0, o cada alerta con su decisión registrada |
| `grep -n "openseesp" .github/dependabot.yml` | las tres distribuciones siguen ignoradas |
| `sha256sum -c SHA256SUMS.txt` sobre el zip descargado | `OK` en cada archivo |
| `gh attestation verify <zip> --repo $REPO` | atestación válida y sujeto igual al digest descargado |
| `python tools/typecheck.py` | pasa sin superar `tools/mypy-budget.txt` |
| `python skills/scripts/validate_skills.py --quiet` | 0 errores |

## Errores frecuentes y trampas

1. **Publicar un tag sin sección en `CHANGELOG.md`.** `tools/release_notes.py` lanza `LookupError` y el paso falla; la 0.0.4 se publicó con el cuerpo vacío por no pasar por el changelog.
2. **Dejar `contents: write` a nivel de flujo.** Lo hereda el job que compila y ejecuta `pip install` de terceros: una dependencia comprometida puede escribir en el repositorio y mover el tag recién publicado.
3. **Duplicar el publicador del release.** Ya ocurrió: cada plataforma adjuntaba su archivo, los jobs competían por el mismo release y un zip mal nombrado reemplazó el de Linux. Hoy hay un solo `publish`, que descarga todos los artefactos con `merge-multiple`.
4. **Hacer bump de un wheel atado al intérprete.** `openseespywin` y `openseespylinux` 3.8.0.0 exigen 3.12 y el `.pyd` enlaza `python312.dll`; un "patch" que pip acepta rompe el bundle sin fallar en la instalación.
5. **Correr mypy contra un entorno sin dependencias.** El job `lint` no lo hace a propósito: contra un entorno desnudo el conteo no significa nada y movería el presupuesto por motivos ajenos al código.
6. **Promover un secreto a `env:` de job.** Es lo que hace `desktop.yml` con los dos secretos de certificado, porque un `if:` de paso no lee `secrets`: el valor queda en el entorno de todos los pasos, incluido `pip install` de terceros.
7. **Confundir caché con artefacto.** Una caché envenenada no la detecta `sha256sum -c`; solo un artefacto inmutable con digest atestiguado es verificable por el usuario.
8. **Fijar acciones por etiqueta mutable.** `@v4` puede re-apuntarse a otro commit y ese código corre con el token del flujo; se fija por SHA con el tag comentado.
9. **Ejecutar ganchos de pre-commit sin fijar.** Los `rev:` actuales son etiquetas de repositorios de terceros que corren con las credenciales del desarrollador; `pre-commit autoupdate --freeze` los deja en SHA.
10. **Confiar en los rangos de `pip install -e ".[gui,dev]"`.** El CI instala desde rangos sin hashes y `requirements-lock.txt` es un registro, no una restricción: una versión nueva de PyPI entra en el siguiente push.
11. **Dar por hecho que los pasos de firma corren.** Se omiten en silencio si el secreto no existe, así que un fork produce archivos sin firmar: hay que mirar si el paso se ejecutó, no solo si el job pasó.
12. **Cerrar una alerta de Dependabot sin cambiar nada.** Ignorar `openseespy*` es deliberado; una alerta de seguridad sobre esos wheels se resuelve a mano, cambiando el intérprete, no la versión de la dependencia.

## Interfaz de salida

Informe breve en Markdown, con una fila por hallazgo:

| Campo | Contenido |
|---|---|
| Hallazgo | qué está mal y en qué archivo o ajuste |
| Evidencia | comando ejecutado y salida literal (nunca el valor de un secreto) |
| Severidad | alta si permite escribir el repositorio o publicar sin trazabilidad; media si depende de un ajuste; baja si es higiene |
| Arreglo mínimo | el diff exacto o el `gh api -X PUT` correspondiente |
| Verificación pendiente | la marca abierta, con el comando que la cierra |

El cambio de flujo se anota en el PR: qué permiso se añadió o se retiró, qué acción pasó a SHA y con qué commit, y si el artefacto gana atestación o SBOM. Nada se afirma sin la salida del comando que lo respalda.

## Referencias

1. GitHub Docs — *Security hardening for GitHub Actions*: <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions>
2. GitHub Docs — *Workflow syntax: `permissions`*: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions>
3. GitHub Docs — *Using secrets in GitHub Actions*: <https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions>
4. GitHub Docs — *About rulesets* (protección de ramas, firmas, checks requeridos): <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets>
5. GitHub Docs — *Signing commits* y *Artifact attestations*: <https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits>, <https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations>
6. GitHub Docs — *Dependabot alerts* y *security updates*: <https://docs.github.com/en/code-security/dependabot/dependabot-alerts/about-dependabot-alerts>
7. Git — *git-tag* (etiquetas firmadas), *git-verify-commit*, *git-verify-tag*: <https://git-scm.com/docs/git-tag>
8. `.github/workflows/ci.yml`, `.github/workflows/desktop.yml`, `.github/actions/windows-opengl/action.yml`, `.github/dependabot.yml` — flujos y política de dependencias vigentes.
9. `packaging/README.md` §"Signing and checksums"; `tools/release_notes.py`; `CHANGELOG.md`; `CONTRIBUTING.md`; `CLAUDE.md`.

## Registro de verificación

- **Verificado el 2026-02-14 leyendo el árbol de trabajo**: `ci.yml` (jobs `lint`, `test`, `gui`; ruff 0.16.8 y mypy 2.4.0; `tools/typecheck.py` y `lint-imports` solo en Linux 3.12; sin bloque `permissions`); `desktop.yml` (`permissions: contents: write` a nivel de flujo, promoción de los dos secretos de certificado a `env:` de job, firma opcional, `SHA256SUMS.txt`, un único `publish` con `softprops/action-gh-release@v2` y `tools/release_notes.py`); `.github/actions/windows-opengl/action.yml` (único `uses:` con SHA y `# v5.1.0`); `.github/dependabot.yml` (grupos `runtime-patch`, `qt-and-vtk`, `actions`; exclusión de los tres wheels de OpenSees); `.pre-commit-config.yaml` (ganchos por etiqueta) y `packaging/README.md` §"Signing and checksums". Se comprobó además que el árbol no contiene `SECURITY.md`, `CODEOWNERS`, SBOM ni pasos de atestación.
- **Pendiente**: todo lo que vive en los ajustes del repositorio —permiso por defecto del token, protección de `main` y `develop`, firmas exigidas, secretos de firma cargados, alertas abiertas, análisis de secretos y protección de push, divulgación privada y análisis de código—. Lo cierra quien tenga permiso de administración con los comandos de este documento; mientras siga abierto, esta skill permanece en `draft`.
