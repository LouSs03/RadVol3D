# Estrategia de pruebas

Cinco carpetas, cada una responde una pregunta distinta.

| Carpeta | Que pregunta responde | Marca | Necesita |
|---|---|---|---|
| `unit/` | esta pieza, sola, hace lo suyo? | `unit` | nada externo |
| `integration/` | dos capas reales se entienden? | `integration` | Supabase de prueba |
| `e2e/` | el sistema completo funciona por HTTP? | `e2e` | servicio levantado |
| `concurrency/` | aguanta varias peticiones a la vez? | `concurrency` | servicio levantado |
| `architecture/` | alguien se salto una capa? | `architecture` | nada |

## Las pruebas de caja negra

Son las de `e2e/`: entran por HTTP y comprueban el resultado sin conocer nada de
lo que pasa por dentro, que es la definicion de caja negra.

## Una prueba unitaria por funcionalidad

**Un pull request que agrega una funcionalidad sin su prueba unitaria no se
fusiona.** La cobertura se mide en el pipeline, asi que la omision se ve sin que
nadie la busque.

El patron Strategy es lo que hace esto viable: con los dobles de
`tests/fixtures/fake_strategies.py` se prueba la tuberia completa sin GPU, sin
PyTorch y sin archivo de pesos.

## Como se ejecutan

```
pytest                       # todas
pytest -m unit               # solo unitarias
pytest -m architecture       # limites entre capas
pytest -m "unit or architecture"   # lo que se corre antes de cada commit
```
