# Estilo de codigo

## Idioma

| Que | Idioma |
|---|---|
| modulos, carpetas, clases, funciones, variables | ingles |
| tablas y columnas de la base de datos | ingles |
| comentarios y docstrings | espanol |
| mensajes al usuario en la interfaz | espanol |
| descripcion de los commits (despues de los dos puntos) | espanol |

## Una sola convencion: snake_case

| Elemento | Correcto | Incorrecto |
|---|---|---|
| Modulo | `study_repository.py` | `studyRepository.py` |
| Funcion | `find_by_study` | `findByStudy` |
| Variable | `study_id` | `studyId` |
| Clase | `StudyRepository` | `study_repository` |
| Constante | `MAX_PROJECTIONS` | `maxProjections` |
| Columna SQL | `total_time_sec` | `totalTimeSec` |

**Las clases llevan PascalCase.** No es mezclar convenciones: lo fija la PEP 8,
que es el estandar del lenguaje. Lo que queda prohibido es `camelCase` para
funciones y variables.

**JavaScript tambien va en snake_case.** La convencion habitual de JavaScript es
`camelCase`, pero la exigencia es una sola convencion en todo el proyecto. Es una
desviacion deliberada y queda escrita aqui para que se lea como decision y no
como descuido.

## Como se verifica

```
ruff check src tests
python scripts/check_naming_convention.py
```

`ruff` con las reglas `N` cubre el Python. El script revisa los nombres de
archivos y el JavaScript. Las dos cosas corren en cada push.
