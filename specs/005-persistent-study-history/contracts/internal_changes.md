# Contrato: cambios internos entre capas

Todos los cambios **agregan**: ninguna firma existente cambia, así que no hay commits con `!`.

## domain/entities.py

- `+ StudyHistoryEntry`: ver [data-model.md §2](../data-model.md). `national_id` lleva
  `repr=False`.
- `+ StudyHistoryPage`: ver [data-model.md §2](../data-model.md).

## persistence/

| Componente | Agrega | Lanza |
|---|---|---|
| `repositories/study_repository.py` · `StudyRepository` | `list_history(limit: int, offset: int, national_id: str \| None = None) -> list[StudyHistoryEntry]` | `InvalidPatientDataError` si el DNI no tiene ocho dígitos, sin el valor en el mensaje. `DatabaseUnavailableError` si la base no responde |
| `study_metadata_store.py` · `StudyMetadataStore` | `list_history(limit: int, offset: int, national_id: str \| None = None) -> StudyHistoryPage` | Lo mismo que el repositorio |

- `list_recent` y `list_studies` se conservan: las usan las pruebas de integración de
  borrado.
- No se importa `fastapi` ni `starlette`.

## services/study_service.py

| Agrega | Comportamiento |
|---|---|
| `StudyService.list_history(limit: int = 50, offset: int = 0, national_id: str \| None = None) -> StudyHistoryPage` | Delega en el almacén y aplica la regla de `completed` (research.md R4) |

## api/

- `+ schemas/history_schema.py`: `StudyHistoryItem`, `StudyHistoryResponse` y
  `StudySearchRequest`.
- `+ routers/history_router.py`: `GET /studies` y `POST /studies/search`. Recibe
  `StudyService` con `Depends(get_study_service)`.
- `main.py`: `app.include_router(history_router.router)`.
- `error_handlers.py`: sin cambios. `InvalidPatientDataError` ya responde 422.
- `api/` no importa `persistence`, `psycopg`, `supabase` ni `torch`.

## static/ (interfaz web)

- `+ static/js/history_view.js`: funciones puras (research.md R7). Exporta:
  - `format_volume(mm3)`;
  - `volume_text(entry)`, `lesion_count_text(entry)` y `national_id_text(entry)`;
  - `clean_national_id(value)` e `is_valid_national_id(value)`.
- `static/index.html`:
  - el historial lee `GET /studies` y `POST /studies/search`, con "Ver más", el filtro por
    DNI y las columnas DNI y Volumen;
  - se quitan las funciones de historial local y se borra la clave vieja (R6);
  - el visor importa `format_volume` del módulo.
