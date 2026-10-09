# Convenciones de git

## Ramas

Conventional Branch: `<tipo>/<descripcion>`, en minusculas, en ingles y con guiones.

```
feat/lesion-repository
fix/study-status-mapping
test/concurrency-suite
docs/data-dictionary
chore/ci-pipeline
```

## Commits

Conventional Commits 1.0.0. El tipo y el ambito en ingles, la descripcion en
espanol. El ambito es la carpeta tocada.

```
feat(persistence): agrega el repositorio de lesiones
fix(api): corrige el codigo HTTP cuando el estudio no existe
docs(database): escribe el diccionario de datos
test(services): prueba la tuberia con estrategias falsas
chore(ci): agrega el flujo de integracion continua
refactor(services)!: renombra el almacen de archivos
```

| Tipo | Cuando |
|---|---|
| `feat` | funcionalidad nueva |
| `fix` | correccion de un error |
| `docs` | solo documentacion |
| `test` | solo pruebas |
| `refactor` | cambia el codigo sin cambiar lo que hace |
| `chore` | herramientas, configuracion, dependencias |

El `!` marca un cambio que rompe compatibilidad con otra capa. Hay que avisar al
equipo en el mismo pull request.

## Pull request

Se fusiona con pull request, nunca directo a `main`. Debe pasar el flujo de
integracion continua. Si SonarCloud marca el Quality Gate, abrir **Details** y
revisar que condicion fallo antes de fusionar.
