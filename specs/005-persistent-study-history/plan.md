# Implementation Plan: Historial de estudios persistente con volumen de lesión y DNI

**Branch**: `feat/persistent-study-history` (por crear; hoy se trabaja en `feat/rest-api-viewer`) | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-persistent-study-history/spec.md`

## Summary

El historial de la interfaz deja de vivir en `localStorage` y sale de la base. Hay dos rutas
nuevas:

- `GET /studies` lista todos los estudios, paginados;
- `POST /studies/search` filtra por DNI, que va en el cuerpo para no quedar en el registro de
  acceso de uvicorn (research.md R1).

Cada elemento trae código, órgano, estado, fecha, número de lesiones, volumen total de lesión
en mm³ y el DNI completo del paciente. Solo un estudio `completed` trae lesiones y volumen.

No hay migración. Una sola consulta en `StudyRepository` une `study`, `organ` y `patient` con
un `left join lesion` agrupado (R2). La regla de `completed` vive en `StudyService` (R4).

En la web:

- las funciones de formato pasan a `static/js/history_view.js`, que se prueba con
  `node --test`;
- el visor y el historial usan el mismo `format_volume` (R5, R7).

## Technical Context

**Language/Version**: Python 3.11 en el CI y 3.13 en desarrollo. JavaScript ES2022 (módulos
ES). Node 22 solo para `node --test`.

**Primary Dependencies**: las ya presentes (FastAPI, Pydantic 2, psycopg). No se agrega
ninguna dependencia de Python ni de JavaScript.

**Storage**: Supabase Postgres con el esquema de 001 y la migración 002, sin cambios. El
historial no toca Storage.

**Testing**:

- pytest con los marcadores `unit`, `integration` y `architecture` (ninguno nuevo);
- `TestClient` para las rutas;
- `node --test "tests/unit/web/*.js"` para `history_view.js`.

**Target Platform**: el mismo servidor de 004 (un proceso de uvicorn, CPU) y un navegador
moderno.

**Project Type**: servicio web (FastAPI) con la interfaz en `src/radvol3d/static/`.

**Performance Goals**: la primera página del historial, con 500 estudios, se ve completa en
menos de 2 s en el entorno de demostración (SC-002). No se fija ninguna otra meta.

**Constraints**:

- capas cerradas;
- el DNI no aparece en registros, mensajes de error, URL, `localStorage` ni consola
  (FR-012);
- nombre y apellido no salen en ninguna respuesta (FR-009);
- servicios gratuitos;
- snake_case también en JavaScript.

**Scale/Scope**: cientos de estudios, con páginas de 50 (máximo 100). Son 2 rutas nuevas, 1
módulo JS nuevo y una vista de `index.html` reescrita.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo lo cumple el diseño | Antes | Después |
|---|---|---|---|
| **I. Capas cerradas** | `history_router.py` recibe `StudyService` con `Depends(get_study_service)` y solo importa `services`, `domain` y sus esquemas. El SQL va en `StudyRepository` y la transacción en `StudyMetadataStore`. `test_layer_boundaries.py` no se modifica. | ✅ | ✅ |
| **II. Strategy, Factory Method y Repository** | No toca estrategias ni la tubería. No hay `if organ ==`: la regla de R4 es por estado. El acceso a datos pasa por el repositorio. | ✅ | ✅ |
| **III. Inglés y snake_case** | Rutas, campos JSON, clases y funciones en inglés: `national_id`, `total_lesion_volume_mm3`, `StudyHistoryEntry`, `history_view.js`. Mensajes al usuario en español. Las funciones de `history_view.js` van en snake_case. | ✅ | ✅ |
| **IV. Prueba unitaria con cada funcionalidad** | El router, el servicio, el repositorio, el almacén y `history_view.js` tienen cada uno su prueba en `tests/unit/`. La consulta real se prueba en `tests/integration/`. Ninguna prueba `unit` usa la red ni la base. | ✅ | ✅ |
| **V. Ningún dato inventado, ninguna clave expuesta** | La única meta de rendimiento es la de la spec (SC-002), y el quickstart pide anotar el valor medido. Los ejemplos del contrato se declaran ilustrativos. No hay claves nuevas. El DNI no se registra (R1). | ✅ | ✅ |
| **Servicios y dependencias** | No hay dependencias nuevas. La conexión sigue abriéndose una sola vez en el `lifespan`. | ✅ | ✅ |
| **Flujo de desarrollo** | La rama actual es `feat/rest-api-viewer`. La implementación MUST ir en `feat/persistent-study-history`. Commits por carpeta: `feat(domain)`, `feat(persistence)`, `feat(services)`, `feat(api)`, `feat(static)`, `test(...)`, `docs(specs)`. | ⚠️ rama pendiente, no bloquea | ⚠️ |

**Cambios que rompen compatibilidad**: ninguno. Todas las firmas son nuevas
([contracts/internal_changes.md](contracts/internal_changes.md)).

**Excepción documentada a otra especificación**: FR-029 de 004 ("las respuestas no devuelven
datos personales") gana una excepción acotada a `national_id` en las dos rutas del historial
(R8). Esto no viola la constitución: el Principio V habla de datos inventados y claves, no de
datos personales. Igual se documenta en la spec y el contrato de 004 (FR-013).

**Re-check después del diseño.** Se revisaron [data-model.md](data-model.md) y
[contracts/](contracts/). Los siete puntos se mantienen y ninguna decisión necesita una
excepción a la constitución.

## Project Structure

### Documentation (this feature)

```text
specs/005-persistent-study-history/
├── spec.md
├── plan.md                        # este archivo
├── research.md                    # Fase 0: decisiones R1-R8
├── data-model.md                  # Fase 1
├── quickstart.md                  # Fase 1
├── contracts/
│   ├── http_api_history.md        # GET /studies y POST /studies/search
│   └── internal_changes.md        # lo que se agrega en domain, persistence, services, api y static
├── checklists/requirements.md
└── tasks.md                       # Fase 2 (/speckit-tasks), no se crea aquí
```

### Source Code (repository root)

```text
src/radvol3d/
├── domain/
│   └── entities.py                    # + StudyHistoryEntry, StudyHistoryPage
├── persistence/
│   ├── repositories/
│   │   └── study_repository.py        # + list_history (una consulta agregada)
│   └── study_metadata_store.py        # + list_history (limit + 1 → has_more)
├── services/
│   └── study_service.py               # + list_history (regla de completed)
├── api/
│   ├── schemas/
│   │   └── history_schema.py          # nuevo: StudyHistoryItem, StudyHistoryResponse, StudySearchRequest
│   └── routers/
│       └── history_router.py          # nuevo: GET /studies, POST /studies/search
├── main.py                            # + include_router(history_router.router)
└── static/
    ├── index.html                     # vista de historial reescrita; sin historial local
    └── js/
        └── history_view.js            # nuevo: format_volume y textos de cada fila

tests/
├── unit/
│   ├── api/test_history_router.py             # nuevo
│   ├── services/test_study_service.py         # + casos de list_history
│   ├── persistence/repositories/test_study_repository.py   # + casos de list_history
│   ├── persistence/test_study_metadata_store.py            # + has_more
│   ├── domain/                                 # + repr de StudyHistoryEntry sin DNI
│   └── web/test_history_view.js                # nuevo
└── integration/persistence/test_study_history_integration.py   # nuevo

specs/004-rest-api-viewer/
├── spec.md                        # nota en FR-029 que remite a 005
└── contracts/http_api.md          # enlace a la sección de historial
```

**Structure Decision**: se mantiene la estructura de un solo paquete (`src/radvol3d/`) con
las capas de la constitución. Lo único nuevo en la estructura es `static/js/`, para que la
lógica de la página se pueda importar desde una prueba de Node (R7).

## Complexity Tracking

No hay violaciones de la constitución que justificar.
