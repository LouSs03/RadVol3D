# Implementation Plan: Capa de API REST y visor 3D

**Branch**: `feat/rest-api-viewer` (por crear; hoy se trabaja en `feat/services-pipeline`) | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-rest-api-viewer/spec.md`

## Summary

La funcionalidad expone por HTTP la tubería de 002 y agrega el visor 3D. El flujo tiene
tres pasos:

1. `POST /studies` crea el estudio;
2. `POST /studies/{code}/projections` sube los cuatro `.npy`;
3. `POST /studies/{code}/process` reclama el estudio con un bloqueo de fila y lanza la
   tubería en una tarea en segundo plano de FastAPI. Responde `202` al instante.

Después, `GET /status` muestra el avance etapa por etapa y `GET /result` devuelve rutas de
descarga del propio servicio. El bucket sigue privado. `GET /viewer/{code}` sirve una página
con Three.js que dibuja el órgano semitransparente y una malla opaca por lesión, cada una de
un color que coincide con su fila en la lista.

La malla por lesión obliga a tocar las capas de abajo:

- **meshing**: separa cada región de la máscara emparejándola con el resumen por número de
  vóxeles y centroide (R9);
- **persistence**:
  - sube una `.glb` por lesión;
  - guarda su ruta en `lesion.mesh_path`;
  - agrega la columna `lesion.organ` con la migración 002;
  - borra esas mallas junto con el estudio.

`region_id` no llega a la base ni a la API.

## Technical Context

**Language/Version**: Python 3.11 en el CI, 3.13 en la laptop de desarrollo. JavaScript
ES2022 (módulos ES) en el navegador. Node 22 solo para `node --test` en el CI.

**Primary Dependencies**:

- Ya presentes: FastAPI, Pydantic 2, python-multipart, httpx (pruebas), numpy, scipy,
  scikit-image, trimesh.
- Navegador: Three.js con `GLTFLoader` y `OrbitControls`, por `importmap` desde jsDelivr y
  con versión fija (research.md R13).
- No se agrega ninguna dependencia de Python.

**Storage**:

- Supabase Postgres: el esquema de 001 más la migración `002_add_lesion_organ.sql`.
- Supabase Storage: el bucket de datos gana `<code>/meshes/lesion_<NNN>.glb`.

**Testing**:

- pytest con los marcadores `unit`, `integration`, `e2e`, `concurrency` y `architecture`.
  Ninguno nuevo.
- `node --test` para la lógica del visor (R14).
- `TestClient` para la API; uvicorn en un hilo para la prueba de concurrencia.

**Target Platform**: servidor Linux en CPU con un solo proceso de uvicorn (R4, R5). Navegador
moderno con WebGL 2 y acceso a la red de distribución.

**Project Type**: servicio web (FastAPI) con páginas estáticas en `src/radvol3d/web/`.

**Performance Goals**: los de la spec, nada inventado:

- `POST /process` responde en menos de 1 s (SC-002);
- `GET /status` responde en menos de 1 s mientras otro estudio se procesa (SC-003);
- las mallas aparecen en el visor en menos de 5 s en la misma red (SC-004).

La tubería con modelos reales tarda minutos en CPU (R18 de 002). Por eso se ejecuta en
segundo plano.

**Constraints**:

- capas cerradas: `api/` sin `persistence`, `psycopg`, `supabase` ni `torch`;
- ningún dato personal en respuestas, errores ni registros, incluido el 422 de validación;
- bucket privado;
- servicios gratuitos;
- snake_case también en JavaScript.

**Scale/Scope**: un servidor y un proceso, con varios estudios en segundo plano a la vez.
Son 4 rutas de API más 4 de descarga y 1 de visor. Cada `.npy` de entrada pesa unos 64 KB, y
cada estudio tiene unas pocas lesiones.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo lo cumple el diseño | Antes | Después |
|---|---|---|---|
| **I. Capas cerradas** | Los routers reciben `StudyService` con `Depends(get_study_service)` desde `app.state`. `api/` importa solo `services`, `domain` y `config`: los tipos de contenido de las descargas se declaran en `api/`, sin importar la constante de la persistencia. Las operaciones nuevas (crear sin proyecciones, reclamar, bajar archivos y recuperar estudios colgados) van en `services/` y `persistence/`, no en `api/`. `test_layer_boundaries.py` no se modifica. | ✅ | ✅ |
| **II. Strategy, Factory Method y Repository** | La malla por lesión se agrega dentro de `MeshingStrategy`, cambiando su firma (un parámetro más). La tubería solo pasa las regiones. No hay `if organ ==`: el órgano de cada lesión lo copia el `insert` desde el estudio. El SQL nuevo vive en los repositorios; el listado del bucket, en `ObjectStorage`. | ✅ | ✅ |
| **III. Inglés y snake_case** | Rutas, campos JSON, módulos y la columna `organ` van en inglés. El cuerpo de error pasa de `detalle` a `detail` (R8). Los mensajes al usuario van en español. En JS, todas las declaraciones van en snake_case; los métodos de Three.js son externos y `check_naming_convention.py` solo revisa declaraciones. Three.js no se copia al repositorio, porque rompería esa verificación (R13). | ✅ | ✅ |
| **IV. Prueba unitaria con cada funcionalidad** | Cada router, operación de servicio, método de persistencia y `split_lesion_masks` tiene su prueba en `tests/unit/`. La lógica del visor se separa en `viewer_state.js` y se prueba con `node --test` en `tests/unit/web/` (R14). Lo que necesita un navegador se valida con quickstart.md. Ninguna prueba `unit` usa la red, la base ni torch. | ✅ | ✅ |
| **V. Ningún dato inventado, ninguna clave expuesta** | No hay metas de rendimiento propias: solo las de la spec. La versión de Three.js se fija con un número publicado y verificado al implementar, nunca a ojo. Los ejemplos del contrato dicen de dónde salen (el doble). Las URL de descarga no exponen el bucket ni la clave. El 422 no devuelve `input`. | ✅ | ✅ |
| **Servicios y dependencias** | No hay dependencias de Python nuevas. Three.js llega por una red de distribución gratuita, sin peso en el repositorio. Node solo corre en el CI, sin paquetes. La base y los modelos se siguen abriendo una vez en el `lifespan`, que ahora también recupera los estudios colgados. | ✅ | ✅ |
| **Flujo de desarrollo** | La rama actual es `feat/services-pipeline`. La implementación MUST ir en `feat/rest-api-viewer`. Commits por carpeta: `feat(api)`, `feat(services)`, `feat(persistence)!`, `feat(domain)`, `feat(web)`, `test(...)`, `docs(...)`. | ⚠️ rama pendiente, no bloquea | ⚠️ |

**Cambios que rompen compatibilidad entre capas (se marcan con `!` y se avisan en el pull
request):**

- `ResultStore.save_result` gana el parámetro obligatorio `lesion_meshes`, y `mesh_path`
  cambia de significado (`feat(persistence)!`).
- `MeshingStrategy.build_meshes` gana `regions` (`feat(services)!`).
- El cuerpo de error de la API pasa de `detalle` a `detail` (`feat(api)!`). Ningún cliente
  del repositorio lo leía (`web/js/main.js` solo llama a `/health`).

**Re-check después del diseño.** Se revisaron [data-model.md](data-model.md) y
[contracts/](contracts/). Los siete puntos se mantienen. Ninguna decisión necesita una
excepción.

## Project Structure

### Documentation (this feature)

```text
specs/004-rest-api-viewer/
├── spec.md
├── plan.md                            # este archivo
├── research.md                        # Fase 0: decisiones R1-R16
├── data-model.md                      # Fase 1
├── quickstart.md                      # Fase 1
├── contracts/
│   ├── http_api.md                    # API pública y visor
│   ├── services_api_changes.md        # lo que cambia en el contrato de 002
│   └── persistence_api_changes.md     # lo que cambia en los contratos de 001 y 002
├── checklists/requirements.md
└── tasks.md                           # Fase 2 (/speckit-tasks), no se crea aquí
```

### Source Code (repository root)

```text
src/radvol3d/
├── config.py                          # + MAX_PROJECTION_BYTES
├── main.py                            # monta los routers nuevos; quita reconstruction/segmentation
├── domain/
│   ├── entities.py                    # Lesion.organ, StoredResult.volume_path
│   ├── enums.py                       # + ResultFile
│   └── exceptions.py                  # + InvalidStudyStateError
├── api/
│   ├── dependencies.py                # sin cambios
│   ├── error_handlers.py              # tabla R8, "detail", 422 sin input, 500 genérico
│   ├── content_types.py               # nuevo: model/gltf-binary, application/octet-stream
│   ├── routers/
│   │   ├── health_router.py           # sin cambios
│   │   ├── study_router.py            # reescrito: create, status, process, delete
│   │   ├── projection_router.py       # nuevo
│   │   ├── result_router.py           # nuevo: resultado y descargas
│   │   ├── viewer_router.py           # nuevo
│   │   ├── reconstruction_router.py   # se borra
│   │   └── segmentation_router.py     # se borra
│   └── schemas/
│       ├── study_schema.py            # reescrito
│       ├── projection_schema.py       # nuevo
│       ├── result_schema.py           # nuevo
│       ├── error_schema.py            # nuevo
│       ├── reconstruction_schema.py   # se borra
│       └── segmentation_schema.py     # se borra
├── services/
│   ├── study_service.py               # métodos nuevos (contrato services_api_changes.md)
│   ├── service_container.py           # recover_interrupted_studies al armar
│   ├── pipeline/
│   │   ├── filters.py                 # MeshingFilter pasa las regiones
│   │   └── persistence_progress.py    # pasa meshes.lesions
│   └── meshing/
│       ├── meshing_strategy.py        # MeshSet.lesions, build_meshes(..., regions)
│       ├── lesion_regions.py          # nuevo: split_lesion_masks
│       └── marching_cubes_strategy.py # una malla por región
├── persistence/
│   ├── storage_layout.py              # + lesion_mesh_path
│   ├── object_storage.py              # + list_names
│   ├── study_metadata_store.py        # create_study, add_projections, claim, load, delete
│   ├── processing_progress_store.py   # + fail_interrupted_studies
│   ├── result_store.py                # lesion_meshes, read_file, read_lesion_mesh
│   └── repositories/
│       ├── lesion_repository.py       # organ desde el estudio
│       ├── projection_repository.py   # + count_by_study
│       └── study_repository.py        # + list_codes_by_status
└── web/
    ├── viewer.html                    # importmap, lienzo, lista, avisos, rutas absolutas
    ├── css/main.css                   # estilos del visor
    └── js/
        ├── viewer_state.js            # nuevo: paleta, filas, mensajes (sin DOM ni Three.js)
        └── viewer_3d.js               # escena, carga de .glb, controles, resaltado

docs/database/schema/002_add_lesion_organ.sql   # nueva migración

tests/
├── fixtures/
│   ├── fake_strategies.py             # región con voxels y centroid_voxel; .glb por región
│   └── fake_container.py              # sin cambios de forma
├── unit/
│   ├── api/                           # un archivo por router + error_handlers + schemas
│   ├── services/                      # study_service (nuevos), lesion_regions, marching_cubes
│   ├── persistence/                   # storage_layout, object_storage, stores, lesion_repository
│   └── web/test_viewer_state.js       # node --test
├── integration/
│   ├── persistence/                   # organ y mesh_path por fila, claim con bloqueo, borrado
│   └── services/                      # tubería con malla por lesión
├── e2e/
│   ├── app_with_fakes.py              # create_app_with_fakes: dobles + .env.test
│   └── test_http_flow.py              # FR-031
└── concurrency/
    └── test_background_processing.py  # FR-032, SC-003

.github/workflows/ci.yml               # setup-node 22, node --test, cobertura de api >= 80 %
docs/architecture/fastapi_structure.md # routers por recurso, segundo plano, descargas
docs/database/data_dictionary.md       # lesion.organ, mesh_path por lesión
docs/database/entity_relationship.md   # lesion.organ
docs/models/meshing.md                 # malla por lesión y emparejamiento con el resumen
docs/standards/testing_strategy.md     # pruebas del visor con node --test
specs/001-.../contracts/persistence_api.md  # reescrito con los cambios
```

**Decisión de estructura**: un solo proyecto, con el paquete `src/radvol3d` y sus capas
existentes. El visor vive en `web/`, que ya existe y ya se sirve con `StaticFiles`. No se
crea un proyecto de frontend aparte: no hay paso de compilación ni `node_modules`.

## Orden de construcción

1. **Base.**
   1. `domain/`: `Lesion.organ`, `StoredResult.volume_path`, `ResultFile` e
      `InvalidStudyStateError`.
   2. `config.MAX_PROJECTION_BYTES`.
   3. Migración 002 aplicada en la base de prueba.
2. **Persistencia**, con sus pruebas unitarias e integración:
   1. `lesion_mesh_path` y `list_names`.
   2. `LesionRepository` con `organ`.
   3. `create_study`, `add_projections`, `claim_for_processing` y `load_projections`.
   4. `save_result` con las mallas por lesión, `read_file` y `read_lesion_mesh`.
   5. `delete_study` con las mallas por lesión.
   6. `fail_interrupted_studies`.
3. **Mallas por lesión**:
   1. `split_lesion_masks`.
   2. `MeshSet.lesions` y la nueva firma de `build_meshes`.
   3. `MarchingCubesStrategy`.
   4. `MeshingFilter` y `PersistenceProgress`.
   5. Los dobles.
   Las pruebas de 002 se actualizan en el mismo commit.
4. **Servicio**:
   1. Los métodos nuevos de `StudyService`.
   2. `process_study` como composición de esos métodos.
   3. La recuperación en `service_container`.
5. **API**:
   1. Esquemas.
   2. `error_handlers` (R8).
   3. Los cuatro routers.
   4. `main.py`.
   5. Pruebas unitarias de cada ruta.
   6. Paso de cobertura de `api/` en el CI.
6. **Visor**:
   1. `viewer_state.js` con `node --test`.
   2. `viewer.html` y `viewer_3d.js`.
   3. Versión de Three.js verificada en npm.
   4. `node --test` en el CI.
7. **Punta a punta y concurrencia**:
   1. `app_with_fakes.py`.
   2. `test_http_flow.py`.
   3. `test_background_processing.py`.
   4. Recorrido manual de quickstart.md.
8. **Documentación**: los documentos de `docs/` de la lista y el contrato de 001.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Sin conexión a jsDelivr, el visor no carga Three.js | La página detecta el fallo del `import` y muestra el aviso con los enlaces de descarga (FR-026). Copiar Three.js al repositorio queda como alternativa documentada, con una exclusión en `check_naming_convention.py` que habría que aprobar aparte. |
| Con más de un proceso de uvicorn, la recuperación al arrancar marcaría `failed` estudios vivos de otro proceso | Supuesto explícito: un solo proceso (R4, R5). Se documenta en `fastapi_structure.md` y en el docstring de `fail_interrupted_studies`. |
| Una región del resumen no encuentra su componente en la máscara y la etapa 4 falla | Es exacto para EN-2 por construcción (máscara limpia, mismo etiquetado). Una prueba unitaria lo cubre con la referencia de `test_lung_region_summary.py`. Si pasara, el fallo se ve en el estado del estudio. |
| Un estudio con muchas lesiones hace lento el visor | Cada malla de lesión se extrae a resolución completa y suele ser chica. SC-004 se mide en la prueba manual con el estudio de ejemplo. Si no se cumple, se aplica `ORGAN_STEP` también a las lesiones grandes. |
| Las pruebas de 001 y 002 que llaman a `save_result` o `build_meshes` con la firma vieja | Se actualizan en el mismo commit que cambia la firma (commits `!`). |
| `TestClient` corre la tarea en segundo plano de forma síncrona y oculta problemas de concurrencia | La prueba de concurrencia usa uvicorn real en un hilo (R15). |

## Complexity Tracking

No hay violaciones de la constitución que justificar. Dos decisiones salen de lo habitual y
quedan registradas:

| Decisión | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Usar Node en el CI para probar el JavaScript del visor | Principio IV: la lógica del visor es funcionalidad nueva y necesita su prueba unitaria | No probar el JS, porque viola el Principio IV. Playwright o Jest, porque traen cientos de MB o `node_modules`. |
| Suponer un solo proceso de uvicorn | La recuperación de estudios colgados (FR-017) necesita saber que ninguna tarea sigue viva | Un vencimiento por tiempo, porque exige fijar un tiempo máximo que el repositorio no tiene (Principio V). |
