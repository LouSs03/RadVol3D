---

description: "Lista de tareas: capa de API REST y visor 3D"
---

# Tasks: Capa de API REST y visor 3D

**Input**: Design documents from `/specs/004-rest-api-viewer/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/http_api.md](contracts/http_api.md),
[contracts/services_api_changes.md](contracts/services_api_changes.md),
[contracts/persistence_api_changes.md](contracts/persistence_api_changes.md),
[quickstart.md](quickstart.md)

**Tests**: Sí se incluyen. Las exigen el Principio IV de la constitución (prueba unitaria en
el mismo pull request) y FR-030 a FR-033 de la spec. En cada componente, la prueba se
escribe antes que el código y debe fallar.

**Organization**: Las tareas se agrupan por historia de la spec:

- US1 (P1): cargar y procesar un estudio por HTTP;
- US2 (P1): rechazar pedidos inválidos;
- US3 (P2): ver el resultado en 3D, con la malla por lesión;
- US4 (P3): borrar un estudio.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (archivos distintos, sin depender de tareas sin terminar)
- **[Story]**: historia de la spec a la que pertenece la tarea (US1 a US4)
- Todas las rutas son relativas a la raíz del repositorio

## Path Conventions

Proyecto único (ver "Decisión de estructura" en [plan.md](plan.md)):

- Código: `src/radvol3d/{domain,persistence,services,api,web}/` y `src/radvol3d/main.py`
- Migración: `docs/database/schema/`
- Pruebas: `tests/unit/` (`unit`), `tests/unit/web/` (`node --test`), `tests/integration/`
  (`integration`), `tests/e2e/` (`e2e`), `tests/concurrency/` (`concurrency`)
- Dobles: `tests/fixtures/`

Reglas de todas las tareas:

- Identificadores, rutas HTTP, campos JSON y columnas en inglés y snake_case, también en
  JavaScript; comentarios, docstrings y mensajes al usuario en español (Principio III).
- `api/` no importa `persistence`, `psycopg`, `psycopg_pool`, `storage3`, `supabase` ni
  `torch` (Principio I). `tests/architecture/test_layer_boundaries.py` no se modifica.
- Ninguna respuesta, mensaje de error ni registro contiene nombre, apellido ni DNI del
  paciente, ni el contenido de un archivo (FR-029).
- Ninguna prueba `unit` usa la red, la base, el bucket real ni `torch`.
- Antes de cada commit: `pytest -m "unit or architecture"`, `ruff check src tests`,
  `python scripts/check_naming_convention.py` y, desde US3, `node --test "tests/unit/web/*.js"`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: rama y documentos de diseño versionados

- [X] T001 Crear la rama `feat/rest-api-viewer` desde `feat/services-pipeline` (`git switch -c feat/rest-api-viewer`) y versionar `specs/004-rest-api-viewer/` con el commit `docs(specify): agrega la especificacion y el plan de la api rest y el visor`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: tipos del dominio, configuración y el esqueleto de la capa `api/` que usan
todas las historias

**⚠️ CRITICAL**: ninguna historia empieza hasta terminar esta fase

- [X] T002 [P] Escribir las pruebas del dominio:
  - `tests/unit/domain/test_entities.py`: `Lesion(...)` sin `organ` deja `organ is None`, `Lesion.organ` acepta `OrganName.LUNG`; `StoredResult(study_code)` deja `volume_path is None`;
  - `tests/unit/domain/test_enums.py`: `ResultFile` tiene exactamente `ORGAN_MESH = "organ_mesh"`, `TUMOR_MESH = "tumor_mesh"` y `VOLUME = "volume"`;
  - `tests/unit/domain/test_exceptions.py`: `InvalidStudyStateError` es subclase de `RadVol3DError`.
- [X] T003 Implementar los cambios del dominio (data-model.md §2) para que pase T002:
  - `src/radvol3d/domain/entities.py`: campo `organ: OrganName | None = None` en `Lesion`, al final, para no romper los constructores posicionales; `volume_path: str | None = None` en `StoredResult`;
  - `src/radvol3d/domain/enums.py`: `ResultFile(StrEnum)`;
  - `src/radvol3d/domain/exceptions.py`: `InvalidStudyStateError(RadVol3DError)` con docstring en español ("la operacion no corresponde al estado del estudio").
- [X] T004 [P] Agregar `MAX_PROJECTION_BYTES: Final[int] = 1_048_576` a `src/radvol3d/config.py`. El comentario dice "1 MiB: un .npy de 128 x 128 pesa 65 664 bytes en float32 y 131 200 en float64 (research.md R7)". Agregar la prueba del valor en `tests/unit/test_config.py`; crear el archivo si no existe.
- [X] T005 Borrar los esqueletos: `src/radvol3d/api/routers/reconstruction_router.py`, `src/radvol3d/api/routers/segmentation_router.py`, `src/radvol3d/api/schemas/reconstruction_schema.py` y `src/radvol3d/api/schemas/segmentation_schema.py`. Quitar sus `import` e `include_router` de `src/radvol3d/main.py`. Actualizar `tests/unit/test_main_lifespan.py` si los nombra. `pytest -m "unit or architecture"` queda en verde.
- [X] T006 [P] Crear `src/radvol3d/api/schemas/error_schema.py` con:
  - `ErrorResponse(detail: str)`;
  - `ValidationErrorItem(loc: list[str | int], msg: str, type: str)`;
  - `ValidationErrorResponse(detail: list[ValidationErrorItem])`.
  No tiene campo `input` (research.md R8).
- [X] T007 Actualizar primero la prueba y después el traductor de errores:
  - `tests/unit/api/test_error_handlers.py`: los cuerpos esperados pasan de `{"detalle": ...}` a `{"detail": ...}`; agregar `InvalidStudyStateError → 409` y `DuplicateStudyError → 409`;
  - `src/radvol3d/api/error_handlers.py`: devolver `{"detail": str(exc)}` y agregar esas dos entradas a `STATUS_BY_ERROR`. El resto de la tabla R8 va en US2.

**Checkpoint**: el dominio, la configuración y el esqueleto de errores están listos.

---

## Phase 3: User Story 1 - Cargar y procesar un estudio por HTTP (Priority: P1) 🎯 MVP

**Goal**: el flujo crear → subir las cuatro proyecciones → procesar en segundo plano →
consultar el estado funciona por HTTP.

**Independent Test**: con `create_app(container_builder=FakeServiceContainer)` y
`TestClient`, recorrer `POST /studies`, `POST /projections`, `POST /process` y
`GET /status`. Comprobar los códigos 201, 201, 202 y 200, la forma de cada respuesta, y que
`run_processing` se agregó una sola vez como tarea en segundo plano.

### Tests for User Story 1 ⚠️

> Escribirlas primero y comprobar que fallan.

- [X] T008 [P] [US1] En `tests/unit/persistence/repositories/test_projection_repository.py`, probar `count_by_study(study_code)` con `FakeDatabase`: devuelve el entero de `select count(*)`, lanza `StudyNotFoundError` si el estudio no existe y `InvalidStudyIdError` para un código inválido.
- [X] T009 [P] [US1] En `tests/unit/persistence/repositories/test_study_repository.py`, probar `list_codes_by_status(status)`: devuelve los códigos en orden de `created_at` y rechaza un estado fuera de `StudyStatus` con `PersistenceError`.
- [X] T010 [P] [US1] En `tests/unit/persistence/test_study_metadata_store.py` (contrato persistence_api_changes.md), con `FakeDatabase` e `InMemoryBucket`, probar:
  - `create_study`: crea paciente, estudio y cuatro etapas en una transacción y no sube nada al bucket;
  - `add_projections`:
    - bloquea con `lock_status`;
    - lanza `InvalidStudyStateError` si el estudio no está `pending` o ya tiene proyecciones (`count_by_study > 0`), sin subir nada;
    - valida los cuatro ángulos y sube `angle_000.npy` … `angle_135.npy`;
  - `claim_for_processing`:
    - lanza `InvalidStudyStateError` si el estado no es `pending` o si `count_by_study != 4`;
    - si cumple, llama a `update_status(..., PROCESSING)` en la misma transacción que `lock_status`;
  - `load_projections`: devuelve `{0: ..., 45: ..., 90: ..., 135: ...}` con los arreglos bajados del bucket;
  - `register_study`: sigue devolviendo el estudio completo (prueba de regresión de 001).
- [X] T011 [P] [US1] En `tests/unit/persistence/test_processing_progress_store.py`, probar `fail_interrupted_studies()`:
  - un estudio en `processing` con la etapa 2 en `running`: la etapa 2 pasa a `failed`, la 3 y la 4 a `skipped` y el estudio a `failed`;
  - si no hay ninguna etapa en `running`, la primera en `waiting` pasa a `failed`;
  - devuelve los códigos;
  - no toca los estudios en otros estados.
- [X] T012 [P] [US1] En `tests/unit/services/test_study_service.py` (contrato services_api_changes.md), con dobles de los almacenes y de la fábrica, probar:
  - `create_study`:
    - llama primero a `factory.strategies_for(organ)`;
    - con `ModelNotAvailableError`, no llama a `metadata_store.create_study`;
  - `add_projections`: llama a `ProjectionLoader.parse` y, si lanza `InvalidProjectionError`, no llama a la persistencia;
  - `start_processing`:
    - comprueba el modelo antes de `claim_for_processing`;
    - con `ModelNotAvailableError`, no reclama el estudio;
  - `run_processing`:
    - nunca lanza;
    - con una tubería que falla, no vuelve a marcar el estudio (eso ya lo hizo la tubería);
    - si `load_projections` lanza `StorageError`, llama a `fail_from_stage(code, StageNumber.PREPROCESSING)`;
    - el registro (`caplog`) trae el código y el nombre del tipo de error, pero no el texto del error;
  - `process_study`:
    - conserva el resultado de 002;
    - lanza `StageFailedError` si la tubería falló;
  - `recover_interrupted_studies`: devuelve lo que devuelve `fail_interrupted_studies`.
- [X] T013 [P] [US1] En `tests/unit/services/test_service_container.py`, probar que `build_service_container` llama una sola vez a `recover_interrupted_studies` después de armar el servicio y registra cuántos estudios recuperó, sin otros datos.
- [X] T014 [P] [US1] Crear `tests/unit/api/test_study_schema.py` y probar los esquemas de data-model.md §5:
  - `StudyCreate.study_code` rechaza lo que no cumpla `^[A-Za-z0-9_-]{1,64}$`;
  - `organ` solo acepta `lung` o `liver`;
  - `PatientInput.first_name` y `last_name` admiten "hasta 80 caracteres";
  - `national_id` exige "8 dígitos";
  - `StudyResponse` y `StudyStatusResponse` no tienen `first_name`, `last_name` ni `national_id`;
  - `StageStatusResponse.stage_name` es uno de `preprocessing`, `reconstruction`, `segmentation`, `meshing`.
- [X] T015 [P] [US1] Crear `tests/unit/api/test_study_router.py`, con `create_app(container_builder=FakeServiceContainer)` y `TestClient`. Probar:
  - `POST /studies`:
    - responde 201 con `study_code`, `organ`, `status="pending"`, `created_at` y `patient_code`, más `Location: /studies/{code}/status`;
    - el servicio recibe `PatientDetails` con los datos del paciente;
  - `GET /studies/{code}/status`:
    - responde 200 con las cuatro etapas en orden y `stage_name` correcto;
    - la respuesta no contiene nombre, apellido ni DNI, aunque el `Study` doble los traiga;
  - `POST /studies/{code}/process`:
    - responde 202 con `{"study_code", "status": "processing", "status_url"}`;
    - `start_processing` se llama una vez dentro del pedido y `run_processing` una vez después de la respuesta;
    - si `start_processing` lanza, `run_processing` no se llama.
- [X] T016 [P] [US1] Crear `tests/unit/api/test_projection_router.py`. Probar:
  - con los cuatro campos `angle_000`, `angle_045`, `angle_090` y `angle_135` (bytes de `tests/fixtures/projection_files.valid_npy`), responde 201 con `{"study_code", "angles": [0, 45, 90, 135]}`;
  - el servicio recibe cuatro `ProjectionFile` cuyo ángulo sale del nombre del campo, aunque el nombre del archivo diga otro ángulo;
  - si falta un campo, 422;
  - con un archivo de `MAX_PROJECTION_BYTES + 1` bytes, 413 con un mensaje que nombra el ángulo y el límite, y el servicio no se llama;
  - el router lee a lo sumo `MAX_PROJECTION_BYTES + 1` bytes por archivo (un `UploadFile` doble que cuenta las lecturas).

### Implementation for User Story 1

- [X] T017 [P] [US1] Implementar `ProjectionRepository.count_by_study` en `src/radvol3d/persistence/repositories/projection_repository.py` (pasa T008).
- [X] T018 [P] [US1] Implementar `StudyRepository.list_codes_by_status` en `src/radvol3d/persistence/repositories/study_repository.py` (pasa T009).
- [X] T019 [US1] Implementar `create_study`, `add_projections`, `claim_for_processing` y `load_projections` en `src/radvol3d/persistence/study_metadata_store.py`, y reescribir `register_study` como `create_study` + `add_projections` en una sola transacción (pasa T010). Depende de T017 y T018. Mensajes en español, con el código del estudio y el estado actual, sin datos del paciente. El docstring del módulo agrega el orden de cada operación nueva.
- [X] T020 [US1] Implementar `fail_interrupted_studies` en `src/radvol3d/persistence/processing_progress_store.py` (pasa T011). Una transacción por estudio. El docstring dice "supone un solo proceso de uvicorn (research.md R4 y R5)".
- [X] T021 [US1] Implementar en `src/radvol3d/services/study_service.py` los métodos `create_study`, `add_projections`, `start_processing`, `run_processing` y `recover_interrupted_studies`, y reescribir `process_study` como su composición (pasa T012). Depende de T019 y T020.
- [X] T022 [US1] En `src/radvol3d/services/service_container.py`, llamar a `study_service.recover_interrupted_studies()` al final de `build_service_container` y registrar la cantidad con `logger.info` (pasa T013).
- [X] T023 [P] [US1] Reescribir `src/radvol3d/api/schemas/study_schema.py` con `PatientInput`, `StudyCreate`, `StudyResponse`, `StageStatusResponse`, `StudyStatusResponse` y `ProcessingAccepted`, con las reglas de data-model.md §5 (pasa T014). Crear `src/radvol3d/api/schemas/projection_schema.py` con `ProjectionsUploaded(study_code: str, angles: list[int])`.
- [X] T024 [US1] Reescribir `src/radvol3d/api/routers/study_router.py` con `POST /studies` (201 y `Location`), `GET /studies/{study_code}/status` y `POST /studies/{study_code}/process` (202 y `BackgroundTasks.add_task(service.run_processing, study_code)`), con `Depends(get_study_service)` y `response_model` en cada ruta (pasa T015). Depende de T023.
- [X] T025 [US1] Crear `src/radvol3d/api/routers/projection_router.py` con `POST /studies/{study_code}/projections` (pasa T016):
  - recibe cuatro parámetros `UploadFile` obligatorios: `angle_000`, `angle_045`, `angle_090` y `angle_135`;
  - lee de cada uno `config.MAX_PROJECTION_BYTES + 1` bytes y responde 413 si se pasa;
  - arma un `ProjectionFile(angle, content, upload.filename)` por archivo;
  - llama a `service.add_projections`.
- [X] T026 [US1] Montar `study_router` y `projection_router` en `src/radvol3d/main.py`, antes del montaje de `StaticFiles`.
- [ ] T027 [US1] Crear `tests/integration/persistence/test_study_lifecycle_integration.py` (marcador `integration`, Supabase de prueba, prefijo `it_`) y probar:
  - `create_study` → `add_projections` → `claim_for_processing` deja el estudio en `processing`;
  - una segunda `add_projections` lanza `InvalidStudyStateError`;
  - dos `claim_for_processing` en dos hilos a la vez: exactamente uno tiene éxito y el otro lanza `InvalidStudyStateError`;
  - `fail_interrupted_studies` deja el estudio y sus etapas como en T011.
- [X] T028 [US1] Crear `tests/concurrency/test_background_processing.py` (marcador `concurrency`), para FR-032 y SC-003:
  - levanta uvicorn en un hilo, en un puerto libre;
  - usa un contenedor doble cuyo `run_processing` espera un `threading.Event`;
  - lanza `POST /process` de un estudio y, mientras espera, 10 pedidos `GET /status` de otro estudio;
  - comprueba que cada uno responde en menos de 1 s; al final libera el evento y apaga el servidor.

**Checkpoint**: el flujo principal funciona por HTTP con el servicio doble y contra la base
de prueba.

---

## Phase 4: User Story 2 - Rechazar pedidos inválidos con mensajes claros (Priority: P1)

**Goal**: cada error del dominio llega con su código HTTP y un mensaje claro en español, y
ninguna respuesta contiene datos del paciente.

**Independent Test**: con el servicio doble configurado para lanzar cada error del dominio,
comprobar el código y el cuerpo de cada caso. Ningún cuerpo debe contener el nombre, el
apellido ni el DNI que se enviaron.

### Tests for User Story 2 ⚠️

- [X] T029 [P] [US2] Ampliar `tests/unit/api/test_error_handlers.py` con la tabla completa de research.md R8, parametrizada:
  - 404: `StudyNotFoundError`, `StorageObjectNotFoundError`;
  - 400: `InvalidStudyIdError`;
  - 422: `InvalidProjectionError`, `InvalidPatientDataError`, `UnknownOrganError`;
  - 409: `DuplicateStudyError`, `StudyInProgressError`, `InvalidStudyStateError`;
  - 503: `ModelNotAvailableError`, `DatabaseUnavailableError`;
  - 500: `StorageError`, `StageFailedError`, `PersistenceError`, `InvalidLesionError`, `PatientCodeExhaustedError`.
  Además: un `RuntimeError("detalle interno")` da 500 con un mensaje genérico en español que no contiene `"detalle interno"` ni `"Traceback"`.
- [X] T030 [P] [US2] Crear `tests/unit/api/test_validation_privacy.py` y probar:
  - `POST /studies` con `patient.national_id = "1234567X"` da 422 con `detail` como lista de `{loc, msg, type}`, sin clave `input`, y el cuerpo no contiene `"1234567X"`;
  - lo mismo con un `first_name` de 81 caracteres;
  - en cada error de US2 provocado con datos del paciente en el pedido, ni el cuerpo ni los registros (`caplog`) contienen el nombre, el apellido ni el DNI enviados (SC-005).
- [X] T031 [P] [US2] Crear `tests/unit/api/test_study_router_errors.py` con los escenarios 1 a 6 de US2. El servicio doble lanza el error del dominio de cada caso:
  - código repetido → 409;
  - código inválido → 400;
  - `organ` fuera del enum → 422 de validación;
  - `liver` → 503 con el mensaje del servicio;
  - subida con un `.npy` inválido → 422 que nombra el ángulo;
  - `process` sobre un estudio sin proyecciones o en otro estado → 409;
  - código inexistente en `status`, `process` y `projections` → 404.

### Implementation for User Story 2

- [X] T032 [US2] Completar `src/radvol3d/api/error_handlers.py` (pasa T029 y T030):
  - `STATUS_BY_ERROR` con toda la tabla R8;
  - un manejador de `RequestValidationError` que devuelve 422 con `detail` como lista de `{loc, msg, type}`, sin `input` ni `ctx`;
  - un manejador de `Exception` que devuelve 500 con `{"detail": "Error interno del servidor."}` y registra solo el tipo del error.
- [X] T033 [US2] Revisar los mensajes de los errores nuevos de T019 a T025: deben estar en español, nombrar el código, el ángulo o el estado, y no incluir datos del paciente. Ajustar los que no cumplan, hasta que T031 pase completo.

**Checkpoint**: US1 y US2 juntas forman el MVP de la API.

---

## Phase 5: User Story 3 - Ver el resultado en 3D (Priority: P2)

**Goal**: un estudio `completed` muestra en el visor el órgano semitransparente y una malla
opaca por lesión, cada una en su color, con la lista de lesiones al lado. Cada lesión tiene
su `.glb` y su fila de `lesion` con `organ` y su propio `mesh_path`.

**Independent Test**: procesar un estudio con los dobles (que generan una `.glb` por región)
y abrir `/viewer/{code}`. Se ven la malla del órgano y una por lesión; la lista muestra una
fila por lesión, con su color y el órgano `lung`, sin `region_id`. `node --test
tests/unit/web/` y las pruebas de `result_router` y `viewer_router` en verde.

### Tests for User Story 3 ⚠️

- [X] T034 [P] [US3] En `tests/unit/persistence/test_storage_layout.py`, probar `lesion_mesh_path`:
  - `("lung_028", 1)` → `"lung_028/meshes/lesion_001.glb"`;
  - `12` → `lesion_012.glb`;
  - `0`, `-1`, `True` y `"1"` → `InvalidLesionError`;
  - un código inválido → `InvalidStudyIdError`.
- [X] T035 [P] [US3] En `tests/unit/persistence/repositories/test_lesion_repository.py`, probar:
  - `add_many` emite un `insert into lesion (... organ) select ... from study s join organ o` que toma `o.name`, y no usa `Lesion.organ`;
  - `list_by_study` devuelve `Lesion.organ` como `OrganName`.
- [X] T036 [P] [US3] En `tests/unit/persistence/test_result_store.py`, probar:
  - `save_result(..., lesion_meshes=[...])` lanza `PersistenceError` si `len(lesion_meshes)` no es igual al número de regiones con lesión, sin subir nada;
  - con dos regiones, sube `lesion_001.glb` y `lesion_002.glb` con tipo `model/gltf-binary`, y cada fila guarda su propio `mesh_path`;
  - con `regions: []` y `lesion_meshes=[]`, no sube mallas de lesión;
  - `get_result` devuelve `volume_path` y las lesiones con `organ`;
  - `read_file(code, ResultFile.ORGAN_MESH)` baja `organ.glb`, y lo mismo con `TUMOR_MESH` y `VOLUME`;
  - `read_lesion_mesh(code, 2)` baja el `mesh_path` de la segunda fila; con `3`, sobre dos lesiones, lanza `StorageObjectNotFoundError`.
  Actualizar las pruebas existentes de `save_result` a la firma nueva.
- [X] T037 [P] [US3] Crear `tests/unit/services/test_lesion_regions.py` (research.md R9) y probar `split_lesion_masks`:
  - con una máscara sintética de tres regiones y sus regiones de `summarize_regions(mask, probability, 2.5)`, devuelve tres máscaras booleanas en el orden del resumen, cada una igual a su componente;
  - una región con `voxels` o `centroid_voxel` que no coincide con ninguna componente lanza `ValueError`;
  - `regions=[]` devuelve `[]`;
  - con la entrada de `tests/unit/services/reference/lung_region_summary_reference.json`, la suma de las máscaras es igual a `mask > 0`. Ese archivo todavía no existe (lo genera `scripts/generate_regression_reference.py` con `models/`): si falta, este caso se omite con `pytest.skip`, igual que `test_lung_region_summary.py`.
- [X] T038 [P] [US3] En `tests/unit/services/test_marching_cubes_strategy.py`, probar `build_meshes(volume, mask, regions)` con dos regiones:
  - `MeshSet.lesions` tiene dos `.glb` válidos (`trimesh.load` las abre), distintos entre sí, y cada uno solo cubre su región (cajas límite disjuntas, en mm y centradas como el órgano);
  - una región que no da superficie produce un `.glb` válido sin geometría;
  - `MeshSet(organ, tumor)` sin `lesions` deja `()`.
  Actualizar las llamadas existentes a la firma nueva.
- [X] T039 [P] [US3] En `tests/unit/services/test_study_service.py`, probar:
  - `get_completed_result`, `read_result_file` y `read_lesion_mesh` lanzan `InvalidStudyStateError` si el estudio no está `completed`, con el estado en el mensaje;
  - en `completed`, delegan en `ResultStore`.
- [X] T040 [P] [US3] Crear `tests/unit/api/test_result_router.py` (contrato http_api.md, "Resultados") y probar:
  - `GET /result`: 200 con `organ_mesh_url`, `tumor_mesh_url`, `volume_url` y `lesions[*]` con `lesion_number` desde 1, `organ`, `location`, `volume_mm3`, `max_diameter_mm`, `confidence` y `mesh_url` = `/studies/{code}/result/lesions/{n}.glb`, sin `region_id` ni `lesion_id`;
  - `organ.glb` y `tumor.glb`: `model/gltf-binary`;
  - `volume.npy`: `application/octet-stream` con `Content-Disposition: attachment; filename="<code>_volume.npy"`;
  - `lesions/{n}.glb`: `model/gltf-binary`, y 404 si el servicio lanza `StorageObjectNotFoundError`;
  - 409 si el servicio lanza `InvalidStudyStateError`.
- [X] T041 [P] [US3] Crear `tests/unit/api/test_viewer_router.py` y probar `GET /viewer/{code}`:
  - estudio existente: 200, `text/html`, con el contenido de `src/radvol3d/web/viewer.html`;
  - estudio inexistente: 404 con la misma página;
  - código inválido: 400;
  - la página referencia `/css/main.css` y `/js/viewer_3d.js` con ruta absoluta, y tiene un `importmap` con `three@<versión exacta>` (no `latest`).
- [X] T042 [P] [US3] Crear `tests/unit/web/test_viewer_state.js` (`node:test` y `node:assert/strict`; sin npm), que importe `../../../src/radvol3d/web/js/viewer_state.js`, y probar:
  - `LESION_PALETTE` tiene exactamente `["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"]`;
  - `lesion_color(index)` repite la paleta desde la octava lesión;
  - `ORGAN_COLOR` es un gris claro distinto de la paleta;
  - `lesion_rows(result)` devuelve una fila por lesión con `color`, `organ`, `location`, `volume_mm3`, `max_diameter_mm` (o "—" si es `null`), `confidence` y `mesh_url`, y nunca `region_id`;
  - `status_view(status)` devuelve el mensaje y la acción de cada estado: `pending` y `processing` → refrescar cada 5000 ms; `completed` → cargar; `failed` → mostrar la etapa en `failed`; 404 → "no existe".
  Todas las declaraciones en snake_case.

### Implementation for User Story 3

- [X] T043 [P] [US3] Crear `docs/database/schema/002_add_lesion_organ.sql` (research.md R11) con:
  - `alter table lesion add column organ varchar(32);`
  - `update lesion l set organ = o.name from study s join organ o on o.organ_id = s.organ_id where s.study_id = l.study_id;`
  - `alter table lesion alter column organ set not null;`
  - `alter table lesion add constraint lesion_organ_allowed check (organ in ('lung', 'liver'));`
  - un `comment on column lesion.organ` en español.
  Aplicarla en el Supabase de prueba con el editor SQL.
- [X] T044 [US3] Implementar `lesion_mesh_path` en `src/radvol3d/persistence/storage_layout.py` y reemplazar en el docstring la nota "ruta reservada `lesion_<region_id>.glb`" por la ruta nueva (pasa T034).
- [X] T045 [US3] Actualizar `src/radvol3d/persistence/repositories/lesion_repository.py`: el `insert ... select` toma `organ` del estudio; `list_by_study` lee `l.organ` y lo convierte a `OrganName` (pasa T035).
- [X] T046 [US3] Actualizar `src/radvol3d/persistence/result_store.py` (pasa T036):
  - `save_result(..., lesion_meshes: Sequence[bytes])`: valida la cantidad antes de subir; sube cada malla con `lesion_mesh_path(code, n)`; arma cada `Lesion` con su `mesh_path`;
  - `get_result` devuelve `volume_path`;
  - nuevos `read_file(study_code, file: ResultFile)` y `read_lesion_mesh(study_code, lesion_number)`.
  El docstring del módulo pasa de cinco archivos a "cinco archivos más una malla por lesión". Depende de T044 y T045. Commit `feat(persistence)!`.
- [X] T047 [P] [US3] Crear `src/radvol3d/services/meshing/lesion_regions.py` con `split_lesion_masks(mask, regions)`, usando `scipy.ndimage.label` con la conectividad por omisión y el emparejamiento por `voxels` y `centroid_voxel` (pasa T037). Solo numpy y scipy.
- [X] T048 [US3] Actualizar las mallas (pasa T038). Depende de T047. Commit `feat(services)!`.
  - `src/radvol3d/services/meshing/meshing_strategy.py`:
    - `MeshSet.lesions: tuple[bytes, ...] = ()`;
    - `build_meshes(self, volume, mask, regions)`, con su docstring.
  - `src/radvol3d/services/meshing/marching_cubes_strategy.py`: genera `lesions` con `split_lesion_masks` y `_surface(region, volume.shape, TUMOR_STEP)`.
- [X] T049 [US3] Actualizar los dobles en `tests/fixtures/fake_strategies.py`:
  - la región de `FakeSegmentationStrategy` agrega `"voxels": 512` y `"centroid_voxel": [64, 64, 64]` (el cubo `[60:68]³`);
  - `FakeMeshingStrategy.build_meshes(volume, mask, regions)` devuelve `lesions` con un `b"glTF" + bytes([3 + i]) * 16` por región;
  - `FailingMeshingStrategy` usa la firma nueva.
  Actualizar `tests/unit/services/test_fake_strategies.py`.
- [X] T050 [US3] En `src/radvol3d/services/pipeline/filters.py`, hacer que `MeshingFilter` pase `[r for r in summary["regions"] if r.get("has_lesion", True) is True]`. En `src/radvol3d/services/pipeline/persistence_progress.py`, hacer que `save_result` pase `meshes.lesions`. Actualizar `tests/unit/services/test_pipeline_filters.py`, `tests/unit/services/test_persistence_progress.py` y `tests/unit/services/test_processing_pipeline.py` si fallan. Depende de T046, T048 y T049.
- [X] T051 [US3] Implementar `get_completed_result`, `read_result_file` y `read_lesion_mesh` en `src/radvol3d/services/study_service.py` (pasa T039).
- [X] T052 [P] [US3] Crear `src/radvol3d/api/content_types.py` con `GLB_CONTENT_TYPE = "model/gltf-binary"` y `NPY_CONTENT_TYPE = "application/octet-stream"`. Crear `src/radvol3d/api/schemas/result_schema.py` con `LesionResponse` y `ResultResponse` (data-model.md §5), sin `region_id` ni `lesion_id`.
- [X] T053 [US3] Crear `src/radvol3d/api/routers/result_router.py` con `GET /studies/{study_code}/result` y las cuatro descargas de research.md R6 (`Response` con los bytes y el tipo de contenido). Las URL se arman con el código y `lesion_number`, nunca con rutas del bucket (pasa T040). Depende de T051 y T052.
- [X] T054 [US3] Crear `src/radvol3d/api/routers/viewer_router.py` con `GET /viewer/{study_code}` (pasa T041):
  - valida el código con `service.get_study`;
  - devuelve `FileResponse` de `src/radvol3d/web/viewer.html`, con 404 y la misma página si lanza `StudyNotFoundError`;
  - la ruta del HTML se calcula con `Path(__file__)`; no importa nada de `main.py`.
- [X] T055 [US3] Montar `result_router` y `viewer_router` en `src/radvol3d/main.py`, antes de `StaticFiles`.
- [X] T056 [P] [US3] Crear `src/radvol3d/web/js/viewer_state.js` (pasa T042): solo funciones puras y constantes exportadas, sin DOM ni Three.js.
- [X] T057 [US3] Reescribir `src/radvol3d/web/viewer.html`:
  - `importmap` con `three` y `three/addons/` apuntando a `https://cdn.jsdelivr.net/npm/three@<versión>/build/three.module.js` y `.../examples/jsm/`, con una versión exacta comprobada en `https://www.npmjs.com/package/three` el día de la implementación y anotada en un comentario con esa fecha;
  - contenedor del lienzo, lista de lesiones, zona de avisos, botón "Vista inicial";
  - enlaces de descarga ocultos para el caso sin WebGL;
  - rutas absolutas `/css/main.css` y `/js/viewer_3d.js`;
  - textos en español.
- [X] T058 [US3] Reescribir `src/radvol3d/web/js/viewer_3d.js` según research.md R13 y http_api.md, "Visor", pasos 1 a 7:
  - lee el código de `location.pathname` y pide el estado con `fetch`, refrescándolo con `status_view`;
  - en `completed`:
    - pide el resultado y carga cada `.glb` con `GLTFLoader`;
    - el órgano usa `MeshStandardMaterial({color: ORGAN_COLOR, transparent: true, opacity: 0.3, depthWrite: false})`;
    - cada lesión es opaca, con `lesion_color(i)`;
    - `OrbitControls` para rotar, acercar y desplazar;
    - la vista inicial encuadra la caja del órgano;
  - elegir una fila resalta su malla (emisivo) y baja la opacidad de las demás; otro clic lo deshace;
  - sin WebGL, o si falla el `import` de Three.js, muestra el aviso y los enlaces de descarga.
  Las declaraciones van en snake_case. Depende de T056 y T057.
- [X] T059 [P] [US3] Agregar a `src/radvol3d/web/css/main.css` los estilos del visor: lienzo a pantalla, lista lateral con la muestra de color de cada fila, fila resaltada y avisos. Las clases van en snake_case.
- [X] T060 [US3] En `.github/workflows/ci.yml`, agregar `actions/setup-node@v4` con `node-version: "22"` y el paso `node --test "tests/unit/web/*.js"`, después de "Estilo y convencion de nombres".
- [X] T061 [US3] Actualizar `tests/integration/persistence/test_result_storage_integration.py`, con la migración 002 aplicada en la base de prueba. Probar:
  - cada fila de `lesion` tiene `organ = 'lung'` y su propio `mesh_path` `lesion_<NNN>.glb`, que existe en el bucket;
  - un `insert` con `organ = 'kidney'` hecho a mano viola `lesion_organ_allowed`.
- [X] T062 [US3] Actualizar `tests/integration/services/test_pipeline_integration.py`: el estudio procesado con los dobles tiene `lesion_001.glb` en el bucket, y su `get_result().lesions[0].mesh_path` apunta a ese archivo.

**Checkpoint**: el resultado se ve en el visor con una malla por lesión.

---

## Phase 6: User Story 4 - Borrar un estudio (Priority: P3)

**Goal**: `DELETE /studies/{code}` borra el estudio y todos sus archivos, incluidas las
mallas por lesión.

**Independent Test**: con el servicio doble, `DELETE` responde 204 y, sobre un estudio en
`processing`, 409. Contra la base de prueba, después de borrar no queda ningún archivo bajo
el código del estudio.

### Tests for User Story 4 ⚠️

- [ ] T063 [P] [US4] En `tests/unit/persistence/test_object_storage.py`, probar `list_names(folder)` sobre `InMemoryBucket`:
  - devuelve solo los nombres de los archivos que están directamente en la carpeta;
  - una carpeta vacía o inexistente da `[]`;
  - una falla del bucket da `StorageError`, sin la clave en el mensaje.
- [ ] T064 [P] [US4] En `tests/unit/persistence/test_study_metadata_store.py`, probar que `delete_study`:
  - borra las diez rutas fijas más `lesion_001.glb` y `lesion_002.glb` presentes en `<code>/meshes/`;
  - no borra archivos de otro estudio;
  - deja todo intacto, con `StudyInProgressError`, si el estudio está en `processing`.
- [ ] T065 [P] [US4] En `tests/unit/api/test_study_router.py`, probar `DELETE /studies/{code}`: responde 204 sin cuerpo; 409 si el servicio lanza `StudyInProgressError`; 404 si lanza `StudyNotFoundError`.

### Implementation for User Story 4

- [ ] T066 [US4] Agregar `list(path)` a `InMemoryBucket` en `tests/fixtures/fake_object_storage.py`, con la misma forma que el `list` de storage3: entradas `{"name": ...}`. Implementar `ObjectStorage.list_names(folder)` en `src/radvol3d/persistence/object_storage.py` (pasa T063).
- [ ] T067 [US4] En `src/radvol3d/persistence/study_metadata_store.py`, hacer que `delete_study` borre también los `lesion_*.glb` que liste `list_names(f"{code}/meshes")`, dentro de la misma transacción. Actualizar el docstring del módulo: ya no son "sus diez archivos" (pasa T064). Depende de T066.
- [ ] T068 [US4] Agregar `DELETE /studies/{study_code}` (204) a `src/radvol3d/api/routers/study_router.py`, llamando a `service.delete_study` (pasa T065).
- [ ] T069 [US4] Actualizar `tests/integration/services/test_delete_study_integration.py` y la limpieza de `tests/integration/conftest.py`: después de borrar un estudio procesado con los dobles, `list_names` de `<code>/`, `<code>/projections`, `<code>/segmentation` y `<code>/meshes` devuelve `[]`.

**Checkpoint**: las cuatro historias funcionan.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: punta a punta, CI y documentación

- [ ] T070 Crear `tests/e2e/app_with_fakes.py` con `create_app_with_fakes()`. Arma un `ServiceContainer` con `build_service_container`, la configuración de `.env.test` y `StrategyBuilders` con `FakeReconstructionStrategy`, `FakeSegmentationStrategy` y `FakeMeshingStrategy`, y devuelve `create_app(container_builder=...)`. Si falta `.env.test`, lanza `ConfigurationError` con un mensaje claro. Lo usan T071 y quickstart.md §4.
- [ ] T071 Crear `tests/e2e/test_http_flow.py` (marcador `e2e`, FR-031, SC-001), con `TestClient(create_app_with_fakes())`:
  - `POST /studies` (`it_` + uuid) → `POST /projections` → `POST /process`;
  - `GET /status` en `completed` con las cuatro etapas `completed`;
  - `GET /result`: bajar `organ.glb`, `tumor.glb`, `volume.npy` y `lesions/1.glb` (las `.glb` empiezan con `b"glTF"`);
  - `GET /viewer/{code}` → 200;
  - `DELETE` → 204, y `GET /status` → 404.
- [ ] T072 [P] En `.github/workflows/ci.yml`, agregar después de "Cobertura de services" el paso `coverage report --include="src/radvol3d/api/*" --fail-under=80` (SC-007).
- [ ] T073 [P] Actualizar `docs/architecture/fastapi_structure.md`:
  - los cinco routers por recurso;
  - el procesamiento en segundo plano y el supuesto de un solo proceso de uvicorn (R4 y R5);
  - las descargas por el servicio (R6);
  - el visor y Three.js por CDN (R13);
  - el cuerpo de error `detail` y el 422 sin `input` (R8).
- [ ] T074 [P] Actualizar `docs/database/data_dictionary.md` y `docs/database/entity_relationship.md`: `lesion.organ` (`varchar(32)`, no nulo, `lesion_organ_allowed`), `mesh_path` por lesión y la migración 002.
- [ ] T075 [P] Actualizar `docs/models/meshing.md` con la malla por lesión: emparejamiento por `voxels` y `centroid_voxel` (R9), misma escala y origen que el órgano, y `lesion_<NNN>.glb`.
- [ ] T076 [P] Actualizar `docs/standards/testing_strategy.md` con la fila de `tests/unit/web/` (`node --test`, Node 22, sin npm) y el uso de `tests/e2e/app_with_fakes.py`.
- [ ] T077 [P] Reescribir `specs/001-persistence-schema-migration/contracts/persistence_api.md` con los cambios de [contracts/persistence_api_changes.md](contracts/persistence_api_changes.md): `create_study`, `add_projections`, `claim_for_processing`, `load_projections`, `fail_interrupted_studies`, la firma nueva de `save_result`, `read_file`, `read_lesion_mesh`, `lesion_mesh_path`, `list_names` y `lesion.organ`.
- [ ] T078 Correr la validación completa de [quickstart.md](quickstart.md):
  - §1: estilo, nombres, `unit` y `architecture`, `node --test` y cobertura de `api/`;
  - §2: migración;
  - §3: `integration`, `e2e` y `concurrency`;
  - §4 y §5: recorrido manual con `uvicorn --factory tests.e2e.app_with_fakes:create_app_with_fakes`, midiendo SC-002 y SC-004.
  Anotar en el pull request lo que se midió.
- [ ] T079 Aplicar `docs/database/schema/002_add_lesion_organ.sql` en la base real de Supabase (editor SQL), después de mergear el pull request. En el pull request, avisar los tres cambios `!`: `save_result`, `build_meshes` y el cuerpo de error `detail`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup. Bloquea todas las historias.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de Foundational. Sus pruebas T031 usan las rutas de US1, así que en la práctica va después de T024 a T026.
- **US3 (Phase 5)**: depende de Foundational. Para el recorrido completo en el visor necesita US1 (crear y procesar). Sus piezas de persistencia y mallas (T034 a T050) no dependen de US1.
- **US4 (Phase 6)**: depende de Foundational. T067 cubre las mallas por lesión, que crea US3; sus pruebas unitarias ponen esos archivos a mano en `InMemoryBucket`, así que no necesitan US3.
- **Polish (Phase 7)**: depende de las cuatro historias.

### User Story Dependencies

- **US1 (P1)**: ninguna.
- **US2 (P1)**: usa las rutas de US1 para sus escenarios.
- **US3 (P2)**: usa el flujo de US1 para tener un estudio `completed`. Los cambios de mallas y persistencia son independientes.
- **US4 (P3)**: independiente. Su prueba de integración (T069) es más completa con US3.

### Within Each User Story

- Las pruebas primero, y deben fallar.
- Persistencia → servicios → esquemas → routers → `main.py` → integración.
- Un commit por grupo lógico, con el ámbito de la carpeta (`feat(persistence)`, `feat(services)`, `feat(api)`, `feat(web)`, `test(...)`).

### Parallel Opportunities

- Foundational: T002, T004 y T006 son de archivos distintos.
- US1: las pruebas T008 a T016; luego T017, T018 y T023.
- US2: T029, T030 y T031.
- US3:
  - pruebas: T034 a T042;
  - persistencia (T043 a T046) y mallas (T047 a T049), en paralelo entre sí;
  - visor: T056 y T059 en paralelo con la API (T052 a T055).
- US4: T063, T064 y T065.
- Polish: T072 a T077.

---

## Parallel Example: User Story 3

```bash
# Pruebas de US3 juntas (archivos distintos):
Task: "Probar lesion_mesh_path en tests/unit/persistence/test_storage_layout.py"
Task: "Probar split_lesion_masks en tests/unit/services/test_lesion_regions.py"
Task: "Probar result_router en tests/unit/api/test_result_router.py"
Task: "Probar viewer_state.js en tests/unit/web/test_viewer_state.js"

# Dos frentes de implementación en paralelo:
Task: "Migración 002 + lesion_repository + result_store (T043-T046)"
Task: "lesion_regions + meshing_strategy + marching_cubes + dobles (T047-T049)"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1 y Phase 2.
2. Phase 3 (US1): el flujo principal por HTTP.
3. Phase 4 (US2): errores claros y sin datos personales.
4. **Parar y validar**: `pytest -m "unit or architecture"`, T027 y T028 en verde.

### Incremental Delivery

1. Setup + Foundational.
2. US1 + US2 → la API se puede usar con cualquier cliente HTTP.
3. US3 → resultado, descargas y visor con una malla por lesión.
4. US4 → borrado completo.
5. Polish → punta a punta, CI, documentación y migración en la base real.

---

## Notes

- `[P]`: archivos distintos, sin dependencias pendientes.
- La versión de Three.js se fija en T057 con un número publicado en npm, con la fecha en
  que se comprobó. No se inventa (Principio V).
- Los cambios `!` (T046, T048 y T032/T007 por `detail`) se avisan en el pull request.
- Si una prueba de 001 o 002 falla por las firmas nuevas, se actualiza en el mismo commit que
  cambia la firma. Nunca se modifica `tests/architecture/test_layer_boundaries.py`.
