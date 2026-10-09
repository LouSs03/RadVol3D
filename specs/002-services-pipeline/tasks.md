---

description: "Lista de tareas: capa de servicios y tubería de procesamiento"
---

# Tasks: Capa de servicios y tubería de procesamiento

**Input**: Design documents from `/specs/002-services-pipeline/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/services_api.md](contracts/services_api.md),
[contracts/persistence_api_changes.md](contracts/persistence_api_changes.md),
[contracts/model_artifacts.md](contracts/model_artifacts.md), [quickstart.md](quickstart.md)

**Tests**: Sí se incluyen. Las exigen el Principio IV de la constitución (una prueba unitaria
por funcionalidad, en el mismo pull request) y FR-033 a FR-035 (pruebas unitarias, de
integración, de concurrencia, de arquitectura y de regresión `ml`). En cada componente, la
prueba se escribe antes que el código y debe fallar.

**Organization**: Las tareas se agrupan por historia (US1 a US5 de la especificación). El
orden sigue el de construcción que pidió el usuario: primero todo con dobles y en verde
(Fases 1 a 7) y, como último bloque, los modelos reales (Fase 8, US5).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (archivos distintos, sin depender de tareas sin terminar)
- **[Story]**: historia de la especificación a la que pertenece la tarea (US1 a US5)
- Todas las rutas son relativas a la raíz del repositorio

## Path Conventions

Proyecto único (ver "Decisión de estructura" en [plan.md](plan.md)):

- Código: `src/radvol3d/domain/`, `src/radvol3d/persistence/`, `src/radvol3d/services/`, y lo
  mínimo de `src/radvol3d/api/` y `src/radvol3d/main.py`
- Scripts: `scripts/`
- Pruebas: `tests/unit/` (`unit`), `tests/integration/` (`integration`), `tests/concurrency/`
  (`concurrency`), `tests/ml/` (`ml`), `tests/architecture/` (`architecture`)
- Dobles: `tests/fixtures/`

Reglas de todas las tareas:

- Identificadores en inglés y snake_case; comentarios y docstrings en español (Principio III).
- Ningún mensaje de error ni registro contiene nombre, apellido o DNI del paciente, ni el
  contenido de un archivo (FR-032).
- Ningún módulo que importe `api/` o que corra en las pruebas `unit` importa `torch` en su
  nivel superior (research.md R2).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependencias, marcador `ml`, archivos ignorados y variables nuevas.

- [X] T001 Agregar `scikit-image>=0.24` y `trimesh>=4.0` a `requirements.txt` y ejecutar `pip install -r requirements-dev.txt`. Comprobar que `from skimage.measure import marching_cubes`, `from skimage.filters import threshold_otsu` e `import trimesh` funcionan. El peso de research.md R3 debe quedar en la descripción del pull request.
- [X] T002 En `pyproject.toml`:
  - agregar `[project.optional-dependencies]` con `ml = ["torch>=2.6"]`;
  - agregar a `[tool.pytest.ini_options].markers` la entrada `"ml: necesita PyTorch y los pesos de los modelos; el CI la omite"`.

  No agregar `torch` a `requirements.txt` (research.md R2).
- [X] T003 [P] Agregar `models/` y `.cache/` a `.gitignore`. Comprobar con `git status --short` que ya no aparecen `models/` ni ningún `.pth`.
- [X] T004 [P] Agregar a `.env.example` y a `.env.test.example` las variables de data-model.md §6, sin valores: `MODEL_BUCKET`, `EN1_WEIGHTS_OBJECT`, `EN2_WEIGHTS_OBJECT`, `MODEL_CACHE_DIR` y `RECONSTRUCTION_STRATEGY`. Agregar un comentario en español que diga que son opcionales y que, si faltan, el modelo queda no disponible pero la aplicación arranca.
- [X] T005 [P] Crear los paquetes y carpetas vacíos:
  - `tests/integration/services/__init__.py`
  - `tests/ml/__init__.py`
  - `tests/ml/reference/.gitkeep`
  - `tests/unit/services/reference/.gitkeep`
  - `tests/unit/scripts/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: dominio, interfaces Strategy con su firma final, dobles, carpeta `services/pipeline/`
y puerto de avance. Todas las historias los usan.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta terminar esta fase.

### Dominio

- [X] T006 [P] Ampliar `tests/unit/domain/test_exceptions.py`:
  - `StageFailedError` y `StudyInProgressError` heredan de `RadVol3DError`;
  - `StageFailedError(study_code="it_a", stage_number=StageNumber.SEGMENTATION)` expone ambos atributos;
  - su mensaje es "La etapa 3 (segmentation) del estudio it_a falló.";
  - el mensaje no incluye el texto de la causa encadenada.
- [X] T007 [P] Ampliar `tests/unit/domain/test_entities.py`:
  - `SegmentationResult(mask, probability, global_confidence)` sigue funcionando sin `summary`, que vale `{}` por omisión;
  - `summary` guarda el mapeo recibido.
- [X] T008 [P] Agregar a `src/radvol3d/domain/exceptions.py`:
  - `StageFailedError(RadVol3DError)`, con `__init__(self, study_code: str, stage_number: StageNumber)`, que arma el mensaje con `stage_number.value` y `stage_number.name.lower()`;
  - `StudyInProgressError(RadVol3DError)`.

  Docstrings en español. `domain/` sigue sin importar nada del proyecto, salvo `domain.enums`.
- [X] T009 [P] Agregar a `SegmentationResult` en `src/radvol3d/domain/entities.py` el campo `summary: Mapping[str, object] = field(default_factory=dict)`, después de `lesions`. Sin lógica ni entrada/salida.

### Interfaces Strategy (firma final, research.md R20)

- [X] T010 [P] En `src/radvol3d/services/reconstruction/reconstruction_strategy.py`, corregir el docstring de `reconstruct`. La entrada es "(4, 128, 128) float32 con las integrales de línea del convenio de TA-2, sin normalizar" y la salida "(128, 128, 128) float32 en [0, 1]". La firma no cambia.
- [X] T011 [P] En `src/radvol3d/services/segmentation/segmentation_strategy.py`, cambiar la firma a `segment(self, volume, study_code: str) -> SegmentationResult`. El docstring debe decir:
  - mask uint8 {0, 1};
  - probability float32 en [0, 1], de la misma forma;
  - summary con las claves de data-model.md §4.

  Actualizar la firma de `src/radvol3d/services/segmentation/liver_unet_strategy.py`, que sigue como esqueleto.
- [X] T012 [P] En `src/radvol3d/services/meshing/meshing_strategy.py`:
  - definir `@dataclass(frozen=True) class MeshSet` con `organ: bytes` y `tumor: bytes`;
  - reemplazar `build_mesh(mask)` por `build_meshes(self, volume, mask) -> MeshSet`, abstracto, con un docstring que diga que, si no hay superficie, devuelve un `.glb` válido sin geometría y no lanza.

  Ajustar la firma del esqueleto en `src/radvol3d/services/meshing/marching_cubes_strategy.py`, que sigue lanzando `NotImplementedError` hasta T082.

### Carpeta `services/pipeline/` (research.md R1)

- [X] T013 Mover `src/radvol3d/services/processing_pipeline.py` a `src/radvol3d/services/pipeline/processing_pipeline.py` y `src/radvol3d/services/preprocessing/projection_loader.py` a `src/radvol3d/services/pipeline/projection_loader.py`, con `git mv`.
  - Crear `src/radvol3d/services/pipeline/__init__.py`, con un docstring en español.
  - Borrar `src/radvol3d/services/preprocessing/`.
  - Actualizar los imports en `src/radvol3d/api/dependencies.py`, `src/radvol3d/api/routers/reconstruction_router.py` y `src/radvol3d/api/routers/segmentation_router.py`.
  - Correr `pytest -m architecture`: debe seguir en verde sin tocar `tests/architecture/`.
- [X] T014 [P] Crear `src/radvol3d/services/pipeline/pipeline_data.py` con `@dataclass(frozen=True) class PipelineData` y estos campos:
  - `study_code: str`
  - `projections_by_angle: Mapping[int, ndarray]`
  - `projections: ndarray | None = None`
  - `volume: ndarray | None = None`
  - `segmentation: SegmentationResult | None = None`
  - `meshes: MeshSet | None = None`

  Cada filtro devuelve una copia con `dataclasses.replace`.
- [X] T015 [P] Crear `src/radvol3d/services/pipeline/progress.py` con `class PipelineProgress(Protocol)` y los cinco métodos de [contracts/services_api.md](contracts/services_api.md#tubería): `stage_started`, `stage_completed`, `stage_failed`, `save_volume` y `save_result`.
- [X] T016 [P] En `src/radvol3d/config.py`, cambiar `ACCEPTED_FORMATS` a `(".npy",)` y su comentario: "solo .npy en el convenio de TA-2; PNG no tiene la escala que espera EN-1".

### Dobles

- [X] T017 [P] Actualizar `tests/fixtures/fake_strategies.py` a las firmas nuevas:
  - **`FakeSegmentationStrategy.segment(volume, study_code)`** devuelve, además de lo que ya devuelve, un `summary` con la forma de data-model.md §4:
    - `study_code`
    - `organ: "lung"`
    - `model_name: "fake_segmentation"`
    - `model_version: "0.0.0"`
    - `regions`, con una región cuyos datos coinciden con la lesión del doble
  - **`FakeMeshingStrategy.build_meshes(volume, mask)`** devuelve `MeshSet(organ=b"glTF"+..., tumor=b"glTF"+...)`.
  - **`FakeReconstructionStrategy`** devuelve un volumen que depende de las proyecciones, por ejemplo `np.full(..., float(projections.mean()) % 1.0)`. Así la prueba de concurrencia distingue dos estudios.
- [X] T018 [P] Crear `tests/fixtures/fake_progress.py` con `RecordingProgress`:
  - implementa `PipelineProgress` y guarda cada llamada como tupla en `events`, por ejemplo `("started", "it_a", 2)` o `("completed", "it_a", 2, "fake_reconstruction", "0.0.0")`;
  - es seguro entre hilos: usa un `threading.Lock` para agregar eventos;
  - acepta `fail_on` para lanzar una excepción en un evento dado.
- [X] T019 [P] Crear `tests/fixtures/projection_files.py`, con funciones que arman en memoria:
  - `valid_npy(angle, seed)`: `.npy` `(128, 128)` float32, finito, sin pickle;
  - `png_bytes()`: firma PNG;
  - `pickled_npy()`: arreglo de objetos guardado con `allow_pickle=True`;
  - `npy_with_nan()`
  - `npy_wrong_shape()`
  - `npy_text_dtype()`
  - `four_valid_files(seed)`: lista de `ProjectionFile` para 0, 45, 90 y 135.
- [X] T020 Actualizar `tests/unit/services/test_fake_strategies.py`. Depende de T017. Debe comprobar:
  - el resumen del doble trae `model_name`, `model_version` y `regions`, como exige `ResultStore`;
  - `build_meshes` devuelve dos bytes que empiezan por `glTF`.

**Checkpoint**: `pytest -m "unit or architecture"`, `ruff check src tests` y `python scripts/check_naming_convention.py` en verde.

---

## Phase 3: User Story 1 - Procesar un estudio de punta a punta con estrategias falsas (Priority: P1) 🎯 MVP

**Goal**: con los dobles, un estudio se registra, pasa por las cuatro etapas, cada etapa queda
registrada con estado, horas y modelo, y se guardan el volumen, el resultado y las mallas.

**Independent Test**: `pytest tests/integration/services/test_pipeline_integration.py` contra el
Supabase de prueba. El estudio queda en `completed`, con las cuatro etapas en `completed` y sus
horas, modelo en las etapas 2 y 3, `grid_size` 128, tiempo total y las cinco rutas del resultado.

### Tests for User Story 1 ⚠️

- [ ] T021 [P] [US1] Escribir `tests/unit/persistence/test_processing_progress_store.py` con `FakeDatabase` (research.md R9):
  - `start_processing` hace `update study set status = 'processing'`;
  - `start_stage(code, 2)` deja la etapa en `running`;
  - `complete_stage(code, 2, "m", "1.0.0")` hace `get_or_create` del modelo antes de `set_status` con ese modelo, en la misma transacción;
  - `complete_stage` sin modelo no toca `model`;
  - `complete_study` llama a `mark_completed` con el modelo, `grid_size` y `total_time_sec`;
  - `register_model("m", "1.0.0")` devuelve un `Model` con `trained_on is None`;
  - un estudio inexistente lanza `StudyNotFoundError`;
  - cada método abre una sola transacción.
- [ ] T022 [P] [US1] Actualizar `tests/unit/persistence/test_result_store.py` según research.md R7. `save_result`:
  - sube los cinco archivos e inserta las lesiones en una unidad de trabajo;
  - **no** ejecuta ningún `update processing_stage` ni registra modelo;
  - sigue rechazando un resumen sin `model_name` o `model_version`.

  `get_result` sigue devolviendo un resultado vacío si las etapas 3 y 4 no están en `completed`.
- [ ] T023 [P] [US1] Escribir `tests/unit/services/test_projection_loader.py` (camino correcto). `ProjectionLoader.parse(four_valid_files())`:
  - devuelve un `dict` `{0, 45, 90, 135}` de arreglos `(128, 128)` float32, iguales en valor a los originales, sin reescalar;
  - acepta las proyecciones en cualquier orden de llegada.
- [ ] T024 [P] [US1] Escribir `tests/unit/services/test_pipeline_filters.py` con los dobles:
  - `PreprocessingFilter` apila en orden de ángulo, `(4, 128, 128)` float32;
  - `ReconstructionFilter` pone `volume` y expone el `model_name` y `model_version` de su estrategia;
  - `SegmentationFilter` llama a `segment(volume, study_code)` y pone `segmentation`;
  - `MeshingFilter` llama a `build_meshes(volume, segmentation.mask)` y pone `meshes`;
  - ningún filtro modifica el `PipelineData` recibido;
  - `stage_number` es 1, 2, 3 y 4.
- [ ] T025 [P] [US1] Escribir `tests/unit/services/test_processing_pipeline.py` (camino correcto) con `RecordingProgress`. La secuencia exacta de eventos es:
  1. `started 1`, `completed 1` (sin modelo)
  2. `started 2`, `save_volume`, `completed 2` (con el modelo de reconstrucción)
  3. `started 3`, `completed 3` (con el modelo de segmentación)
  4. `started 4`, `save_result`, `completed 4` (sin modelo)

  `run` devuelve un `PipelineData` con los cuatro campos llenos. La tubería no contiene `organ` en ninguna condición: grep sobre el módulo.
- [ ] T026 [P] [US1] Escribir `tests/unit/services/test_strategy_factory.py` (camino correcto), con constructores que cuentan sus llamadas y devuelven los dobles:
  - `preload()` llama a cada constructor exactamente una vez;
  - `strategies_for(OrganName.LUNG)` devuelve un `StrategySet` con las mismas instancias en cada llamada;
  - `availability()` devuelve `{"reconstruction:en1": True, "segmentation:lung": True, "meshing": True}`.
- [ ] T027 [P] [US1] Escribir `tests/unit/services/test_persistence_progress.py`. `PersistenceProgress` delega con los argumentos correctos:
  - `stage_started` → `ProcessingProgressStore.start_stage`
  - `stage_completed` → `complete_stage`
  - `save_volume` → `StudyMetadataStore.save_volume`
  - `save_result` → `ResultStore.save_result(code, mask, probability, summary, meshes.organ, meshes.tumor)`

  Los almacenes son falsos (`unittest.mock.create_autospec`).
- [ ] T028 [P] [US1] Escribir `tests/unit/services/test_study_service.py` (camino correcto), con almacenes falsos y la fábrica con dobles. `process_study(StudyRequest(...))` llama en este orden:
  1. `parse`
  2. `strategies_for`
  3. `register_study`, con `ProjectionUpload` por ángulo y el paciente
  4. `start_processing`
  5. la tubería
  6. `complete_study`, con el modelo de segmentación, `grid_size == config.GRID_SIZE` y un `total_time_sec > 0` medido con `time.perf_counter`
  7. `get_study`

  Devuelve ese `Study`. `get_study` y `get_result` delegan en los almacenes.
- [ ] T029 [US1] Mover las fixtures compartidas de `tests/integration/persistence/conftest.py` a `tests/integration/conftest.py`: `test_settings`, `database`, `object_storage`, la fábrica de códigos `it_` y la limpieza. Dejar en el archivo original solo lo propio de la persistencia, si queda algo. Las pruebas de `tests/integration/persistence/` deben seguir pasando igual.
- [ ] T030 [US1] Escribir `tests/integration/services/test_pipeline_integration.py` (marca `integration`). Arma `StudyService` con los almacenes reales sobre `.env.test`, `PersistenceProgress` y la fábrica con dobles. Procesa un estudio `it_` de pulmón con paciente y comprueba la prueba independiente de la historia 1 y sus escenarios 1 y 3:
  - estudio `completed`, `grid_size` 128 y `total_time_sec` presente;
  - cuatro etapas en `completed`, cada una con `started_at <= finished_at`;
  - `fake_reconstruction` en la etapa 2 y `fake_segmentation` en la 3 y en el estudio;
  - `get_result` con las cinco rutas y una lesión;
  - las diez rutas existen en el bucket.

  Agregar un segundo caso para el escenario 2: un `RecordingProgress` envuelve al real y, mientras corre la etapa 3, lee las etapas de la base y encuentra 1 y 2 en `completed`, 3 en `running` y 4 en `waiting`.
- [ ] T031 [US1] Actualizar `tests/integration/persistence/test_result_storage_integration.py` a R7. Después de `save_result`, `get_result` sigue vacío hasta que la prueba marca las etapas 3 y 4 con `ProcessingProgressStore.complete_stage`. Después vuelve con las cinco rutas.

### Implementation for User Story 1

- [ ] T032 [US1] Crear `src/radvol3d/persistence/processing_progress_store.py` con `ProcessingProgressStore(database)` y los métodos `start_processing`, `start_stage`, `complete_stage`, `complete_study` y `register_model` de [contracts/persistence_api_changes.md](contracts/persistence_api_changes.md#processing_progress_store-nuevo). `fail_from_stage` se hace en US2. Cada método es una unidad de trabajo con `database.transaction()` sobre `StudyRepository`, `ProcessingStageRepository` y `ModelRepository`. Hace pasar T021.
- [ ] T033 [US1] Modificar `src/radvol3d/persistence/result_store.py` según R7: quitar de `save_result` el `ModelRepository.get_or_create` y los dos `set_status`, y dejar la subida y `LesionRepository.add_many` en una unidad de trabajo. Actualizar el docstring del módulo con el orden nuevo y quitar la frase "la capa no tiene borrado todavía". `_model_of` sigue validando el resumen. Hace pasar T022 y T031.
- [ ] T034 [US1] Implementar en `src/radvol3d/services/pipeline/projection_loader.py`:
  - `@dataclass(frozen=True) class ProjectionFile(angle_degrees: int, content: bytes, original_name: str | None = None)`;
  - `ProjectionLoader.parse(files) -> dict[int, ndarray]`: lee con `np.load(io.BytesIO(content), allow_pickle=False)` y convierte a `float32` sin reescalar;
  - `ProjectionLoader.stack(by_angle) -> ndarray (4,128,128)`, en el orden de `config.PROJECTION_ANGLES`.

  Las validaciones de error se hacen en US2 (T046). Hace pasar T023.
- [ ] T035 [US1] Crear `src/radvol3d/services/pipeline/filters.py` con `PreprocessingFilter(loader)`, `ReconstructionFilter(strategy)`, `SegmentationFilter(strategy)` y `MeshingFilter(strategy)`. Cada uno tiene:
  - `stage_number: StageNumber`;
  - `model: tuple[str, str] | None`: el nombre y la versión de la estrategia en las etapas 2 y 3, `None` en la 1 y la 4;
  - `apply(data: PipelineData) -> PipelineData`.

  Hace pasar T024.
- [ ] T036 [US1] Implementar `ProcessingPipeline.run(study_code, projections_by_angle, strategies, progress)` en `src/radvol3d/services/pipeline/processing_pipeline.py`:
  - arma los cuatro filtros con `strategies` en cada corrida, sin estado en la instancia;
  - recorre los filtros con la secuencia de T025;
  - guarda el volumen después de la etapa 2 y el resultado después de la 4.

  Sin condicionales por órgano. El manejo de fallos se hace en US2 (T048). Hace pasar T025.
- [ ] T037 [US1] Reescribir `src/radvol3d/services/strategy_factory.py` según [contracts/services_api.md](contracts/services_api.md#fábrica):
  - `@dataclass(frozen=True) class StrategySet(reconstruction, segmentation, meshing)`;
  - `StrategyFactory(reconstruction_builders, segmentation_builders, meshing_builder, reconstruction_key)`, con `preload()`, `strategies_for(organ)` y `availability()`;
  - las instancias se construyen solo en `preload()` y se guardan.

  Quitar `SEGMENTATION_BY_ORGAN` con `LiverUnetStrategy` y `build_segmentation_strategy`. Los caminos de error se hacen en US2 (T049). Hace pasar T026.
- [ ] T038 [US1] Crear `src/radvol3d/services/pipeline/persistence_progress.py` con `PersistenceProgress(progress_store, metadata_store, result_store)`, que implementa `PipelineProgress` delegando como en T027. Hace pasar T027.
- [ ] T039 [US1] Implementar en `src/radvol3d/services/study_service.py`:
  - `@dataclass(frozen=True) class StudyRequest(study_code, organ, projections, patient=None)`;
  - `StudyService(metadata_store, result_store, progress_store, factory, pipeline, loader)`, con `process_study`, `get_study` y `get_result`.

  `process_study` sigue el orden de T028. Convierte cada arreglo a `ProjectionUpload(angle, array, original_name)` y construye `PersistenceProgress` con sus almacenes. Hace pasar T028 y T030.

**Checkpoint**: la historia 1 es funcional e independiente. `pytest -m unit` y `pytest -m integration tests/integration` en verde, con `.env.test`.

---

## Phase 4: User Story 2 - Fallar con errores claros y sin datos del paciente (Priority: P1)

**Goal**: cada entrada inválida, modelo no disponible o fallo de etapa lanza el error del
dominio que corresponde, deja el estudio en un estado consistente y no expone datos personales.

**Independent Test**: `pytest -m unit tests/unit/services` con los casos de error, y
`pytest tests/integration/services/test_pipeline_failures_integration.py`. El fallo en la
etapa 3 deja 3 en `failed`, 4 en `skipped` y el estudio en `failed`. `liver` y las
entradas inválidas no crean el estudio. Ningún mensaje contiene "Ana", "Pérez" ni "12345678".

### Tests for User Story 2 ⚠️

- [ ] T040 [P] [US2] Agregar a `tests/fixtures/fake_strategies.py` las clases `FailingReconstructionStrategy`, `FailingSegmentationStrategy` y `FailingMeshingStrategy`. Cada una lanza `RuntimeError("detalle interno")` al usarse y expone `model_name` y `model_version` como los dobles normales.
- [ ] T041 [P] [US2] Ampliar `tests/unit/services/test_projection_loader.py` con los errores de FR-010, FR-011 y los casos borde. Cada uno lanza `InvalidProjectionError`:
  - tres archivos;
  - cinco archivos;
  - ángulo repetido: el mensaje nombra el ángulo;
  - ángulo faltante: el mensaje nombra el ángulo que falta;
  - ángulo 30;
  - PNG: el mensaje nombra el ángulo y dice "solo se acepta .npy en el convenio de TA-2";
  - `.npy` con objetos de Python: se rechaza sin cargarlo;
  - dtype de texto;
  - forma `(64, 64)`: el mensaje nombra el ángulo y la forma esperada `(128, 128)`;
  - NaN o infinito.

  Ningún mensaje contiene bytes del archivo.
- [ ] T042 [P] [US2] Ampliar `tests/unit/services/test_processing_pipeline.py`:
  - **Fallo en la etapa n.** Para cada `n` de 1 a 4, con un filtro o estrategia que falla en esa etapa, el último evento de progreso es `("failed", code, n)` y no hay `completed n`. Se lanza `StageFailedError` con `stage_number == n` y `__cause__` es la excepción original. El mensaje no contiene "detalle interno".
  - **Fallo al guardar.** Si `save_volume` o `save_result` fallan (`RecordingProgress.fail_on`), falla la etapa 2 o la 4.
- [ ] T043 [P] [US2] Ampliar `tests/unit/services/test_strategy_factory.py`. En cada caso se lanza `ModelNotAvailableError` con el mensaje de [contracts/services_api.md](contracts/services_api.md#fábrica):
  - `strategies_for(OrganName.LIVER)` dice "No hay modelo de segmentación de hígado todavía.";
  - una `reconstruction_key` desconocida dice "No hay estrategia de reconstrucción '<clave>'.";
  - un constructor que lanza `ImportError`, `FileNotFoundError` o `StorageError` en `preload()`: `preload` no lanza, `availability()` marca `False` y `strategies_for` dice "El modelo <nombre> no está disponible en este servidor.";
  - el registro de log del fallo no contiene la ruta firmada ni la clave.
- [ ] T044 [P] [US2] Ampliar `tests/unit/persistence/test_processing_progress_store.py`:
  - `fail_from_stage(code, 3)` deja en una sola transacción la etapa 3 en `failed`, la 4 en `skipped` y el estudio en `failed`;
  - `fail_from_stage(code, 1)` deja la 1 en `failed` y la 2, 3 y 4 en `skipped`;
  - un estudio inexistente lanza `StudyNotFoundError`.
- [ ] T045 [P] [US2] Ampliar `tests/unit/services/test_study_service.py`:
  - una entrada inválida o un órgano `liver` lanzan el error **sin** llamar a `register_study` (historia 2, escenarios 1 a 3);
  - si falla una etapa, `StageFailedError` se propaga y no se llama a `complete_study`;
  - `DuplicateStudyError` del almacén se propaga sin tocar la tubería.
  - **Privacidad (SC-007).** Con `PatientDetails(first_name="Ana", last_name="Pérez", national_id="12345678")`, provocar cada uno de los errores anteriores y comprobar que ni `str(error)`, ni `repr(error)`, ni los registros capturados con `caplog` contienen esos tres valores.
- [ ] T046 [US2] Escribir `tests/integration/services/test_pipeline_failures_integration.py` (marca `integration`):
  - con `FailingSegmentationStrategy`, la etapa 3 queda en `failed`, la 4 en `skipped`, el estudio en `failed` y se lanza `StageFailedError` (historia 2, escenario 4);
  - con `organ=OrganName.LIVER`, se lanza `ModelNotAvailableError` y `get_study` del código lanza `StudyNotFoundError`;
  - con un PNG en el ángulo 90, se lanza `InvalidProjectionError` y no se crea el estudio.

### Implementation for User Story 2

- [ ] T047 [US2] Agregar a `ProjectionLoader.parse` en `src/radvol3d/services/pipeline/projection_loader.py` las validaciones de T041, en este orden:
  1. cantidad y ángulos, con `config.PROJECTION_ANGLES`;
  2. firma mágica `\x93NUMPY`;
  3. `np.load(..., allow_pickle=False)`: un `ValueError` se convierte en `InvalidProjectionError` con `from None`;
  4. dtype numérico (`np.issubdtype(dtype, np.number)`);
  5. forma `(config.GRID_SIZE, config.GRID_SIZE)`;
  6. `np.isfinite(...).all()`.

  Los mensajes, en español, nombran solo el ángulo. Hace pasar T041.
- [ ] T048 [US2] Agregar el manejo de fallos a `ProcessingPipeline.run` en `src/radvol3d/services/pipeline/processing_pipeline.py`. Cualquier excepción en el filtro o en su guardado:
  1. llama a `progress.stage_failed(code, n)`;
  2. registra en el log `logger.error("Falló la etapa %d del estudio %s (%s)", n, code, type(error).__name__)`, sin el texto de la causa;
  3. lanza `StageFailedError(code, n) from error`.

  Si `stage_failed` también falla, se registra y se lanza igual el `StageFailedError`. Hace pasar T042.
- [ ] T049 [US2] Agregar a `StrategyFactory` en `src/radvol3d/services/strategy_factory.py` los caminos de error de T043. `preload()` captura `Exception` por constructor, guarda un motivo genérico y registra el tipo de la excepción. Los mensajes van como en el contrato. Hace pasar T043.
- [ ] T050 [US2] Agregar `fail_from_stage` a `src/radvol3d/persistence/processing_progress_store.py`: en una transacción, `set_status(n, FAILED)`, `set_status(m, SKIPPED)` para cada `m > n` y `update_status(FAILED)`. Hacer que `PersistenceProgress.stage_failed` en `src/radvol3d/services/pipeline/persistence_progress.py` delegue en él. Hace pasar T044.
- [ ] T051 [US2] Ajustar `StudyService.process_study` en `src/radvol3d/services/study_service.py` para que `parse` y `strategies_for` corran antes de `register_study`, y para que `StageFailedError` se propague sin envolverlo. Hace pasar T045 y T046.
- [ ] T052 [P] [US2] Agregar a `STATUS_BY_ERROR` en `src/radvol3d/api/error_handlers.py` los errores `StageFailedError: 500` y `StudyInProgressError: 409`. Agregar a `tests/unit/api/test_error_handlers.py` una prueba que registra los manejadores en una app mínima y comprueba los dos códigos.

**Checkpoint**: las historias 1 y 2 funcionan juntas y por separado.

---

## Phase 5: User Story 3 - Consultar y borrar estudios (Priority: P2)

**Goal**: listar estudios y borrar un estudio con sus filas y sus diez archivos, con rechazo
mientras está en `processing`.

**Independent Test**: `pytest tests/integration/services/test_delete_study_integration.py`.
Después de procesar y borrar, `get_study` lanza `StudyNotFoundError`, no queda ninguna de las
diez rutas, el paciente sigue y un estudio en `processing` no se puede borrar.

### Tests for User Story 3 ⚠️

- [ ] T053 [P] [US3] Agregar a `tests/fixtures/fake_object_storage.py` el método `InMemoryBucket.remove(paths: list[str])`, que imita storage3: borra las rutas que existen, ignora las que no y anota `("remove", paths)` en `events`. También debe aceptar `fail_next("remove", error)`.
- [ ] T054 [P] [US3] Ampliar `tests/unit/persistence/test_object_storage.py` con `remove_many`:
  - con varias rutas, hace una sola llamada a `remove`;
  - una ruta inexistente no es error;
  - una lista vacía no llama al bucket;
  - un fallo de storage3 se convierte en `StorageError`, sin el texto original.
- [ ] T055 [P] [US3] Ampliar `tests/unit/persistence/repositories/test_study_repository.py`:
  - `lock_status(code)` ejecuta un `select ... for update` y devuelve `StudyStatus`;
  - `delete(code)` ejecuta `delete from study where study_code = %s`;
  - con un código inexistente, ambos lanzan `StudyNotFoundError`.
- [ ] T056 [P] [US3] Ampliar `tests/unit/persistence/test_study_metadata_store.py` con `delete_study`, usando `FakeDatabase` e `InMemoryBucket` con la lista `events` compartida:
  - el orden es `lock_status` → `delete from study` → `remove` (con exactamente las diez rutas de data-model.md §7) → commit;
  - con `processing` lanza `StudyInProgressError`, no borra nada y no llama al bucket;
  - si el bucket falla, la transacción se revierte (rollback) y se lanza `StorageError`;
  - un código inválido lanza `InvalidStudyIdError` antes de abrir la transacción;
  - `pending`, `completed` y `failed` se borran.
- [ ] T057 [P] [US3] Ampliar `tests/unit/services/test_study_service.py`: `list_studies` y `delete_study` delegan en `StudyMetadataStore`, y `StudyNotFoundError` y `StudyInProgressError` se propagan.
- [ ] T058 [US3] Escribir `tests/integration/services/test_delete_study_integration.py` (marca `integration`), con los escenarios 1 a 3 de la historia 3. Para el escenario 3, `start_processing` deja el estudio en `processing` antes de intentar borrarlo. Comprobar también el borde de `failed`: después de un fallo en la etapa 3, el borrado limpia los archivos que hayan quedado.

### Implementation for User Story 3

- [ ] T059 [P] [US3] Agregar `ObjectStorage.remove_many(paths: Sequence[str]) -> None` en `src/radvol3d/persistence/object_storage.py`, que llama a `self._bucket.remove(list(paths))`. Hace pasar T054.
- [ ] T060 [P] [US3] Agregar `StudyRepository.lock_status` y `StudyRepository.delete` en `src/radvol3d/persistence/repositories/study_repository.py`, con `execute_translated` como el resto del repositorio. Hace pasar T055.
- [ ] T061 [US3] Agregar `StudyMetadataStore.delete_study(study_code)` en `src/radvol3d/persistence/study_metadata_store.py`, según research.md R8 y [contracts/persistence_api_changes.md](contracts/persistence_api_changes.md#study_metadata_store-agrega). Las diez rutas salen de `storage_layout`: `projection_path` para cada ángulo de `config.PROJECTION_ANGLES` y las seis funciones restantes. Hace pasar T056.
- [ ] T062 [US3] Agregar `list_studies` y `delete_study` a `StudyService` en `src/radvol3d/services/study_service.py`. Hace pasar T057 y T058.
- [ ] T063 [US3] Quitar de `tests/integration/conftest.py` el comentario "la capa de persistencia no tiene borrado". Usar `StudyMetadataStore.delete_study` en la limpieza de los estudios `it_` y conservar el SQL directo solo para los pacientes creados por la prueba.

**Checkpoint**: las historias 1, 2 y 3 funcionan juntas y por separado.

---

## Phase 6: User Story 4 - Arrancar el servicio con todo conectado una sola vez (Priority: P2)

**Goal**: el `lifespan` arma una vez la base, los almacenes, los pesos, las estrategias y
`StudyService`, registra los modelos y lo entrega a `api/` por `Depends()`. Si falta un modelo,
la aplicación arranca igual.

**Independent Test**: `pytest tests/unit/services/test_service_container.py tests/unit/test_main_lifespan.py`.
Con constructores falsos, cada estrategia se construye una sola vez, `api/` recibe el servicio
desde `app.state` y `pytest -m architecture` sigue en verde.

### Tests for User Story 4 ⚠️

- [ ] T064 [P] [US4] Ampliar `tests/unit/persistence/test_settings.py` con `ModelSettings` y `get_model_settings()`:
  - sin ninguna variable, no lanza;
  - `model_cache_dir == Path(".cache/models")` y `reconstruction_strategy == "en1"`;
  - con las cinco variables, las expone;
  - `get_settings()` sigue exigiendo solo sus cuatro variables.
- [ ] T065 [P] [US4] Ampliar `tests/unit/persistence/test_object_storage.py`: `ObjectStorage.from_settings(settings, bucket="modelos-x")` usa ese bucket, y sin `bucket` usa `settings.storage_bucket`. Usar el cliente falso que ya usa la prueba de `from_settings`.
- [ ] T066 [P] [US4] Escribir `tests/unit/persistence/test_model_weights_store.py` con `InMemoryBucket` y `tmp_path`:
  - **Primera llamada.** `fetch("reconstruction_en1/1.0.0/weights.pth")` baja el archivo y lo guarda bajo `cache_dir`, con los mismos bytes.
  - **Segunda llamada.** No vuelve a bajar: no hay un segundo evento `download`.
  - **Objeto inexistente.** Lanza `StorageObjectNotFoundError` y no deja ningún archivo, tampoco el temporal.
  - **Ruta peligrosa.** Una ruta con `..` se rechaza con `StorageError`.
- [ ] T067 [P] [US4] Escribir `tests/unit/services/test_service_container.py`. `build_service_container` recibe fábricas inyectables de base, almacenamiento y constructores de estrategias, todas falsas. Comprobar:
  - abre la base una vez;
  - cada constructor de estrategia se llama una vez, aunque se procesen tres estudios;
  - registra con `register_model` cada modelo cargado, con `trained_on=None` (historia 4, escenario 3);
  - con el constructor de segmentación fallando, el contenedor se construye igual, `model_status()` marca `segmentation:lung` en `False` y `process_study` de pulmón lanza `ModelNotAvailableError` (FR-019);
  - `close()` cierra la base y es idempotente.
- [ ] T068 [P] [US4] Escribir `tests/unit/test_main_lifespan.py`. Con `create_app(container_builder=fake_builder)`, al entrar en `TestClient`:
  - el `lifespan` llama al constructor una vez;
  - guarda el contenedor en `app.state.services`;
  - al salir llama a `close()`.

  `api.dependencies.get_study_service(request)` devuelve `app.state.services.study_service`.
- [ ] T069 [P] [US4] Actualizar `tests/conftest.py` para que la fixture `app` use `create_app(container_builder=...)` con un contenedor falso que no abre la base. Así `tests/unit/api/test_health_router.py` sigue pasando sin `.env`.
- [ ] T070 [US4] Escribir `tests/concurrency/test_concurrent_studies.py` (marca `concurrency`, con `.env.test`). Dos estudios `it_` con proyecciones de semillas distintas se procesan a la vez con `ThreadPoolExecutor(max_workers=2)`, usando `StudyService` con los dobles y la persistencia de prueba. Se repite 20 veces (SC-005). En cada repetición:
  - los volúmenes guardados (`download_array(volume_path)`) y los resúmenes coinciden con los de los mismos estudios procesados por separado;
  - ningún dato de un estudio aparece en el otro.

  Comprobar también que cada constructor de estrategia se llamó una sola vez (SC-006). Actualizar `tests/concurrency/README.md`: estas pruebas necesitan `.env.test`, no el servicio levantado.

### Implementation for User Story 4

- [ ] T071 [P] [US4] Agregar a `src/radvol3d/persistence/settings.py` la clase `ModelSettings(BaseSettings)`, con los cinco campos opcionales de data-model.md §6 y el mismo `env_file`, y `get_model_settings()` con `functools.cache`. No cambia `Settings`. Hace pasar T064.
- [ ] T072 [P] [US4] Agregar el parámetro opcional `bucket: str | None = None` a `ObjectStorage.from_settings` en `src/radvol3d/persistence/object_storage.py`. Hace pasar T065.
- [ ] T073 [P] [US4] Crear `src/radvol3d/persistence/model_weights_store.py` con `ModelWeightsStore(storage, cache_dir).fetch(object_path) -> Path`:
  - valida la ruta: sin `..`, sin barra invertida, no vacía;
  - si el archivo ya está en `cache_dir / object_path`, lo devuelve;
  - si no, lo baja con `download_bytes`, lo escribe en un temporal en la misma carpeta y hace `os.replace`.

  Hace pasar T066.
- [ ] T074 [US4] Crear `src/radvol3d/services/service_container.py` con `ServiceContainer` (`study_service`, `model_status()`, `close()`) y `build_service_container(settings, model_settings, *, database_factory=Database.from_settings, storage_factory=ObjectStorage.from_settings, strategy_builders=None)`. El orden de armado es:
  1. abre la base;
  2. crea el almacenamiento de datos y, si `model_bucket` existe, el de modelos con `ModelWeightsStore`;
  3. arma `StrategyFactory` con los constructores por omisión de `default_strategy_builders(weights_store, model_settings)`:
     - `"en1"` → `NeuralEn1Strategy.from_weights(weights_store.fetch(en1_weights_object))`
     - `OrganName.LUNG` → `LungUnetStrategy.from_weights(weights_store.fetch(en2_weights_object))`
     - mallas → `MarchingCubesStrategy()`

     Un objeto sin configurar lanza `ModelNotAvailableError` dentro del constructor. Esas clases todavía son esqueletos hasta US5, así que sus modelos quedan no disponibles.
  4. llama a `preload()`;
  5. registra los modelos disponibles con `register_model(name, version, trained_on=None, description=...)`;
  6. arma `StudyService`.

  Hace pasar T067.
- [ ] T075 [US4] Modificar `src/radvol3d/main.py`. `create_app(container_builder=None)` usa por omisión `lambda: build_service_container(get_settings(), get_model_settings())`. El `lifespan`:
  - guarda el contenedor en `app.state.services`;
  - registra en el log `model_status()`;
  - lo cierra al terminar.

  `app = create_app()` sigue al final del módulo. Hace pasar T068.
- [ ] T076 [US4] Reescribir `src/radvol3d/api/dependencies.py`: `get_study_service(request: Request) -> StudyService` lee `request.app.state.services.study_service`. Eliminar `get_processing_pipeline` y cambiar `src/radvol3d/api/routers/reconstruction_router.py` y `src/radvol3d/api/routers/segmentation_router.py` para que reciban `StudyService` con `Depends(get_study_service)`. Sus cuerpos siguen con `NotImplementedError`, porque los endpoints están fuera de alcance. `api/` no gana ningún import de `persistence`, `supabase` ni `torch`. Hace pasar T068 y T069.
- [ ] T077 [US4] Hacer pasar T070. Si la prueba detecta mezcla de datos, corregir el estado compartido en la tubería, el servicio o los dobles. No agregar candados a la tubería.

**Checkpoint**: las historias 1 a 4 funcionan con los dobles. La aplicación arranca sin modelos y lo informa.

---

## Phase 7: Cierre del bloque con dobles (Cross-Cutting)

**Purpose**: dejar el CI y las reglas en verde antes de conectar los modelos reales (orden de
construcción de la especificación).

- [ ] T078 Agregar a `.github/workflows/ci.yml`, después de `pytest -m unit --cov --cov-report=xml`, el paso "Cobertura de services":
  ```
  coverage report --include="src/radvol3d/services/*" --omit="*/en1_network.py,*/en1_reconstructor.py,*/lung_unet_network.py,*/lung_segmenter.py" --fail-under=80
  ```
  Agregar un comentario en español con el motivo (research.md R17). El CI sigue sin instalar el extra `ml`.
- [ ] T079 [P] Agregar a `docs/standards/testing_strategy.md`:
  - la fila `ml/ | ¿los modelos reales dan la misma salida que los originales? | ml | torch y pesos`;
  - el cambio en la fila `concurrency/`: necesita "Supabase de prueba";
  - el comando `pytest -m "not ml"`.
- [ ] T080 Correr las tres comprobaciones y la cobertura de quickstart.md, bloques A y B: `ruff check src tests`, `python scripts/check_naming_convention.py` y `pytest -m "unit or architecture"`. Con `.env.test`, correr además el bloque C. Todo en verde y `services/` con 80 % o más.

**Checkpoint**: criterio de aceptación 1 cumplido. La tubería corre con dobles de punta a punta y guarda en la persistencia.

---

## Phase 8: User Story 5 - Reconstruir y segmentar con los modelos reales (Priority: P3)

**Goal**: mallas con marching cubes, y EN-1 y EN-2 migrados a `services/` sin cambiar su salida
numérica, cargados una vez desde el bucket de modelos.

**Independent Test**: `pytest -m ml -v` con torch y los artefactos publicados. La regresión de
EN-1 y EN-2 está dentro de la tolerancia, y el estudio de ejemplo produce volumen, máscara,
probabilidad, resumen, `organ.glb` y `tumor.glb`. Las mallas y el caso 4 del resumen se
prueban también sin torch, con `pytest -m unit`.

### Mallas (sin torch)

- [ ] T081 [P] [US5] Escribir `tests/unit/services/test_marching_cubes_strategy.py`. Las mallas se vuelven a abrir con `trimesh.load(..., file_type="glb")`.
  - **Esfera.** Con una máscara esférica de radio 10 vóxeles en el centro, `tumor` empieza con `b"glTF"`, tiene vértices, y su caja envolvente mide ≈ 2·10·2,5 mm por eje (tolerancia de un vóxel), centrada en el origen.
  - **Máscara vacía.** `tumor` es un `.glb` válido sin vértices y no lanza.
  - **Volumen constante.** `organ` es un `.glb` válido sin vértices y no lanza.
  - **Dos regiones.** Con dos esferas separadas de distinto tamaño en el volumen, la malla del órgano cubre solo la mayor: su caja envolvente coincide con la esfera grande.
  - **Coordenadas compartidas.** El tumor y el órgano usan el mismo sistema: un tumor en el centro de un órgano esférico queda dentro de la caja del órgano.
- [ ] T082 [US5] Implementar `MarchingCubesStrategy.build_meshes(volume, mask) -> MeshSet` en `src/radvol3d/services/meshing/marching_cubes_strategy.py`, según research.md R19:
  - **Tumor.** Borde de 1 vóxel con `np.pad`, `marching_cubes(level=0.5, step_size=1, spacing=(config.MM_PER_VOXEL,)*3)`.
  - **Órgano.** `threshold_otsu`, binarizar, quedarse con la componente más grande (`scipy.ndimage.label`), `binary_fill_holes`, y `marching_cubes(level=0.5, step_size=2)`.
  - **Coordenadas.** Restar el borde y el centro del volumen: `(N·2,5)/2` mm.
  - **Exportación.** `trimesh.Trimesh(v, f, process=False).export(file_type="glb")`.
  - **Sin superficie.** `ValueError` o `RuntimeError` de `marching_cubes`, un volumen con `min == max` o una máscara vacía devuelven `trimesh.Trimesh().export(file_type="glb")`.
  - **Atributos.** `model_name = "marching_cubes"`, `model_version = "1.0.0"`, sin registro en `model`, porque la etapa 4 no tiene modelo.

  Hace pasar T081.

### Artefactos de referencia, antes de migrar nada (research.md R16 y R18)

- [ ] T083 [P] [US5] Escribir `tests/unit/scripts/test_export_en2_weights.py`, que carga `scripts/export_en2_weights.py` con `importlib` por ruta, sin torch. `build_export_payload(checkpoint: dict, metrics: dict) -> dict`:
  - devuelve exactamente las ocho claves de [contracts/model_artifacts.md](contracts/model_artifacts.md#pth-de-exportación-de-en-2) con sus fuentes: `pesos` ← `modelo`, `canales` ← `canales`, `parche` y `rejilla` ← `cfg`, `mm_por_voxel` ← 2,5, y `umbral`, `min_voxeles` y `tta` ← métricas;
  - no escribe `solape`, `supervision`, `ventana_hu`, `organo`, `nombre_modelo` ni `version`;
  - si falta una clave de origen, lanza `KeyError` con su nombre.
- [ ] T084 [US5] Crear `scripts/export_en2_weights.py`:
  - argumentos `--checkpoint`, `--metrics` y `--output`;
  - `build_export_payload`, sin torch;
  - `main()`, que importa torch, lee con `torch.load(..., weights_only=True)`, guarda con `torch.save` y comprueba que el resultado se vuelve a abrir con `weights_only=True`.

  El docstring, en español, dice de dónde sale cada valor y que el `.pth` original de exportación, si llega, lo reemplaza sin cambiar código. Hace pasar T083.
- [ ] T085 [US5] Crear `scripts/build_regression_reference.py` (research.md R16), con los argumentos `--models-dir`, `--en2-weights` y `--output-dir`:
  - carga `en1_inferencia_nuevo (1).py` y `en2_inferencia.py` de `--models-dir` con `importlib.util.spec_from_file_location`, sin modificarlos, y fuerza `dispositivo="cpu"`;
  - corre los casos 1, 2 y 3 de [contracts/model_artifacts.md](contracts/model_artifacts.md#bucket-de-modelos-model_bucket) y escribe las salidas en `--output-dir` con los nombres `regression/...`;
  - corre el caso 4 (`resumen_regiones` y `_limpiar` originales sobre una máscara y una probabilidad sintéticas con `np.random.default_rng(20261009)`, con tres regiones y una menor que `min_voxeles=10`), y escribe la entrada y la salida en `tests/unit/services/reference/lung_region_summary_reference.json`;
  - escribe `tests/ml/reference/manifest.json` con la forma del contrato: SHA-256, forma, dtype, receta de la entrada y entorno.
- [ ] T086 [US5] Ejecutar T084 y T085 en la máquina que tiene `models/`, con el extra `ml` instalado, siguiendo quickstart.md D1, antes de crear cualquier módulo de T089 a T098.
  - Versionar solo `tests/ml/reference/manifest.json` y `tests/unit/services/reference/lung_region_summary_reference.json`.
  - Comprobar con `git status` que ningún `.pth` ni `.npy` entra al repositorio.

### Migración de EN-1 (research.md R14 y R15)

- [ ] T087 [P] [US5] Escribir `tests/unit/services/test_en1_geometry.py`, sin torch:
  - `project(ellipsoid_phantom())` da `(4, 128, 128)` float32, y las extensiones de la vista 0 en los ejes 0 y 2 son distintas (la comprobación de la autoprueba original);
  - `back_project` da `(128, 128, 128)`, y con tres proyecciones lanza `ValueError`;
  - `ramp_filter` conserva la forma;
  - `apply_affine` recorta a [0, 1];
  - las constantes valen `G == 128`, `FOV_MM == 320.0`, `ANGLES == (0.0, 45.0, 90.0, 135.0)`, `FILTER_EXPONENT == 0.5`, `FBP_CALIBRATION == (17.7935, -0.0110)` y `BP_CALIBRATION == (1.4131, -0.0591)`.
- [ ] T088 [P] [US5] Escribir `tests/unit/services/test_neural_en1_strategy.py`, sin torch, con un motor falso inyectado (`NeuralEn1Strategy(engine)`):
  - `reconstruct` delega en `engine.reconstruct` y devuelve `(128, 128, 128)` float32;
  - una salida de forma incorrecta lanza `RuntimeError`, que la tubería convierte en un fallo de la etapa 2;
  - `model_name == "reconstruction_en1"` y `model_version == "1.0.0"`;
  - dos hilos que llaman a la vez se serializan: el motor falso registra que nunca hubo dos llamadas a la vez.
- [ ] T089 [US5] Crear `src/radvol3d/services/reconstruction/en1_geometry.py`, solo con numpy y scipy, con lo que no es red de `models/en1_inferencia_nuevo (1).py`, renombrado así:

  | Original | Migrado |
  |---|---|
  | `G` | `G` |
  | `FOV_MM` | `FOV_MM` |
  | `HU_MIN`, `HU_MAX` | sin cambio |
  | `ANGULOS` | `ANGLES` |
  | `EJES_ROTACION` | `ROTATION_AXES` |
  | `EJE_INTEGRACION` | `INTEGRATION_AXIS` |
  | `EJE_DETECTOR` | `DETECTOR_AXIS` |
  | `EXPONENTE_FILTRO` | `FILTER_EXPONENT` |
  | `CALIBRACION_FBP` | `FBP_CALIBRATION` |
  | `CALIBRACION_BP` | `BP_CALIBRATION` |
  | `proyectar` | `project` |
  | `retroproyectar` | `back_project` |
  | `filtro_rampa` | `ramp_filter` |
  | `aplicar_afin` | `apply_affine` |
  | `fantoma_elipsoide` | `ellipsoid_phantom` |

  Las variables locales también van en inglés. Las operaciones, su orden, los valores por omisión y las constantes son idénticos. Los comentarios conservan las explicaciones del original (por qué el relleno de la FFT, por qué el exponente parcial). Hace pasar T087.
- [ ] T090 [US5] Crear `src/radvol3d/services/reconstruction/en1_network.py`, con torch: `conv_block` (era `bloque`) y `ResidualUnet3d` (era `UNet3DResidual`). Los atributos `e1`, `e2`, `e3`, `e4`, `cuello`, `d4`, `d3`, `d2`, `d1`, `salida` y `reducir` **no se renombran**, porque `load_state_dict(strict=True)` compara esos nombres con los del `.pth`. Agregar un comentario que lo explique. Los parámetros del constructor sí pasan a `in_channels` y `base`.
- [ ] T091 [US5] Crear `src/radvol3d/services/reconstruction/en1_reconstructor.py`, con torch, y en él `En1Reconstructor` (era `ReconstructorEN1`):
  - métodos `reconstruct`, `prepare_input`, `baseline` (era `linea_base`) y `describe`;
  - la misma preferencia de claves que el original: `mejores_pesos`, `pesos`, `modelo`, `state_dict` y archivo plano;
  - `torch.load(path, map_location="cpu", weights_only=True)` (R15);
  - `device="cpu"` por omisión.

  No migrar `reconstruir_lote`, `a_hu`, `de_hu`, `espaciado_mm`, `autoprueba` ni `main` (R14).
- [ ] T092 [US5] Implementar `src/radvol3d/services/reconstruction/neural_en1_strategy.py`:
  - `NeuralEn1Strategy(engine)`, con un `threading.Lock` alrededor de `engine.reconstruct`;
  - el classmethod `from_weights(path)`, que importa `En1Reconstructor` dentro del método;
  - una comprobación de la forma de salida.

  El módulo no importa torch en su nivel superior. Hace pasar T088.

### Migración de EN-2 (research.md R14 y R15)

- [ ] T093 [P] [US5] Escribir `tests/unit/services/test_lung_region_summary.py`, sin torch:
  - **Referencia del caso 4.** Con la entrada de `tests/unit/services/reference/lung_region_summary_reference.json`, `summarize_regions` y `clean_mask` devuelven exactamente la salida de referencia: mismas regiones, orden, `region_id`, `volume_mm3`, `max_diameter_mm`, `confidence`, `confidence_min`, `confidence_max`, `voxels` y `centroid_voxel`.
  - **`describe_position`.** Devuelve los textos en español del original, por ejemplo "medio del eje 0 · medio del eje 1 · medio del eje 2".
  - **`patch_positions(128, 96, 0.5) == [0, 32]`**.
  - **`gaussian_weight_map(96)`.** Su máximo es 1.0.
- [ ] T094 [P] [US5] Escribir `tests/unit/services/test_lung_unet_strategy.py`, sin torch, con un motor falso que devuelve el diccionario del original (`mask`, `probability` y un `summary` con `organ: "pulmon"`, `model_name: "segmentacion_pulmon"` y `study_id`):
  - `segment(volume, "it_a")` devuelve un `SegmentationResult` con `summary["study_code"] == "it_a"`, sin la clave `study_id`, con `organ == "lung"`, `model_name == "segmentation_lung"` y `model_version == "1.0.0"`, y con los números iguales (FR-025);
  - una `Lesion` por región, con `location`, `volume_mm3`, `max_diameter_mm` y `confidence`;
  - `global_confidence == summary["global_confidence"]`;
  - `InvalidVolumeError` del motor se propaga, y la tubería lo convierte en un fallo de la etapa 3;
  - el candado serializa dos hilos, como en T088.
- [ ] T095 [US5] Crear `src/radvol3d/services/segmentation/lung_region_summary.py`, solo con numpy y scipy, con lo que no es red de `models/en2_inferencia.py`:

  | Original | Migrado |
  |---|---|
  | `NOMBRES_EJES` | `AXIS_NAMES` (textos en español sin cambios) |
  | `VolumenInvalido` | `InvalidVolumeError(ValueError)` |
  | `_mapa_gaussiano` | `gaussian_weight_map` |
  | `_posiciones` | `patch_positions` |
  | `_limpiar` | `clean_mask` |
  | `describir_posicion` | `describe_position` |
  | `_diametro_maximo_mm` | `max_diameter_mm` |
  | `resumen_regiones` | `summarize_regions` |

  Las claves del resumen (`has_lesion`, `location`, ...) ya están en inglés y no cambian. Hace pasar T093.
- [ ] T096 [US5] Crear `src/radvol3d/services/segmentation/lung_unet_network.py`, con torch: `ResidualBlock` (era `BloqueResidual`) y `SegmentationUnet3d` (era `UNet3DSegmentacion`), con `features` (era `caracteristicas`). Los nombres de submódulos y atributos que aparecen en el `state_dict` **no se renombran**: `c1`, `n1`, `c2`, `n2`, `act`, `salto`, `entrada`, `bajadas`, `subidas`, `fusiones` y `cabezas`. Agregar un comentario que lo explique, como en T090.
- [ ] T097 [US5] Crear `src/radvol3d/services/segmentation/lung_segmenter.py`, con torch, y en él `LungSegmenter` (era `SegmentadorPulmon`):
  - métodos `segment` (era `segmentar`), `probability` (era `probabilidad`), `describe` (era `describir`) y `_validate` (era `_validar`);
  - lee las mismas claves del `.pth`, con los mismos valores por omisión;
  - `torch.load(..., weights_only=True)` (R15);
  - TTA, ventanas, pesos gaussianos y umbral idénticos.

  No migrar `autoprueba` ni el `__main__` (R14).
- [ ] T098 [US5] Implementar `src/radvol3d/services/segmentation/lung_unet_strategy.py`:
  - `LungUnetStrategy(engine)`, con candado;
  - `from_weights(path)`, que importa `LungSegmenter` dentro del método;
  - `segment(volume, study_code)`, que llama a `engine.segment(volume)`, alinea los identificadores del resumen como en T094 (research.md R14; FR-023a: la alineación ocurre en la estrategia, no en el motor) y arma las `Lesion`.

  El módulo no importa torch en su nivel superior. Hace pasar T094.

### Pruebas `ml` y publicación

- [ ] T099 [US5] Crear `tests/ml/conftest.py`:
  - todas las pruebas de la carpeta llevan `pytestmark = pytest.mark.ml`, mediante `pytest_collection_modifyitems` o un `pytestmark` en cada módulo;
  - llama a `pytest.importorskip("torch")`;
  - expone la fixture `model_artifacts`, que obtiene los objetos del manifiesto desde `MODEL_CACHE_DIR` o, si faltan, con `ModelWeightsStore` sobre el bucket de modelos de `.env.test`;
  - verifica el SHA-256 de cada objeto contra `tests/ml/reference/manifest.json`;
  - omite las pruebas con un mensaje claro si faltan los artefactos o el bucket.
- [ ] T100 [P] [US5] Escribir `tests/ml/test_en1_regression.py`. `NeuralEn1Strategy.from_weights(...)` sobre `regression/en1_phantom_projections.npy` da una diferencia absoluta máxima menor o igual a `1e-5` contra `regression/en1_phantom_volume.npy`. Si falla, el mensaje incluye la diferencia y el entorno del manifiesto frente al actual.
- [ ] T101 [P] [US5] Escribir `tests/ml/test_en2_regression.py`, con los casos 2 y 3. Usa `LungSegmenter` directo para comparar el resumen sin alinear:
  - la máscara es idéntica (`np.array_equal`);
  - la probabilidad difiere en `1e-5` o menos;
  - el resumen es igual campo por campo.

  Además, `LungUnetStrategy` produce el resumen alineado de FR-025 con los mismos números.
- [ ] T102 [US5] Escribir `tests/ml/test_example_study.py` (historia 5, escenarios 1 a 4; SC-003; criterio de aceptación 2). Arma `StudyService` con las estrategias reales (`build_service_container` sobre `.env.test`) y procesa como estudio `it_` las proyecciones del fantoma (`regression/en1_phantom_projections.npy` repartidas en cuatro `.npy`). Comprueba:
  - el estudio queda en `completed`;
  - el bucket tiene `volume.npy`, `mask.npy`, `probability.npy`, `summary.json`, `organ.glb` y `tumor.glb`;
  - las dos mallas empiezan con `glTF` y trimesh las vuelve a abrir;
  - cada región del resumen tiene su fila en `lesion`;
  - la tabla `model` tiene `reconstruction_en1` y `segmentation_lung` con `trained_on` nulo.

  Al final, borra el estudio con `delete_study`.
- [ ] T103 [US5] Crear `scripts/publish_model_artifacts.py`, que sube a `MODEL_BUCKET` con `ObjectStorage.from_settings(settings, bucket=...)`:
  - el `.pth` de EN-1, sin cambios;
  - el `.pth` de exportación de EN-2;
  - los objetos `regression/` de T086.

  Las rutas son las de [contracts/model_artifacts.md](contracts/model_artifacts.md). No imprime claves ni URLs firmadas. Ejecutarlo (quickstart.md D1), escribir `EN1_WEIGHTS_OBJECT` y `EN2_WEIGHTS_OBJECT` en `.env` y `.env.test`, y correr `pytest -m ml -v`: T100 a T102 en verde.
- [ ] T104 [US5] Completar `default_strategy_builders` en `src/radvol3d/services/service_container.py` con las descripciones de data-model.md §5 para `register_model`. Agregar los comentarios `TODO(TRAINING_DATE_EN1)` y `TODO(TRAINING_DATE_EN2)` junto a `trained_on=None` (Principio V). Arrancar con `uvicorn radvol3d.main:app` y comprobar quickstart.md D3: el registro de arranque muestra los dos modelos disponibles y, sin `EN2_WEIGHTS_OBJECT`, la aplicación arranca igual.
- [ ] T105 [P] [US5] Reescribir `docs/models/reconstruction_en1.md` y `docs/models/segmentation_lung_en2.md` y crear `docs/models/meshing.md`:
  - **Rutas.** Ruta de los pesos en el bucket y módulos migrados.
  - **Procedencia del `.pth` de exportación de EN-2.** Cada clave con su fuente (Q1 = B).
  - **Métricas de `models/metricas_test.json`, copiadas sin cambios y citando el archivo.** Dice de validación 0,7361, de prueba 0,6553 ± 0,2771, precisión 0,6628, sensibilidad 0,804, n = 44/9/10, umbral 0,3 y la referencia de Carles et al.
  - **Fechas.** `TODO(TRAINING_DATE_EN1)` y `TODO(TRAINING_DATE_EN2)`.
  - **Tiempos medidos en CPU.** ≈ 11 s y ≈ 148 s.
  - **En `meshing.md`.** Otsu, componente mayor, `step_size`, coordenadas, y que la malla del órgano depende de la calidad de la reconstrucción, con el umbral fijo en HU como mejora futura (FR-026a).

**Checkpoint**: criterio de aceptación 2 cumplido. Con las estrategias reales, un estudio de ejemplo produce volumen, máscara, resumen y mallas.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: enmienda de la constitución, documentos de arquitectura, contrato de 001 y
validación final.

- [ ] T106 Enmendar `.specify/memory/constitution.md` (PATCH 1.0.0 → 1.0.1), en un commit `docs(specify): actualiza la ruta de la tuberia en la constitucion`:
  - en el Principio II, `services/processing_pipeline.py` pasa a `services/pipeline/processing_pipeline.py`;
  - actualizar el Sync Impact Report y `Last Amended: 2026-10-09`.

  No cambia ningún principio.
- [ ] T107 [P] Actualizar `docs/architecture/design_patterns.md` con las rutas nuevas, la estrategia de mallas (Strategy para las tres etapas), la fábrica con registros y la tubería como Pipes and Filters en `services/pipeline/`. Actualizar `docs/architecture/fastapi_structure.md`: se quitan `get_processing_pipeline` y su ejemplo, y se agrega `get_study_service` desde `app.state`.
- [ ] T108 [P] Reescribir `specs/001-persistence-schema-migration/contracts/persistence_api.md` incorporando [contracts/persistence_api_changes.md](contracts/persistence_api_changes.md), para que quede un solo contrato vigente: `ModelSettings`, `remove_many`, `ModelWeightsStore`, `ProcessingProgressStore`, `delete_study`, `lock_status`, `delete` y el `save_result` nuevo. Agregar una nota con la fecha que remita a la funcionalidad 002.
- [ ] T109 [P] Revisar los docstrings de `src/radvol3d/services/` y `src/radvol3d/persistence/` que mencionan "[0,1]" para las proyecciones, `services/preprocessing` o "no hay borrado", y corregirlos.
- [ ] T110 Correr quickstart.md completo, bloques A a E: `ruff check src tests`, `python scripts/check_naming_convention.py`, `pytest -m "unit or architecture"`, la cobertura de services de T078 (80 % o más), `pytest -m integration`, `pytest -m concurrency`, `pytest -m ml --cov=src/radvol3d/services` y `git status --short`, sin `.pth`, `.npy` ni `models/`. Escribir en la descripción del pull request:
  - el peso de las dependencias (R3);
  - la cobertura del CI y la local con `ml`;
  - el cambio en `save_result` (R7) y el borrado nuevo en la persistencia;
  - la enmienda PATCH de la constitución;
  - el uso de `weights_only=True` (R15).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Fase 1)**: no depende de nada.
- **Foundational (Fase 2)**: depende de la Fase 1. Bloquea todas las historias.
- **US1 (Fase 3)**: depende de la Fase 2.
- **US2 (Fase 4)**: depende de US1, porque amplía el cargador, la tubería, la fábrica, el almacén de avance y el servicio que crea US1. Sus pruebas se pueden escribir en paralelo con la implementación de US1.
- **US3 (Fase 5)**: depende de la Fase 2. Su parte de persistencia (T053 a T061) es independiente de US1 y US2. T062 y T058 necesitan el `StudyService` de US1.
- **US4 (Fase 6)**: depende de US1, porque arma `StudyService` y la fábrica. T064 a T066 y T071 a T073 son independientes y pueden adelantarse.
- **Cierre del bloque con dobles (Fase 7)**: depende de US1 a US4.
- **US5 (Fase 8)**: depende de la Fase 7, por el orden de construcción pedido. Dentro de US5:
  - las mallas (T081 y T082) solo necesitan la Fase 2;
  - T083 a T086, la referencia generada con los originales, **deben terminar antes** de T089 a T098, la migración;
  - T099 a T104 necesitan la migración y la publicación.
- **Polish (Fase 9)**: depende de todo lo anterior. T106 y T107 pueden adelantarse en cuanto exista T013.

### Dependencias dentro de los componentes

- Cada prueba va antes de su implementación y debe fallar primero:
  - T021 → T032 y T044 → T050
  - T022 → T033
  - T023 y T041 → T034 y T047
  - T024 → T035
  - T025 y T042 → T036 y T048
  - T026 y T043 → T037 y T049
  - T027 → T038
  - T028 y T045 → T039 y T051
  - T053 a T057 → T059 a T062
  - T064 a T069 → T071 a T076
  - T081 → T082
  - T083 → T084
  - T087 → T089
  - T088 → T092
  - T093 → T095
  - T094 → T098
- T017 → T020, y T017 → todas las pruebas que usan los dobles.
- T013 → T034, T036 y T076, porque las rutas se mueven.
- T029 → T030, T046, T058, T070 y T102, que usan las fixtures compartidas de integración.
- T090 → T091 → T092, y T095 → T096 → T097 → T098.
- T086 → T093, porque el JSON de referencia del caso 4 lo genera T085.

### Parallel Opportunities

- **Fase 1.** T003, T004 y T005.
- **Fase 2.** T006 a T012 y T014 a T019, porque son archivos distintos. T013 va solo, porque mueve archivos que otros importan.
- **US1.** Las pruebas T021 a T028. Después T032 y T033 (persistencia) en paralelo con T034 y T035 (servicios).
- **US2.** Las pruebas T040 a T045, y T052 en cualquier momento.
- **US3.** T053 a T057, después T059 y T060.
- **US4.** T064 a T069, después T071 a T073.
- **US5.**
  - T081 y T082 (mallas) en paralelo con T083 a T086 (artefactos).
  - Después: T087 y T088 (EN-1) en paralelo con T093 y T094 (EN-2).
  - T100 y T101 en paralelo.

---

## Parallel Example: User Story 1

```bash
# Escribir juntas todas las pruebas de US1 (deben fallar):
Task: "T021 tests/unit/persistence/test_processing_progress_store.py"
Task: "T022 tests/unit/persistence/test_result_store.py (R7)"
Task: "T023 tests/unit/services/test_projection_loader.py"
Task: "T024 tests/unit/services/test_pipeline_filters.py"
Task: "T025 tests/unit/services/test_processing_pipeline.py"
Task: "T026 tests/unit/services/test_strategy_factory.py"
Task: "T027 tests/unit/services/test_persistence_progress.py"
Task: "T028 tests/unit/services/test_study_service.py"

# Después, persistencia y servicios en paralelo:
Task: "T032 src/radvol3d/persistence/processing_progress_store.py"
Task: "T034 src/radvol3d/services/pipeline/projection_loader.py"
Task: "T035 src/radvol3d/services/pipeline/filters.py"
```

## Parallel Example: User Story 5

```bash
# Mallas y artefactos de referencia a la vez:
Task: "T081-T082 meshing/marching_cubes_strategy.py"
Task: "T083-T086 scripts/export_en2_weights.py + scripts/build_regression_reference.py"

# Migración de EN-1 y EN-2 a la vez (después de T086):
Task: "T087-T092 reconstruction/en1_*.py + neural_en1_strategy.py"
Task: "T093-T098 segmentation/lung_*.py + lung_unet_strategy.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Fase 1 (Setup) y Fase 2 (Foundational).
2. Fase 3 (US1): la tubería completa con dobles contra el Supabase de prueba.
3. **PARAR y VALIDAR**: correr T030. El estudio queda en `completed`, con sus etapas y resultado.

### Incremental Delivery

1. Setup y Foundational: interfaces y dobles listos.
2. US1: tubería de punta a punta (MVP).
3. US2: errores claros y estados consistentes. Con US1 cubre las dos historias P1.
4. US3: consulta y borrado.
5. US4: arranque por `lifespan` con todo conectado una vez.
6. Fase 7: CI en verde con 80 % en services. **Criterio de aceptación 1.**
7. US5: mallas, referencia, migración, pruebas `ml` y publicación. **Criterio de aceptación 2.**
8. Polish: constitución, documentos y validación final. **Criterio de aceptación 3.**

### Commits

Se usa Conventional Commits, con el ámbito igual a la carpeta tocada:

- `feat(domain)`, `feat(persistence)`, `feat(services)` y `feat(api)` para el código;
- `test(services)`, `test(persistence)` y `test(ml)` para las pruebas que van solas;
- `chore` para dependencias, `.gitignore` y CI;
- `docs(models)` y `docs(architecture)` para los documentos;
- `docs(specify)` para la enmienda.

Antes de cada commit: `pytest -m "unit or architecture"`, `ruff check src tests` y
`python scripts/check_naming_convention.py`.

---

## Notes

- [P] significa archivos distintos, sin depender de tareas sin terminar.
- Ninguna prueba `unit` importa torch. Si una lo necesita, va en `tests/ml/`.
- `tests/architecture/test_layer_boundaries.py` no se modifica. Si falla, se corrige el import.
- Los nombres de submódulos de las redes que aparecen en el `state_dict` (T090 y T096) se
  mantienen en español a propósito, porque renombrarlos rompe la carga de los pesos. Son datos
  del formato del archivo, igual que las claves de los `.pth`. `ruff` y
  `scripts/check_naming_convention.py` no los marcan, porque están en minúsculas.
- Ningún dato se inventa: fechas, métricas y referencias salen del repositorio o de un script
  que deja su fuente escrita (Principio V).
