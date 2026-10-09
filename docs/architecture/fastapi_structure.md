# La estructura de FastAPI

No compite con la arquitectura en capas. Es como se organiza por dentro la capa 1.

## APIRouter: un archivo por recurso

`main.py` solo monta los routers. Cada grupo de endpoints vive en su archivo, en
lugar de crecer sin limite en uno solo.

## Schemas de Pydantic: validacion y Swagger

Se declara que forma tiene cada peticion y cada respuesta. FastAPI valida la
entrada y genera la documentacion de `/docs` a partir de esa declaracion, asi que
la documentacion nunca se desfasa del codigo.

## Depends(): inyeccion de dependencias

Es la pieza que sostiene el limite entre capas. El endpoint no construye el
servicio de la capa 2, lo recibe:

```python
@router.post("/studies/{study_code}/reconstruct")
def reconstruct_study(
    study_code: str,
    pipeline: ProcessingPipeline = Depends(get_processing_pipeline),
) -> ReconstructionResponse:
    ...
```

Da dos cosas a la vez. El endpoint no tiene forma de saltarse la capa 2, asi que
el limite deja de depender de la disciplina de quien escribe. Y en las pruebas se
sustituye la dependencia con `app.dependency_overrides`, lo que permite probar un
endpoint sin GPU, sin modelo y sin base de datos.

## lifespan: abrir y cerrar una sola vez

La conexion a PostgreSQL y la carga de los modelos ocurren al arrancar, no en cada
peticion. Cargar un modelo de 24 MB en cada llamada dejaria el sistema
inutilizable, y es lo que hace que las pruebas de concurrencia tengan sentido.
