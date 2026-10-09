# La estructura de FastAPI

No compite con la arquitectura en capas. Es como se organiza por dentro la capa 1.

## APIRouter: un archivo por recurso

`main.py` solo monta los routers. Cada grupo de endpoints vive en su archivo, en
lugar de crecer sin limite en uno solo. Desde la funcionalidad 004 son cinco:

| Router | Rutas |
|---|---|
| `health_router.py` | `GET /health` |
| `study_router.py` | `POST /studies`, `GET /studies/{code}/status`, `POST /studies/{code}/process`, `DELETE /studies/{code}` |
| `projection_router.py` | `POST /studies/{code}/projections` (cuatro campos de archivo, `angle_000` a `angle_135`) |
| `result_router.py` | `GET /studies/{code}/result` y las descargas: `organ.glb`, `tumor.glb`, `volume.npy` y `lesions/{n}.glb` |
| `viewer_router.py` | `GET /viewer/{code}` |

Los routers se montan antes que `StaticFiles` en `/`, que sirve `web/`. El contrato completo
esta en `specs/004-rest-api-viewer/contracts/http_api.md`.

## Schemas de Pydantic: validacion y Swagger

Se declara que forma tiene cada peticion y cada respuesta. FastAPI valida la
entrada y genera la documentacion de `/docs` a partir de esa declaracion, asi que
la documentacion nunca se desfasa del codigo.

## Depends(): inyeccion de dependencias

Es la pieza que sostiene el limite entre capas. El endpoint no construye el
servicio de la capa 2, lo recibe:

```python
@router.get("/studies/{study_code}")
def read_study(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> StudyResponse:
    ...
```

`get_study_service` (en `api/dependencies.py`) lee el servicio de `app.state.services`.
Lo dejo ahi el lifespan, armado por `services/service_container.py`. Asi `api/` nunca
importa la persistencia.

Da dos cosas a la vez. El endpoint no tiene forma de saltarse la capa 2, asi que
el limite deja de depender de la disciplina de quien escribe. Y en las pruebas se
sustituye la dependencia con `app.dependency_overrides`, lo que permite probar un
endpoint sin GPU, sin modelo y sin base de datos.

## lifespan: abrir y cerrar una sola vez

La conexion a PostgreSQL y la carga de los modelos ocurren al arrancar, no en cada
peticion. Cargar un modelo de 24 MB en cada llamada dejaria el sistema
inutilizable, y es lo que hace que las pruebas de concurrencia tengan sentido.

El lifespan de `main.py` llama a `build_service_container` y guarda el resultado en
`app.state.services`; al apagarse, lo cierra. Si un modelo no se puede cargar, la
aplicacion arranca igual y lo informa en el registro de arranque. Las pruebas pasan a
`create_app(container_builder=...)` un contenedor falso que no abre la base.

## Procesamiento en segundo plano

`POST /studies/{code}/process` no espera a la tuberia, que con los modelos reales tarda
minutos en CPU. Reclama el estudio dentro del pedido (`start_processing`: pasa de `pending` a
`processing` con un bloqueo de fila, asi que de dos pedidos simultaneos solo uno lo logra) y
deja `run_processing` como tarea de `BackgroundTasks`. Starlette la corre en su grupo de hilos
despues de responder `202`: el bucle de eventos sigue libre y las consultas de estado
responden mientras tanto. `run_processing` nunca lanza; todo fallo queda en el estado del
estudio y en el registro.

**Supuesto: un solo proceso de uvicorn.** Al arrancar, el contenedor pasa a `failed` todo
estudio que haya quedado en `processing`, porque la tarea que lo procesaba murio con el
proceso anterior; sin esto no se podria ni borrar. Con varios procesos, uno marcaria como
fallidos estudios que otro sigue procesando. Si algun dia hace falta escalar, el paso es una
cola de trabajos, no mas procesos de uvicorn.

## Descargas por el propio servicio

El resultado devuelve rutas del servicio (`/studies/{code}/result/...`), no direcciones del
bucket. El navegador nunca ve la direccion de Supabase Storage ni una credencial, el bucket
sigue privado y ninguna direccion vence a mitad de la carga del visor. Los tipos de contenido
se declaran en `api/content_types.py`, no se importan de la persistencia.

## Errores sin datos del paciente

`api/error_handlers.py` es el unico lugar que traduce errores a HTTP:

- cada error del dominio responde `{"detail": <mensaje en espanol>}` con su codigo;
- la validacion de la peticion responde `422` con `loc`, `msg` y `type` de cada campo, **sin**
  el campo `input` que FastAPI usa para devolver el valor recibido (con un DNI mal escrito,
  ese valor seria un dato del paciente);
- un error inesperado responde `500` con un mensaje generico. Se atrapa en un middleware y no
  con un manejador de `Exception`, porque Starlette vuelve a lanzar la excepcion despues de
  ese manejador y el servidor registraria la traza completa con su texto.

## El visor

`web/viewer.html` es una pagina estatica: lee el codigo del estudio de su URL y pide el estado
y el resultado a la API. Usa rutas absolutas (`/css/...`, `/js/...`) porque vive en
`/viewer/<codigo>`. Three.js llega por un `importmap` desde jsDelivr con version fija; no se
copia al repositorio, porque `check_naming_convention.py` revisa todo `.js`. La logica que no
dibuja esta en `web/js/viewer_state.js` y se prueba con `node --test`.
