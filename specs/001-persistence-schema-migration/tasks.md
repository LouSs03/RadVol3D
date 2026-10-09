---

description: "Lista de tareas: migración de la capa de persistencia al esquema en inglés"
---

# Tasks: Migración de la capa de persistencia al esquema en inglés

**Input**: Design documents from `/specs/001-persistence-schema-migration/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/persistence_api.md](contracts/persistence_api.md), [quickstart.md](quickstart.md)

**Tests**: SÍ se incluyen. La constitución (Principio IV) y FR-053 exigen una prueba unitaria por
componente en el mismo pull request, y FR-053 pide además pruebas de integración. En cada
componente la prueba va antes de la implementación: se escribe primero y debe fallar.

**Organization**: Las tareas se agrupan por historia de usuario (US1 a US4 de la especificación).
Los componentes que usan todas las historias están en la Fase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (archivos distintos, sin depender de tareas sin terminar)
- **[Story]**: historia de la especificación a la que pertenece la tarea (US1 a US4)
- Todas las rutas son relativas a la raíz del repositorio

## Path Conventions

Proyecto único (ver "Structure Decision" en [plan.md](plan.md)):

- Código: `src/radvol3d/domain/` y `src/radvol3d/persistence/`
- Pruebas unitarias: `tests/unit/` (marca `unit`)
- Pruebas de integración: `tests/integration/persistence/` (marca `integration`)
- Dobles: `tests/fixtures/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependencia nueva, configuración de pruebas de integración y carpetas de pruebas.

- [X] T001 Cambiar `psycopg[binary]>=3.1` por `psycopg[binary,pool]>=3.1` en `requirements.txt`, ejecutar `pip install -r requirements-dev.txt` y comprobar que `import psycopg_pool` funciona. El peso de la dependencia nueva (`psycopg-pool` 3.3.3, 40 304 bytes, Python puro) debe quedar escrito en la descripción del pull request (Constitución, "Servicios y dependencias").
- [X] T002 [P] Agregar `.env.test` a `.gitignore` y crear `.env.test.example` con las cuatro variables de `.env.example` (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BUCKET`), sin valores, y un comentario en español que diga que debe apuntar a un proyecto de Supabase **de prueba**, nunca al real.
- [X] T003 [P] Crear los paquetes vacíos `tests/unit/domain/__init__.py`, `tests/unit/persistence/repositories/__init__.py` y `tests/integration/persistence/__init__.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: dominio, dobles de prueba y los componentes que usan todas las historias: configuración,
conexión, traducción de errores, rutas del bucket y almacenamiento de objetos.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta terminar esta fase.

### Dobles y utilidades de prueba

- [X] T004 [P] Crear `tests/fixtures/fake_database.py` con: `FakeConnection` (registra cada `execute(sql, params)` en una lista y devuelve filas preparadas como **diccionarios**; puede lanzar un error preparado), `FakeDatabase` (su `transaction()` entrega la `FakeConnection`, y marca si se confirmó o se revirtió) y subclases de `psycopg.errors` (`UniqueViolation`, `CheckViolation`, `IntegrityError`, `OperationalError`) cuyo `diag.constraint_name` y `sqlstate` se pasan al construirlas. `FakeConnection` y `FakeDatabase` aceptan una lista opcional compartida `events` donde anotan sus operaciones.
- [X] T005 [P] Crear `tests/fixtures/fake_object_storage.py` con `InMemoryBucket`, que imita `upload(path, data, file_options)`, `download(path)` y `exists(path)` de storage3, guarda los archivos y su tipo de contenido en un diccionario, lanza `storage3.utils.StorageException` si se baja un archivo que no existe, y acepta la misma lista opcional `events` que T004.
- [X] T006 [P] Crear `tests/integration/persistence/conftest.py`: lee **solo** `.env.test` (nunca `.env`) y, si no existe, omite todas las pruebas con `pytest.skip`. Expone fixtures de `Database` y `ObjectStorage` reales sobre ese proyecto de prueba, una fábrica de códigos de estudio con el prefijo `it_`, y una limpieza al terminar que borra los estudios `it_%` (las proyecciones, etapas y lesiones se borran en cascada), los pacientes que la prueba haya creado (registrando los códigos que devuelva cada registro) y los archivos del bucket bajo esos códigos, usando el cliente de storage3 directamente. Ese SQL y esa limpieza viven solo en las pruebas.

### Dominio

- [X] T007 [P] Escribir `tests/unit/domain/test_exceptions.py`: las siete clases nuevas heredan de `RadVol3DError`, `StorageObjectNotFoundError` hereda de `StorageError`, y cada una se puede construir con un mensaje en español.
- [X] T008 [P] Escribir `tests/unit/domain/test_entities.py`: (a) `Study` y `ProcessingStage` se siguen construyendo como antes, sin los campos nuevos; (b) `repr` y `str` de `Patient` y de `PatientDetails` no contienen el nombre, el apellido ni el DNI; (c) `Study` guarda `patient`, `model` y `grid_size`; (d) `ProcessingStage` guarda `model`; (e) `StoredResult("it_x")` construido solo con el código tiene las cinco rutas en `None` y `lesions == []`.
- [X] T009 [P] Agregar a `src/radvol3d/domain/exceptions.py` los errores de [data-model.md](data-model.md#errores-nuevos-en-domainexceptionspy): `ConfigurationError`, `DuplicateStudyError`, `InvalidPatientDataError`, `PatientCodeExhaustedError`, `UnknownOrganError`, `InvalidLesionError` y `PersistenceError`, todos hijos de `RadVol3DError`, y `StorageObjectNotFoundError` hijo de `StorageError`. Docstrings en español.
- [X] T010 [P] Modificar `src/radvol3d/domain/entities.py` (data-model.md, "Entidades del dominio"). Definir **antes** de `Study`: `Patient` (`patient_code: str`, `first_name`, `last_name`, `national_id`, todos `str | None`, con `field(repr=False)`), `PatientDetails` (los mismos tres campos opcionales, también `repr=False`), `Model` (`model_name: str`, `version: str`, `trained_on: date | None`, `description: str | None`) y `StoredResult` (`study_code: str`; `lesions: list[Lesion]` con `default_factory=list`; y `mask_path`, `probability_path`, `summary_path`, `organ_mesh_path`, `tumor_mesh_path`, todos `str | None = None`, para poder representar un resultado vacío, FR-049). Agregar a `Study`, **después** de los campos existentes y con valor por defecto: `patient: Patient | None = None`, `model: Model | None = None`, `grid_size: int | None = None`. Agregar a `ProcessingStage`, al final: `model: Model | None = None`. No agregar ids seriales (research.md, R4). Sin lógica ni entrada/salida (Principio I).

### Configuración y conexión (camino correcto)

- [X] T011 [P] Escribir `tests/unit/persistence/test_settings.py` (camino correcto): con las cuatro variables en el entorno (`monkeypatch.setenv`) y `Settings(_env_file=None)` para no leer el `.env` real, `Settings` las expone; `database_url` y `supabase_service_key` son `SecretStr`; `get_settings()` guarda el resultado; importar el módulo no falla aunque falte `.env`.
- [X] T012 Implementar `src/radvol3d/persistence/settings.py` según research.md R6: `Settings(BaseSettings)` con `database_url` y `supabase_service_key` como `SecretStr`, `supabase_url` y `storage_bucket` como `str`, los cuatro con `min_length=1`; lee `.env` de la raíz del repositorio (`Path(__file__).parents[3]`) y del entorno, con prioridad al entorno; `get_settings()` con `functools.cache`. (El manejo de errores es de T051.)
- [X] T013 [P] Escribir `tests/unit/persistence/test_connection.py` (camino correcto), con un grupo falso inyectado: `open()` abre el grupo una sola vez y espera a que esté listo; `close()` lo cierra; `transaction()` entrega una conexión, confirma al salir sin error y revierte si hay una excepción; `from_settings` arma el grupo con `min_size=1`, `max_size=4`, 10 s de espera y filas como diccionarios.
- [X] T014 Implementar `src/radvol3d/persistence/connection.py` según research.md R1 y R2: `Database` con `from_settings(settings)`, `open()`, `close()` y `transaction()`. Usa `psycopg_pool.ConnectionPool` con `open=False`, `min_size=1`, `max_size=4`, tiempo de espera de 10 s y `kwargs={"row_factory": dict_row}`. `transaction()` toma una conexión del grupo, abre `conn.transaction()` y la entrega. El constructor acepta un `pool_factory` opcional para inyectar un grupo falso en las pruebas sin red. Los valores 1, 4 y 10 s son decisiones, no mediciones (research.md R1). (La traducción de fallos es de T052.)

### Traducción de errores de la base

- [X] T015 [P] Escribir `tests/unit/persistence/test_database_errors.py` con los dobles de T004: cada fila de la tabla [Restricciones y errores del dominio](data-model.md#restricciones-y-errores-del-dominio) produce su error; `OperationalError` y `PoolTimeout` producen `DatabaseUnavailableError`; cualquier otra `IntegrityError` produce `PersistenceError`; el mensaje del error resultante no contiene el texto de psycopg ni valores como un DNI de la causa.
- [X] T016 Implementar `src/radvol3d/persistence/database_errors.py`: una función que recibe un `psycopg.Error` y **devuelve** el error del dominio según la clase y `error.diag.constraint_name`, con la correspondencia completa de data-model.md. Mensajes propios en español, sin copiar el mensaje de psycopg. Quien la llama lanza el resultado con `raise ... from None` (research.md R3).

### Rutas del bucket

- [X] T017 [P] Escribir `tests/unit/persistence/test_storage_layout.py`: las siete rutas exactas de FR-013 (`<study_code>/projections/angle_000.npy` con `045`, `090` y `135`, `volume.npy`, `segmentation/mask.npy`, `segmentation/probability.npy`, `segmentation/summary.json`, `meshes/organ.glb`, `meshes/tumor.glb`); la misma entrada da la misma ruta; `InvalidStudyIdError` para un código que no cumpla `^[A-Za-z0-9_-]{1,64}$`, que contenga `..` o una barra invertida, o esté vacío; `InvalidProjectionError` para un ángulo fuera de `(0, 45, 90, 135)`; no existe ninguna función para `lesion_<region_id>.glb`.
- [X] T018 Implementar `src/radvol3d/persistence/storage_layout.py` con las funciones del contrato: `validate_study_code`, `projection_path`, `volume_path`, `mask_path`, `probability_path`, `summary_path`, `organ_mesh_path` y `tumor_mesh_path`. Funciones puras: sin acceso a la base ni al bucket (FR-017). No generar la ruta reservada `lesion_<region_id>.glb` (FR-051).

### Almacenamiento de objetos

- [X] T019 [P] Escribir `tests/unit/persistence/test_object_storage.py` con `InMemoryBucket` (T005): subir y bajar devuelve los mismos bytes; subir a una ruta ocupada reemplaza el archivo; `exists` responde bien; un arreglo `.npy` vuelve igual; un `.npy` con objetos serializados se rechaza con `StorageError`; bajar un archivo inexistente lanza `StorageObjectNotFoundError`; un fallo de acceso lanza `StorageError` y no `StorageObjectNotFoundError`; tipos de contenido `application/octet-stream`, `application/json` y `model/gltf-binary`.
- [X] T020 Implementar `src/radvol3d/persistence/object_storage.py` según research.md R7: `ObjectStorage(bucket)` con `upload_bytes`, `download_bytes`, `exists`, `upload_array` y `download_array`; `from_settings(settings)` arma el bucket con `create_client(url, key).storage.from_(bucket)`. Subir con `upsert` en `"true"`. Los arreglos usan `numpy.save` y `numpy.load` sobre `BytesIO`, siempre con `allow_pickle=False`; el `ValueError` de numpy se traduce a `StorageError`. `StorageException` se traduce a `StorageError`; ante un error de descarga se consulta `exists` para distinguir "no existe" (`StorageObjectNotFoundError`) de un fallo de acceso.

**Checkpoint**: dominio, configuración, conexión, rutas y almacenamiento listos. `pytest -m unit` pasa y puede empezar cualquier historia.

---

## Phase 3: User Story 1 - Registrar un estudio con su paciente y sus cuatro proyecciones (Priority: P1) 🎯 MVP

**Goal**: la capa de lógica identifica o registra al paciente, crea el estudio en `pending` con sus cuatro proyecciones en el bucket y sus cuatro etapas en `waiting`, y lo puede volver a pedir por su código.

**Independent Test**: registrar un estudio de pulmón con DNI y cuatro proyecciones y pedirlo por su código. Vuelve con su paciente, el órgano, `pending`, las cuatro proyecciones ordenadas por ángulo y las cuatro etapas en `waiting`, y cada proyección se puede descargar desde su ruta.

### Tests for User Story 1 ⚠️

> Escribir primero. Deben fallar antes de implementar.

- [X] T021 [P] [US1] Escribir `tests/unit/persistence/repositories/test_patient_repository.py` (FR-022 a FR-025, SC-007; research.md R5): el candado `pg_advisory_xact_lock` se pide antes que cualquier lectura; DNI ya registrado devuelve el paciente existente sin modificarlo; DNI nuevo crea uno con el siguiente `PAC` consecutivo; solo nombre o apellido crea un paciente nuevo sin buscar por nombre; sin datos devuelve `PAC000000`; nombre o apellido en blanco cuentan como ausentes; DNI que no cumple `^[0-9]{8}$` lanza `InvalidPatientDataError`; pasar de `PAC999999` lanza `PatientCodeExhaustedError`; si falta `PAC000000` lanza `PersistenceError`; el DNI, el nombre y el apellido no aparecen en ningún mensaje de error.
- [X] T022 [P] [US1] Escribir `tests/unit/persistence/repositories/test_organ_repository.py` (FR-026): `list_all` devuelve `lung` y `liver` como `Organ`; `get_by_name` acepta `OrganName` o texto; un nombre fuera de alcance lanza `UnknownOrganError`; el repositorio no tiene métodos de escritura.
- [X] T023 [P] [US1] Escribir `tests/unit/persistence/repositories/test_study_repository.py` (FR-030, FR-031, FR-032, FR-034): `create` deja el estudio en `pending` y devuelve un `Study` con su paciente; un código repetido lanza `DuplicateStudyError`; un código que viola `study_code_format` lanza `InvalidStudyIdError`; `get_by_code` devuelve el estudio con órgano, paciente y modelo o lanza `StudyNotFoundError`; `list_recent` ordena del más reciente al más antiguo y no trae proyecciones, etapas ni lesiones.
- [X] T024 [P] [US1] Escribir `tests/unit/persistence/repositories/test_projection_repository.py` (FR-035 a FR-037): `add_many` guarda ángulo, ruta y nombre original; un ángulo fuera de `(0, 45, 90, 135)` o repetido lanza `InvalidProjectionError`; un estudio inexistente lanza `StudyNotFoundError`; `list_by_study` ordena por ángulo.
- [X] T025 [P] [US1] Escribir `tests/unit/persistence/repositories/test_processing_stage_repository.py` (FR-038, FR-040; research.md R9), parte de US1: `prepare_stages` crea cuatro etapas numeradas del 1 al 4 en `waiting`, con `stage_name` `preprocessing`, `reconstruction`, `segmentation` y `meshing`, y usa `on conflict do nothing` para no duplicar; `list_by_study` ordena por número; un estudio inexistente lanza `StudyNotFoundError`.
- [X] T026 [P] [US1] Escribir `tests/unit/persistence/test_study_metadata_store.py` (FR-044, FR-045), parte de US1, con `FakeDatabase` e `InMemoryBucket` compartiendo `events`: `register_study` ejecuta en este orden (research.md R8): validar, identificar al paciente, insertar el estudio, subir las cuatro proyecciones, insertar proyecciones y etapas, confirmar; un código duplicado falla **antes** de subir cualquier archivo; un código inválido o un ángulo repetido falla sin tocar la base ni el bucket; si falla algo después de insertar, la transacción se revierte; `get_study` devuelve el estudio completo (paciente, órgano, modelo, rejilla, proyecciones, etapas y lesiones); `list_studies` devuelve los estudios sin lo anidado.
- [X] T027 [P] [US1] Escribir `tests/integration/persistence/test_study_registration_integration.py` (marca `integration`): registrar un estudio con DNI y cuatro proyecciones y leerlo de vuelta con los mismos valores (SC-001); dos registros con el mismo DNI producen un solo paciente (SC-007); dos registros simultáneos sin DNI reciben códigos distintos; el mismo código dos veces lanza `DuplicateStudyError` y conserva los archivos del estudio original; sin datos personales el paciente es `PAC000000`.

### Implementation for User Story 1

- [X] T028 [P] [US1] Implementar `src/radvol3d/persistence/repositories/patient_repository.py` (nuevo) con `find_or_create(details)` y `get_by_code(patient_code)`, según research.md R5 y data-model.md. Reglas verbatim: el DNI "MUST tener exactamente ocho dígitos y ser único" (`^[0-9]{8}$`, columna `varchar(16)`); el código nuevo se valida con `^PAC[0-9]{6}$`; nombre y apellido `varchar(80)`. Recibe la conexión de la unidad de trabajo en el constructor. Traduce los errores de psycopg con T016.
- [X] T029 [P] [US1] Implementar `src/radvol3d/persistence/repositories/organ_repository.py` con `list_all()` y `get_by_name(name)`. Solo lectura. La restricción de la base es `name in ('lung', 'liver')`, `varchar(32)`.
- [X] T030 [P] [US1] Implementar `src/radvol3d/persistence/repositories/study_repository.py` con `create`, `get_by_code` y `list_recent`. Restricciones verbatim: `study_code ~ '^[A-Za-z0-9_-]{1,64}$'`; `status in ('pending', 'processing', 'completed', 'failed')`, con valor inicial `pending`. Los ids seriales se resuelven dentro del SQL y no salen de la capa (research.md R4). `get_by_code` une `study`, `organ`, `patient` y, con unión externa, `model`; deja `projections`, `stages` y `lesions` vacías. Un código inexistente lanza `StudyNotFoundError`.
- [X] T031 [P] [US1] Implementar `src/radvol3d/persistence/repositories/projection_repository.py` con `add_many(study_code, projections)` y `list_by_study(study_code)`. Restricciones verbatim: `angle_degrees in (0, 45, 90, 135)` (`smallint`); `unique (study_id, angle_degrees)`; `file_path` `text` no nulo; `original_name` `varchar(255)` opcional. Validar el ángulo antes de tocar la base y de nuevo como respaldo con la restricción.
- [X] T032 [P] [US1] Implementar `src/radvol3d/persistence/repositories/processing_stage_repository.py` con `prepare_stages(study_code)` y `list_by_study(study_code)`. Restricciones verbatim: `stage_number between 1 and 4`; `stage_status in ('waiting', 'running', 'completed', 'skipped', 'failed')`, valor inicial `waiting`; `unique (study_id, stage_number)`; `stage_name` `varchar(32)` derivado con `StageNumber(n).name.lower()`. (`set_status` es de T041.)
- [X] T033 [US1] Implementar `src/radvol3d/persistence/study_metadata_store.py` con `ProjectionUpload`, `StudyMetadataStore(database, storage)`, `register_study`, `get_study` y `list_studies`, siguiendo el contrato y research.md R8. `register_study` hace todo dentro de una unidad de trabajo: valida el código y las cuatro proyecciones sin tocar nada, identifica al paciente, inserta el estudio, sube las proyecciones, inserta proyecciones y etapas y confirma. `get_study` arma el `Study` completo con los repositorios y asigna `projections`, `stages` y `lesions` en el estudio que devuelve `StudyRepository`. (`save_volume` es de T042.) Depende de T028 a T032.

**Checkpoint**: US1 funciona y se prueba sola. Este es el MVP: el sistema ya acepta y conserva estudios.

---

## Phase 4: User Story 2 - Seguir el avance del procesamiento (Priority: P2)

**Goal**: registrar en qué etapa va el estudio y cómo terminó cada una, el modelo usado, el estado general y el volumen reconstruido.

**Independent Test**: sobre un estudio registrado, avanzar las etapas 1 y 2 a `completed` y guardar el volumen; marcar la 3 y el estudio como `failed`. Las etapas 1 y 2 tienen inicio y fin, la 3 aparece fallida, la 4 en espera, y el volumen se descarga desde `<study_code>/volume.npy`.

### Tests for User Story 2 ⚠️

- [X] T034 [P] [US2] Escribir `tests/unit/persistence/repositories/test_model_repository.py` (FR-027 a FR-029): `get_or_create` con el mismo par `(model_name, version)` dos veces devuelve el mismo modelo y usa `on conflict`; `trained_on` y `description` se guardan solo si llegan, sin completarlos; `get` devuelve `Model` o `None`.
- [X] T035 [P] [US2] Ampliar `tests/unit/persistence/repositories/test_study_repository.py` (FR-033): `update_status` acepta los cuatro estados y lanza `StudyNotFoundError` si no existe; `mark_completed` registra `model`, `grid_size` y `total_time_sec` a la vez y deja el estudio en `completed`; un `total_time_sec` negativo termina en `PersistenceError` por la restricción `study_total_time_positive`.
- [X] T036 [P] [US2] Ampliar `tests/unit/persistence/repositories/test_processing_stage_repository.py` (FR-039; research.md R9): `set_status(..., RUNNING)` registra `started_at`; `COMPLETED`, `SKIPPED` y `FAILED` registran `finished_at`; una etapa que pasa a `skipped` sin haber empezado queda con `started_at` nulo, sin inventar la hora; acepta un `Model` opcional; un estudio inexistente lanza `StudyNotFoundError`.
- [X] T037 [P] [US2] Ampliar `tests/unit/persistence/test_study_metadata_store.py` (FR-046): `save_volume` sube el arreglo a `<study_code>/volume.npy` y devuelve esa ruta; un código inválido falla sin subir nada; un estudio inexistente lanza `StudyNotFoundError` sin subir nada (comprobación previa, antes de la subida y con la conexión ya liberada).
- [X] T038 [P] [US2] Escribir `tests/integration/persistence/test_processing_progress_integration.py` (marca `integration`): el recorrido del Independent Test de esta historia; un modelo registrado dos veces deja una sola fila; `mark_completed` deja el estudio con modelo, rejilla y tiempo; las horas `started_at` y `finished_at` quedan en orden.

### Implementation for User Story 2

- [X] T039 [P] [US2] Implementar `src/radvol3d/persistence/repositories/model_repository.py` con `get_or_create(model_name, version, trained_on=None, description=None)` y `get(model_name, version)`. Restricciones verbatim: `unique (model_name, version)`; `model_name` `varchar(64)`, `version` `varchar(32)`; `trained_on` `date` opcional ("Dato real, no estimado").
- [X] T040 [US2] Agregar `update_status` y `mark_completed` a `src/radvol3d/persistence/repositories/study_repository.py`. `grid_size` es `smallint`; `total_time_sec` es `numeric(9, 3)` con `check (total_time_sec is null or total_time_sec >= 0)`. La capa no impone el orden de las transiciones: solo acepta los cuatro valores de `StudyStatus`. Depende de T030.
- [X] T041 [US2] Agregar `set_status(study_code, stage_number, status, model=None)` a `src/radvol3d/persistence/repositories/processing_stage_repository.py`: `running` registra `started_at = now()`; `completed`, `skipped` y `failed` registran `finished_at = now()`; nunca se inventa `started_at`. Rechaza con `PersistenceError` un `finished_at` anterior a `started_at` (data-model.md, "Validaciones"). Depende de T032.
- [X] T042 [US2] Agregar `save_volume(study_code, volume)` a `src/radvol3d/persistence/study_metadata_store.py`: valida el código, comprueba que el estudio existe con `find_study_id` (si no, `StudyNotFoundError` y no se sube nada), sube el arreglo con `upload_array` a `volume_path` y devuelve la ruta. Depende de T033.

**Checkpoint**: US1 y US2 funcionan solas y juntas.

---

## Phase 5: User Story 3 - Guardar y consultar los resultados de la segmentación (Priority: P3)

**Goal**: guardar en una sola operación la máscara, la probabilidad, el resumen, las dos mallas y las filas de `lesion`, y marcar las etapas 3 y 4 como completadas.

**Independent Test**: sobre un estudio con las etapas 1 y 2 completadas, guardar un resultado con dos lesiones. Las lesiones vuelven con los mismos valores, los cinco archivos se descargan y las etapas 3 y 4 quedan en `completed`.

### Tests for User Story 3 ⚠️

- [X] T043 [P] [US3] Escribir `tests/unit/persistence/repositories/test_lesion_repository.py` (FR-041 a FR-043): `add_many` guarda `location`, `volume_mm3`, `max_diameter_mm` (opcional), `confidence` y `mesh_path`; un volumen no positivo o una confianza fuera de `[0, 1]` lanza `InvalidLesionError` y no guarda ninguna lesión del lote; una lesión sin diámetro se acepta y queda vacía; `list_by_study` devuelve los mismos valores.
- [X] T044 [P] [US3] Escribir `tests/unit/persistence/test_result_store.py` (FR-047 a FR-050; research.md R8 y R12), con `FakeDatabase` e `InMemoryBucket` compartiendo `events`: `save_result` valida el resumen antes de subir nada; sube `mask.npy`, `probability.npy`, `summary.json` (tal como llegó, `ensure_ascii=False`), `organ.glb` y `tumor.glb`; tres regiones dan tres filas de `lesion` con `mesh_path` igual a `<study_code>/meshes/tumor.glb`; `regions: []` da cero filas y completa las etapas 3 y 4; un elemento con `has_lesion` distinto de `true` no genera fila; una región sin `location`, `volume_mm3` o `confidence` lanza `InvalidLesionError` y no se sube ni se guarda nada; `region_id`, `confidence_min`, `confidence_max`, `voxels` y `centroid_voxel` no llegan a la base; las etapas 3 y 4 pasan a `completed` solo si todo salió bien, y la 3 queda con el modelo de `model_name` y `model_version` del resumen; `get_result` con las etapas 3 y 4 en `completed` devuelve las cinco rutas y las lesiones. Pruebas de FR-049, cada una con su propia función de prueba: (1) estudio existente con las etapas 3 y 4 en `waiting` devuelve un `StoredResult` vacío (cinco rutas en `None`, `lesions == []`) **sin lanzar error**; (2) estudio con solo la etapa 3 en `completed` también devuelve el resultado vacío; (3) tras un `save_result` fallido que alcanzó a subir archivos, `get_result` devuelve el resultado vacío; (4) `get_result` sobre un estudio sin resultado no hace ninguna llamada al bucket; (5) solo un código inexistente lanza `StudyNotFoundError`.
- [X] T045 [P] [US3] Escribir `tests/integration/persistence/test_result_storage_integration.py` (marca `integration`): el recorrido del Independent Test de esta historia con dos regiones; un resultado sin lesiones; un resultado con una lesión inválida deja las etapas 3 y 4 como estaban; `get_result` sobre un estudio recién registrado devuelve el resultado vacío sin error.

### Implementation for User Story 3

- [X] T046 [P] [US3] Implementar `src/radvol3d/persistence/repositories/lesion_repository.py` con `add_many(study_code, lesions)` y `list_by_study(study_code)`. Restricciones verbatim: `volume_mm3 > 0` (`numeric(12, 2)`); `confidence >= 0 and confidence <= 1` (`numeric(5, 4)`); `location` `varchar(128)`; `max_diameter_mm` `numeric(8, 2)` opcional; `mesh_path` `text`. Valida el lote completo antes de insertar y rechaza todo si una lesión no cumple.
- [X] T047 [US3] (Incluye conectar `LesionRepository.list_by_study` en `StudyMetadataStore._load`, en `src/radvol3d/persistence/study_metadata_store.py`, y ampliar `tests/unit/persistence/test_study_metadata_store.py`: `get_study` debe devolver las lesiones, FR-045. En US1 quedó vacía porque el repositorio de lesiones es de T046.) Implementar `src/radvol3d/persistence/result_store.py` con `ResultStore(database, storage)`, `save_result` y `get_result`. Orden: (1) validar `summary["regions"]` como lista y exigir `location`, `volume_mm3` y `confidence` en cada elemento; (2) subir los cinco archivos; (3) en una sola unidad de trabajo, insertar las lesiones, registrar el modelo de segmentación con `ModelRepository.get_or_create` y marcar las etapas 3 y 4 como `completed`. Correspondencia de FR-047a: `location`→`location`, `volume_mm3`→`volume_mm3`, `max_diameter_mm`→`max_diameter_mm`, `confidence`→`confidence`, `mesh_path`=`<study_code>/meshes/tumor.glb`. `get_result` (FR-049, research.md R14): si el estudio no existe lanza `StudyNotFoundError`; si sus etapas 3 y 4 están en `completed`, devuelve las cinco rutas calculadas con `storage_layout` y las lesiones; en cualquier otro caso devuelve `StoredResult(study_code)` vacío, **sin lanzar error y sin consultar el bucket**. Depende de T039, T041, T042 y T046.

**Checkpoint**: US1, US2 y US3 funcionan solas y juntas.

---

## Phase 6: User Story 4 - Arrancar con configuración válida o no arrancar (Priority: P4)

**Goal**: si falta una variable o la base no responde, el sistema lo dice en español, nombra la variable y nunca muestra una clave.

**Independent Test**: sin `SUPABASE_SERVICE_KEY` el sistema no arranca y el mensaje nombra la variable; con la base inaccesible se obtiene `DatabaseUnavailableError`; en ningún caso aparece el valor de una clave.

### Tests for User Story 4 ⚠️

- [X] T048 [P] [US4] Ampliar `tests/unit/persistence/test_settings.py` (FR-008, FR-009, SC-003, SC-006): sin cada una de las cuatro variables, `get_settings()` lanza `ConfigurationError` y el mensaje nombra esa variable; una variable vacía cuenta como faltante; el mensaje no contiene `input_value` ni el texto de pydantic; `str()` y `repr()` de `Settings` y el mensaje de error no contienen el valor de `SUPABASE_SERVICE_KEY` ni la contraseña de `DATABASE_URL`; el error no tiene `__cause__`.
- [X] T049 [P] [US4] Ampliar `tests/unit/persistence/test_connection.py` (FR-012): si el grupo no abre dentro del tiempo de espera, `open()` lanza `DatabaseUnavailableError`; un `OperationalError` o un `PoolTimeout` durante `transaction()` también; ninguno de los mensajes contiene la contraseña de la URL.
- [X] T050 [P] [US4] Escribir `tests/integration/persistence/test_startup_failures_integration.py` (marca `integration`): con un `DATABASE_URL` hacia un servidor que no existe, `Database.open()` lanza `DatabaseUnavailableError` en español y el mensaje no contiene la contraseña.

### Implementation for User Story 4

- [X] T051 [US4] Agregar el manejo de errores a `src/radvol3d/persistence/settings.py` (research.md R6): capturar el `ValidationError` de pydantic y lanzar `ConfigurationError("Falta la variable <NOMBRE> en .env", ...)` armado con los nombres de los campos que fallaron, nunca con el texto de pydantic, sin encadenar (`from None`). Sin la variable, el arranque se detiene. Depende de T012.
- [X] T052 [US4] Agregar a `src/radvol3d/persistence/connection.py` la traducción de fallos con `database_errors` (T016): `open()` y `transaction()` convierten `OperationalError` y `PoolTimeout` en `DatabaseUnavailableError`, con mensaje en español, sin la URL y sin encadenar. Depende de T014 y T016.

**Checkpoint**: las cuatro historias funcionan solas y juntas.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: verificar los criterios de éxito y cerrar lo que quedó pendiente de confirmar.

- [X] T053 Ejecutar `ruff check src tests` y `python scripts/check_naming_convention.py`. Corregir todo lo que marquen en los archivos de esta funcionalidad. Los docstrings `TODO: migrar...` de los trece componentes deben haber sido reemplazados (Principio III).
- [X] T054 Ejecutar `pytest -m "unit or architecture"` con la red desconectada. Deben pasar los trece componentes (SC-004) y `tests/architecture/test_layer_boundaries.py` sin modificarse (SC-008).
- [X] T055 [P] Comprobar SC-002: buscar `paciente|estudio|proyeccion|etapa_procesamiento|lesion_detectada|modelo|organo` en `src/radvol3d/persistence`. Debe dar cero coincidencias.
- [X] T056 Con un `.env.test` real, ejecutar `pytest -m integration tests/integration/persistence`. Confirmar los dos puntos que quedaron pendientes en research.md y data-model.md, y corregir `database_errors.py`, `object_storage.py`, `data-model.md` y `research.md` si la realidad es distinta: (a) los nombres de restricción `*_key` y `*_fkey` que PostgreSQL generó; (b) qué responde Supabase al bajar un objeto inexistente (R7).
- [X] T057 [P] Comprobar SC-003 sobre la salida de `pytest -m "unit or integration" -rA`: los valores de `.env.test`, el DNI, el nombre y el apellido de prueba deben aparecer cero veces.
- [X] T058 [P] Ejecutar `pytest --cov=src/radvol3d/persistence --cov-report=term-missing -m unit` y comprobar que cada uno de los trece componentes aparece cubierto por su prueba. Informar el resultado tal cual; no se fija una meta numérica (la especificación no la define).
- [X] T059 Recorrer [quickstart.md](quickstart.md) de punta a punta y dejar anotado en el pull request qué escenarios pasaron y cuáles no.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Fase 1)**: sin dependencias. T001 va primero porque instala `psycopg-pool`.
- **Foundational (Fase 2)**: depende de la Fase 1 y **bloquea** todas las historias.
- **User Stories (Fase 3 en adelante)**: dependen de la Fase 2, pero no son independientes entre sí:
  - **US1** no depende de ninguna otra historia.
  - **US2** necesita un estudio registrado, así que depende de US1.
  - **US3** depende de US1 y de US2 (necesita `ModelRepository`, `set_status` y `save_volume`).
  - **US4** solo amplía archivos de la Fase 2 (T051 sobre T012, T052 sobre T014 y T016). Puede hacerse en paralelo con US1 a US3.
- **Polish (Fase 7)**: depende de las historias que se quieran entregar.

### Dependencias dentro de los componentes

- Cada prueba (marcadas ⚠️) se escribe y falla antes de su implementación.
- T004 y T005 (dobles) antes de cualquier prueba unitaria que los use.
- T009 antes de T016, T028 a T033, T039 a T042, T046, T047, T051 y T052 (los errores del dominio).
- T010 antes de las tareas que construyen entidades (T028 a T033, T039 en adelante).
- T012 → T051. T014 → T052. T016 → T052.
- T030 → T040. T032 → T041. T033 → T042. T033 se escribe después de T028 a T032 (usa todos los repositorios de US1).
- T039, T041, T042 y T046 → T047.

### Parallel Opportunities

- Fase 1: T002 y T003 en paralelo.
- Fase 2: T004 a T008 en paralelo entre sí; T009 y T010 en paralelo; luego las parejas prueba/implementación de cada componente (T011-T012, T013-T014, T015-T016, T017-T018, T019-T020) pueden avanzar en paralelo entre sí.
- US1: T021 a T027 en paralelo (siete archivos de prueba); T028 a T032 en paralelo (cinco archivos distintos); T033 espera a todos.
- US2: T034 a T038 en paralelo; T039 en paralelo con las demás implementaciones, que tocan archivos que ya existen.
- US3: T043 a T045 en paralelo; T046 en paralelo con T044 si el resumen ya está definido.
- Con más de una persona: una persona hace US4 mientras otra hace US1, o dos personas se reparten los repositorios de US1.

---

## Parallel Example: User Story 1

```bash
# Las siete pruebas de US1 juntas (archivos distintos):
Task: "T021 test_patient_repository.py"
Task: "T022 test_organ_repository.py"
Task: "T023 test_study_repository.py"
Task: "T024 test_projection_repository.py"
Task: "T025 test_processing_stage_repository.py"
Task: "T026 test_study_metadata_store.py"
Task: "T027 test_study_registration_integration.py"

# Los cinco repositorios de US1 juntos (archivos distintos):
Task: "T028 patient_repository.py"
Task: "T029 organ_repository.py"
Task: "T030 study_repository.py"
Task: "T031 projection_repository.py"
Task: "T032 processing_stage_repository.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Fase 1: Setup.
2. Fase 2: Foundational (bloquea todo).
3. Fase 3: US1.
4. **Parar y validar**: ejecutar el Independent Test de US1 con `pytest -m "unit or architecture"` y la prueba de integración T027.
5. Hacer commit y abrir el pull request si se quiere entregar solo el MVP.

### Incremental Delivery

1. Setup + Foundational → base lista.
2. + US1 → se puede registrar y consultar un estudio (MVP).
3. + US2 → se puede seguir el avance y guardar el volumen.
4. + US3 → se pueden guardar y consultar los resultados clínicos.
5. + US4 → los errores de arranque quedan cubiertos (puede hacerse antes, ya que no depende de US1 a US3).
6. Cada historia agrega valor sin romper las anteriores.

### Commits

Cada commit sigue Conventional Commits con ámbito en inglés y descripción en español, por ejemplo
`feat(persistence): agrega el repositorio de pacientes`, `test(persistence): prueba el repositorio de pacientes`
y `chore(deps): agrega psycopg-pool`. La rama es `feat/persistence-schema-migration`.

---

## Notes

- **[P]** = archivos distintos y sin dependencias pendientes. El marcador [Story] enlaza cada tarea con su historia.
- Las pruebas unitarias llevan la marca `unit` y no usan red, base, bucket ni modelos reales (Principio IV). Las de integración llevan `integration` y leen solo `.env.test`.
- Los docstrings y comentarios van en español. Los archivos existentes del repositorio los escriben sin tildes ni eñes; conviene seguir ese estilo.
- **Decisiones menores tomadas al repartir las tareas** (no estaban en el plan; se pueden cambiar sin tocar la especificación):
  - las filas llegan como diccionarios (`row_factory=dict_row`) y los dobles de T004 devuelven diccionarios;
  - al implementar US1 se agregaron cuatro piezas que no estaban en el plan: `execute_translated` en `database_errors.py` (traduce errores de psycopg en un solo lugar), `repositories/row_mapping.py` (paso de filas a `Patient` y `Model`), `find_study_id` en `study_repository.py` (los ids seriales se resuelven dentro de la capa) y `validate_projection_angle` en `storage_layout.py`; todas con pruebas;
  - al implementar US2: `mark_completed` y `set_status` con un modelo que no esta en el catalogo fallan con `PersistenceError` en vez de dejar `model_id` vacio en silencio; `set_status` detecta `finished_at` anterior a `started_at` con `returning` y lanza `PersistenceError` (si el llamador propaga el error, la transaccion se revierte); `get_or_create` solo lee la fila existente cuando el `insert ... on conflict do nothing` no devuelve nada, y no sobrescribe sus datos; `save_volume` comprueba que el estudio existe antes de subir, para no dejar volumenes huerfanos en el bucket;
  - al implementar US3: `save_result` comprueba que el estudio existe antes de subir los cinco archivos (mismo criterio que `save_volume`: no dejar archivos huerfanos en el bucket), en una transaccion corta aparte; un resumen sin `model_name` o `model_version` falla con `PersistenceError` antes de tocar nada; `validate_lesion` tambien rechaza valores que no son numeros; y guardar un resultado dos veces sobre el mismo estudio duplica las filas de `lesion` porque la capa no tiene borrado (pregunta abierta, no se asumio ninguna regla);
  - al implementar US4: `Database.open()` convierte CUALQUIER error de psycopg en `DatabaseUnavailableError` (incluso una URL mal formada, que `translate_database_error` por si solo daria `PersistenceError`) y cierra el grupo a medio abrir para no dejar hilos corriendo; `transaction()` traduce los `psycopg.Error` que escapen del bloque (conexion perdida, commit fallido) y deja pasar sin tocar los errores del dominio y cualquier otra excepcion; el fallo de configuracion se lanza desde `get_settings()` y no se guarda en la cache; `test_startup_failures_integration.py` NO necesita `.env.test` (apunta a servidores inexistentes) y tarda unos 18 s porque `pool.close()` espera a sus hilos;
  - al cerrar (T056 a T059): el proyecto de Supabase de prueba estaba vacio y el esquema se aplico desde `docs/database/schema/001_create_tables.sql` en una sola transaccion, tras comprobar que `.env.test` no apunta al proyecto de `.env` y que `public` no tenia tablas; las 20 pruebas de integracion pasan contra Supabase real (unos 2 min); la limpieza deja la base como estaba (1 paciente de referencia, 2 organos) y el bucket vacio; los 10 nombres de restriccion que traduce `database_errors.py` existen en `pg_constraint`; con el registro en DEBUG, `hpack` escribia la cabecera `apikey` con la clave de servicio (228 apariciones), asi que `ObjectStorage.from_settings` sube ese logger a WARNING (research.md R15);
  - `FakeConnection` admite reglas por fragmento de SQL (`when`) además de la cola, e `InMemoryBucket.fail_next` admite `after=N` para fallar en la subida N+1;
  - `Database` acepta un `pool_factory` opcional para inyectar un grupo falso en las pruebas;
  - `FakeDatabase` e `InMemoryBucket` comparten una lista `events` para probar el orden entre la base y el bucket (research.md R8);
  - `get_result` (T044, T047): la decisión del usuario es devolver un resultado vacío, sin error, si el estudio existe y no tiene resultado (FR-049). Que "tiene resultado" signifique "etapas 3 y 4 en `completed`" es una decisión de este desglose (research.md R14), no del usuario.
- Fuera de alcance, ya registrado en [plan.md](plan.md): conectar estas piezas con `services/` y `lifespan`, y el borrado de estudios.
