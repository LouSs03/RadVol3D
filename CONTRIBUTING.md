# Como trabajar en este repositorio

## Antes de escribir codigo

1. Lee `docs/standards/code_style.md` y `docs/standards/git_conventions.md`.
2. Crea tu rama desde `main`.
3. Asegurate de tener tu `.env` y el paquete instalado (`pip install -e .`).

## Ramas

Conventional Branch: `<tipo>/<descripcion>` en minusculas, en ingles y con guiones.

```
feat/lesion-repository
fix/study-status-mapping
test/concurrency-suite
docs/data-dictionary
```

## Commits

Conventional Commits 1.0.0. El tipo y el ambito en ingles, la descripcion en espanol.

```
feat(persistence): agrega el repositorio de lesiones
fix(api): corrige el codigo HTTP cuando el estudio no existe
docs(database): escribe el diccionario de datos
test(services): prueba la tuberia con estrategias falsas
refactor(services)!: renombra el almacen de archivos
```

El `!` marca un cambio que rompe compatibilidad con otra capa. Avisa al equipo.

## Regla de pruebas

**Un pull request que agrega una funcionalidad sin su prueba unitaria no se fusiona.**
Es la exigencia mas facil de posponer y la que mas cuesta recuperar despues.

## Antes de cada commit

```
ruff check src tests
pytest -m "unit or architecture"
```

Si la prueba de arquitectura falla, corrige el import, nunca la prueba.

## Pull request

1. Describe que cambia y por que.
2. Espera a que pase el flujo de integracion continua.
3. Si SonarCloud marca el Quality Gate, abre **Details** y revisa que condicion fallo
   antes de fusionar.
