# Arquitectura en capas

Capas cerradas: cada una llama solo a la inmediata inferior. `domain` no es una
capa mas sino un piso de tipos compartidos, sin logica ni entrada y salida, que
todas pueden importar.

| Capa | Carpeta | Que hace | Solo puede importar |
|---|---|---|---|
| 0 Dominio | `domain/` | entidades, enumerados y errores | nada del proyecto |
| 1 Presentacion | `api/`, `web/` | recibe peticiones y devuelve respuestas | `services`, `domain`, `config` |
| 2 Logica | `services/` | reconstruye, segmenta y genera mallas | `persistence`, `domain`, `config` |
| 3 Persistencia | `persistence/` | guarda y lee en PostgreSQL y Storage | `domain`, `config` |
| 4 Datos | Supabase | tablas y bucket | no es codigo |

## Lo que verifica la prueba de arquitectura

`tests/architecture/test_layer_boundaries.py` revisa, en cada push, los imports de las cuatro
carpetas de codigo Python. Esta tabla es una copia de las constantes `ALLOWED_LAYERS` y
`FORBIDDEN_EXTERNAL_LIBRARIES` de esa prueba: si una cambia, la otra tambien.

| Carpeta | Puede importar del paquete `radvol3d` | No puede importar (librerias externas) |
|---|---|---|
| `domain/` | nada: ni siquiera `config` | `fastapi`, `starlette`, `psycopg`, `supabase`, `torch` |
| `persistence/` | `domain`, `config` | `fastapi`, `starlette` |
| `services/` | `persistence`, `domain`, `config` | `fastapi`, `starlette` |
| `api/` | `services`, `domain`, `config` | `psycopg`, `psycopg_pool`, `storage3`, `supabase`, `torch` |

Son tres comprobaciones, y cada una falla con la lista de los imports que la rompen:

1. `test_a_layer_only_imports_the_allowed_layers`: una capa solo importa del paquete lo que su
   fila permite. Una prueba por carpeta.
2. `test_a_layer_does_not_import_forbidden_libraries`: una capa no importa las librerias
   externas que su fila prohibe. Una prueba por carpeta.
3. `test_the_domain_does_not_depend_on_anything_in_the_package`: el dominio no importa nada de
   `radvol3d` que no sea del propio dominio. Es la fila de `domain/` de la primera tabla, pero
   comprobada aparte porque si el piso dependiera de una capa habria un ciclo.

Si alguna falla, se corrige el import, nunca la prueba. Se corre con `pytest -m architecture`.

### Por que cada regla

1. **La persistencia no sabe que existe una web.** No importa `fastapi` ni `starlette`. Si lo
   hiciera, cambiar de servidor obligaria a reescribir el acceso a datos.
2. **La logica tampoco.** `services/` no importa `fastapi` ni `starlette`: la tuberia se puede
   usar y probar sin levantar un servidor.
3. **La presentacion no sabe que existe una base de datos ni un modelo.** `api/` no importa
   `persistence`, `psycopg`, `psycopg_pool`, `storage3`, `supabase` ni `torch`. Si lo hiciera, un cambio de columna llegaria
   hasta el HTML, y la API sabria como se calcula un resultado en lugar de solo pedirlo.
4. **El dominio no depende de nada.** Ni de las otras capas ni de las librerias de web, base de
   datos o modelos: es el piso que todas importan, y por eso no puede subir a ninguna.

### Lo que la prueba no cubre

Conviene saberlo para no creer que la prueba garantiza mas de lo que garantiza:

- **Compara el nombre raiz de cada import.** `api/` no puede importar `psycopg`, y como la
  comparacion es por nombre raiz, `psycopg_pool` y `storage3` (el grupo de conexiones y el cliente
  del bucket) se prohiben por separado: `psycopg` no cubre a `psycopg_pool`. Un submodulo como
  `torch.nn` si se detecta, porque su nombre raiz es `torch`. Cualquier otra libreria de acceso a
  datos que se agregue al proyecto hay que sumarla a la lista a mano.
- **`services/` si puede importar `psycopg`, `supabase` y `torch`**: la prueba no se lo prohibe,
  porque las estrategias neuronales necesitan `torch`. Que el acceso a datos pase siempre por los
  repositorios (la regla de la constitucion, principio II) se cumple por revision, no por esta
  prueba.
- **Solo recorre `domain/`, `persistence/`, `services/` y `api/`.** `web/` es HTML y JavaScript,
  y los archivos de la raiz del paquete (`main.py`, `config.py`) no estan en ninguna capa. `main.py`
  es donde se arma la aplicacion.
- **Solo mira imports escritos en el codigo.** Un import dinamico (`importlib`) no lo ve.

## Por que existe domain/

Cuando la capa 3 devuelve un estudio y la capa 2 lo pasa a la capa 1, las tres
necesitan el mismo tipo de dato. Si eso viaja como diccionario suelto, cada capa
supone que claves trae y el error aparece en la demostracion. Con una dataclass
compartida, aparece al escribir el codigo.

## Equivalencias con el repositorio anterior

Estado de la migracion de `persistence/`: los trece componentes estan migrados y todos los
nombres anteriores constan. Las rutas anteriores empiezan en `servicio/persistencia/`.

### Archivos migrados

| Archivo anterior | Archivo nuevo | Cambio |
|---|---|---|
| `servicio/persistencia/settings.py` | `persistence/settings.py` | igual |
| `servicio/persistencia/connection.py` | `persistence/connection.py` | igual |
| `servicio/persistencia/layout.py` | `persistence/storage_layout.py` | renombrado |
| `servicio/persistencia/storage.py` | `persistence/object_storage.py` | renombrado |
| `servicio/persistencia/study_metadata.py` | `persistence/study_metadata_store.py` | renombrado |
| `servicio/persistencia/result_store.py` | `persistence/result_store.py` | igual |
| `servicio/persistencia/repositories/organ_repository.py` | `persistence/repositories/organ_repository.py` | igual |
| `servicio/persistencia/repositories/study_repository.py` | `persistence/repositories/study_repository.py` | igual |
| `servicio/persistencia/repositories/projection_repository.py` | `persistence/repositories/projection_repository.py` | igual |
| `servicio/persistencia/repositories/model_repository.py` | `persistence/repositories/model_repository.py` | igual |
| `servicio/persistencia/repositories/processing_stage_repository.py` | `persistence/repositories/processing_stage_repository.py` | igual |
| `servicio/persistencia/repositories/lesion_repository.py` | `persistence/repositories/lesion_repository.py` | igual |
| `pruebas/prueba_capas.py` | `tests/architecture/test_layer_boundaries.py` | renombrado |

### Archivo que desaparece

| Archivo anterior | Motivo |
|---|---|
| `servicio/persistencia/almacen_archivos.py` | Ya no hace falta: existia solo para traducir entre los nombres publicos en espanol y los modulos en ingles. Con todo el codigo en ingles, esa traduccion sobra. |

### Archivos nuevos, sin equivalente anterior

| Archivo nuevo | Para que existe |
|---|---|
| `persistence/repositories/patient_repository.py` | busca o registra al paciente por DNI; el esquema nuevo lo pide |
| `persistence/database_errors.py` | traduce los errores de psycopg a errores del dominio, sin copiar su texto |
| `persistence/repositories/row_mapping.py` | convierte filas de la base en `Patient` y `Model`, que varios repositorios comparten |
