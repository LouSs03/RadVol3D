# Estrategia de pruebas

Seis carpetas de pytest, cada una responde una pregunta distinta, mas las pruebas del visor
en JavaScript.

| Carpeta | Que pregunta responde | Marca | Necesita |
|---|---|---|---|
| `unit/` | esta pieza, sola, hace lo suyo? | `unit` | nada externo |
| `integration/` | dos capas reales se entienden? | `integration` | Supabase de prueba |
| `e2e/` | el sistema completo funciona por HTTP? | `e2e` | servicio levantado |
| `concurrency/` | aguanta varias peticiones a la vez? | `concurrency` | Supabase de prueba |
| `architecture/` | alguien se salto una capa? | `architecture` | nada |
| `ml/` | los modelos reales dan la misma salida que los originales? | `ml` | torch y pesos |
| `unit/web/` | la logica del visor (colores, filas, estados) hace lo suyo? | - (`node --test`) | Node 22 o mas nuevo, sin npm |

## Las pruebas de caja negra

Son las de `e2e/`: entran por HTTP y comprueban el resultado sin conocer nada de
lo que pasa por dentro, que es la definicion de caja negra.

Usan `tests/e2e/app_with_fakes.py`: la aplicacion real (lifespan, routers, contenedor,
base y bucket de `.env.test`) con las estrategias dobles, para que un estudio se procese en
segundos y sin PyTorch. La misma fabrica sirve para el recorrido manual del visor:

```
uvicorn --factory tests.e2e.app_with_fakes:create_app_with_fakes
```

## Las pruebas del visor

La logica del visor que no dibuja (paleta, filas de la lista, que hacer en cada estado) vive
en `src/radvol3d/web/js/viewer_state.js`, sin DOM ni Three.js, y se prueba con el ejecutor
de Node, sin npm ni dependencias (`tests/unit/web/`). Lo que necesita un navegador (que la
escena se dibuje) se verifica a mano con el quickstart de la funcionalidad 004.

Desde Node 22, `node --test` recibe patrones de archivo, no carpetas: hay que pasarle el
patron entre comillas.

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
pytest -m "not ml"          # todo menos los modelos reales (sin PyTorch)
node --test "tests/unit/web/*.js"  # la logica del visor
```
