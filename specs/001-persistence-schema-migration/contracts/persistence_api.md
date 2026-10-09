# Contrato: lo que `persistence/` ofrece a `services/`

> **Actualizado el 2026-10-09 por la funcionalidad 002** (`specs/002-services-pipeline/`):
> configuracion de modelos, `remove_many`, `ModelWeightsStore`, `ProcessingProgressStore`,
> `delete_study`, `lock_status` y `delete`; ademas, `save_result` ya no marca etapas.
>
> **Actualizado el 2026-10-09 por la funcionalidad 004** (`specs/004-rest-api-viewer/`): el
> flujo en tres pasos (`create_study`, `add_projections`, `claim_for_processing`,
> `load_projections`), `fail_interrupted_studies`, una malla por lesion (`lesion_mesh_path`,
> `save_result` con `lesion_meshes`, `read_file`, `read_lesion_mesh`), `list_names`, la columna
> `lesion.organ` (migracion 002) y el borrado de las mallas por lesion. Detalle en
> `specs/004-rest-api-viewer/contracts/persistence_api_changes.md`.
>
> Este es el unico contrato vigente de la persistencia.

Este contrato es interno: lo usan los servicios, no un sistema externo. Las firmas indican qué
entra, qué sale y qué error se lanza. No son la implementación. Todas las entidades son de
`domain/entities.py` y todos los errores, de `domain/exceptions.py`.

Reglas comunes:

- Ningún método devuelve filas, diccionarios de la base ni errores de psycopg o de storage3.
- Los repositorios reciben en su constructor la conexión de una unidad de trabajo. Fuera de ella
  no hacen nada.

## settings

```python
def get_settings() -> Settings          # ConfigurationError
class Settings:
    database_url: SecretStr
    supabase_url: str
    supabase_service_key: SecretStr
    storage_bucket: str
```

```python
def get_model_settings() -> ModelSettings   # nunca lanza por una variable faltante
class ModelSettings:                         # todas opcionales; una variable vacia cuenta
    model_bucket: str | None                 # como no definida (env_ignore_empty)
    en1_weights_object: str | None
    en2_weights_object: str | None
    model_cache_dir: Path                    # por omision .cache/models
    reconstruction_strategy: str             # por omision "en1"
```

`get_settings()` carga la configuración la primera vez y la guarda. `str()` y `repr()` de
`Settings` nunca muestran los secretos.

## connection

```python
class Database:
    @classmethod
    def from_settings(cls, settings: Settings) -> "Database"
    def open(self) -> None                       # DatabaseUnavailableError
    def close(self) -> None
    def transaction(self) -> ContextManager[Connection]   # DatabaseUnavailableError
```

`open()` se llama una sola vez, al arrancar. `transaction()` confirma la unidad de trabajo al
salir sin error y la revierte si hay una excepción.

## storage_layout

Son funciones puras: no tocan la base ni el bucket. Todas lanzan `InvalidStudyIdError` si el
código no es válido.

```python
def projection_path(study_code: str, angle_degrees: int) -> str   # + InvalidProjectionError
def volume_path(study_code: str) -> str
def mask_path(study_code: str) -> str
def probability_path(study_code: str) -> str
def summary_path(study_code: str) -> str
def organ_mesh_path(study_code: str) -> str
def tumor_mesh_path(study_code: str) -> str
def lesion_mesh_path(study_code: str, lesion_number: int) -> str
    # "<study_code>/meshes/lesion_<NNN>.glb", desde 001; InvalidLesionError si no es un int >= 1
def validate_study_code(study_code: str) -> str
```

El numero de la malla de una lesion es su posicion en el resumen, desde 1. No es `region_id`:
el enlace entre la fila de `lesion` y su malla es `mesh_path` (004, research.md R10).

## object_storage

```python
class ObjectStorage:
    def __init__(self, bucket: BucketClient) -> None
    @classmethod
    def from_settings(cls, settings: Settings, bucket: str | None = None) -> "ObjectStorage"
        # bucket=None abre el bucket de datos; con un nombre, abre ese (el de modelos)
    def upload_bytes(self, path: str, data: bytes, content_type: str) -> None   # StorageError
    def download_bytes(self, path: str) -> bytes            # StorageObjectNotFoundError, StorageError
    def exists(self, path: str) -> bool                     # StorageError
    def upload_array(self, path: str, array: ndarray) -> None   # StorageError
    def download_array(self, path: str) -> ndarray          # StorageObjectNotFoundError, StorageError
    def remove_many(self, paths: Sequence[str]) -> None     # StorageError
    def list_names(self, folder: str) -> list[str]          # StorageError
        # archivos directamente en la carpeta, en orden; [] si no existe
```

- Subir a una ruta ocupada reemplaza el archivo.
- `remove_many` borra en una sola llamada; una ruta que no existe no es error.
- Una instancia serializa sus llamadas al bucket con un candado propio: el cliente HTTP de
  Supabase no admite dos peticiones a la vez desde hilos distintos (002, research.md R13).

## model_weights_store

```python
class ModelWeightsStore:
    def __init__(self, storage: ObjectStorage, cache_dir: Path) -> None
    def fetch(self, object_path: str) -> Path
        # StorageObjectNotFoundError, StorageError (tambien por una ruta con '..' o '\')
```

Si el archivo ya esta en la cache, no lo baja. Si no, lo escribe en un temporal y lo renombra:
una descarga cortada nunca deja un archivo a medias.
- Los arreglos se escriben y se leen siempre sin `pickle`. Un `.npy` con objetos se rechaza con
  `StorageError`.

## repositories

```python
class PatientRepository:
    def find_or_create(self, details: PatientDetails | None) -> Patient
        # InvalidPatientDataError, PatientCodeExhaustedError, PersistenceError
    def get_by_code(self, patient_code: str) -> Patient | None

class OrganRepository:
    def list_all(self) -> list[Organ]
    def get_by_name(self, name: OrganName | str) -> Organ           # UnknownOrganError

class ModelRepository:
    def get_or_create(self, model_name: str, version: str,
                      trained_on: date | None = None, description: str | None = None) -> Model
    def get(self, model_name: str, version: str) -> Model | None

class StudyRepository:
    def create(self, study_code: str, organ: OrganName, patient_code: str) -> Study
        # DuplicateStudyError, InvalidStudyIdError, UnknownOrganError
    def get_by_code(self, study_code: str) -> Study                 # StudyNotFoundError
    def list_recent(self) -> list[Study]        # del más reciente al más antiguo, sin lo anidado
    def list_codes_by_status(self, status: StudyStatus) -> list[str]
        # del más antiguo al más reciente; PersistenceError si el estado no existe
    def update_status(self, study_code: str, status: StudyStatus) -> None   # StudyNotFoundError
    def mark_completed(self, study_code: str, model: Model, grid_size: int,
                       total_time_sec: float) -> None               # StudyNotFoundError
    def lock_status(self, study_code: str) -> StudyStatus   # select ... for update; StudyNotFoundError
    def lock_for_claim(self, study_code: str) -> tuple[StudyStatus, OrganName]
        # lo mismo y el órgano, en la misma consulta; StudyNotFoundError
    def delete(self, study_code: str) -> None                # en cascada; StudyNotFoundError

class ProjectionRepository:
    def add_many(self, study_code: str, projections: list[Projection]) -> None
        # InvalidProjectionError, StudyNotFoundError
    def list_by_study(self, study_code: str) -> list[Projection]    # ordenadas por ángulo
    def count_by_study(self, study_code: str) -> int    # una sola consulta; StudyNotFoundError

class ProcessingStageRepository:
    def prepare_stages(self, study_code: str) -> None   # idempotente; StudyNotFoundError
    def set_status(self, study_code: str, stage_number: StageNumber, status: StageStatus,
                   model: Model | None = None) -> None              # StudyNotFoundError
    def list_by_study(self, study_code: str) -> list[ProcessingStage]   # ordenadas por número

class LesionRepository:
    def add_many(self, study_code: str, lesions: list[Lesion]) -> None
        # InvalidLesionError (rechaza el lote completo), StudyNotFoundError
        # La columna organ la toma del estudio en el mismo insert; Lesion.organ se ignora.
    def list_by_study(self, study_code: str) -> list[Lesion]   # con organ; en orden de guardado
```

## study_metadata_store

```python
@dataclass(frozen=True)
class ProjectionUpload:
    angle_degrees: int
    array: ndarray
    original_name: str | None = None

class StudyMetadataStore:
    def __init__(self, database: Database, storage: ObjectStorage) -> None
    def register_study(self, study_code: str, organ: OrganName,
                       projections: list[ProjectionUpload],
                       patient: PatientDetails | None = None) -> Study
        # InvalidStudyIdError, InvalidProjectionError, InvalidPatientDataError,
        # DuplicateStudyError, UnknownOrganError, StorageError, DatabaseUnavailableError
    def get_study(self, study_code: str) -> Study       # completo; StudyNotFoundError
    def list_studies(self) -> list[Study]
    def save_volume(self, study_code: str, volume: ndarray) -> str   # devuelve la ruta
        # InvalidStudyIdError, StudyNotFoundError (antes de subir nada), StorageError
    def delete_study(self, study_code: str) -> None
        # InvalidStudyIdError, StudyNotFoundError, StudyInProgressError, StorageError,
        # DatabaseUnavailableError

    # Flujo en tres pasos de la API (004, research.md R2 y R3)
    def create_study(self, study_code: str, organ: OrganName,
                     patient: PatientDetails | None = None) -> Study
        # pending, cuatro etapas en waiting, sin proyecciones; no sube nada
        # InvalidStudyIdError, UnknownOrganError, InvalidPatientDataError, DuplicateStudyError
    def add_projections(self, study_code: str, projections: list[ProjectionUpload]) -> Study
        # InvalidProjectionError, InvalidStudyStateError (no pending o ya tiene), StudyNotFoundError
    def claim_for_processing(self, study_code: str,
                             check_organ: Callable[[OrganName], object] | None = None) -> None
        # pending + 4 proyecciones -> processing, con la fila bloqueada; check_organ recibe
        # el órgano antes del cambio y, si lanza, se revierte todo
        # InvalidStudyStateError, StudyNotFoundError, lo que lance check_organ
    def load_projections(self, study_code: str) -> dict[int, ndarray]
        # StorageObjectNotFoundError, StorageError
```

`register_study` sigue el orden de research.md (R8): el estudio se inserta antes de subir
cualquier archivo. Desde 004 es `create_study` + `add_projections` en una sola transaccion.

`add_projections` y `claim_for_processing` bloquean la fila del estudio (`lock_status` y
`lock_for_claim`). Con el
bloqueo, de dos pedidos simultaneos de procesar solo uno reclama el estudio: el otro espera, ve
`processing` y recibe `InvalidStudyStateError`.

`delete_study` hace todo en una transaccion: bloquea la fila (`lock_status`), rechaza un
estudio en `processing`, borra la fila (lo demas cae en cascada) y borra con `remove_many` las
diez rutas fijas de `storage_layout` mas las mallas `lesion_<NNN>.glb` que liste en
`<study_code>/meshes` (se listan en el bucket, no se leen de las filas, para limpiar tambien las
de un guardado fallido). Si el bucket falla, se revierte y el estudio sigue en pie. Los
pacientes y los modelos no se borran.

## processing_progress_store

Cada metodo es una unidad de trabajo completa. Cuando recibe un modelo, hace `get_or_create`
antes de enlazarlo.

```python
class ProcessingProgressStore:
    def __init__(self, database: Database) -> None
    def start_processing(self, study_code: str) -> None                 # StudyNotFoundError
    def start_stage(self, study_code: str, stage: StageNumber) -> None  # StudyNotFoundError
    def complete_stage(self, study_code: str, stage: StageNumber,
                       model_name: str | None = None, model_version: str | None = None) -> None
    def fail_from_stage(self, study_code: str, stage: StageNumber) -> None
        # etapa -> failed, siguientes -> skipped, estudio -> failed
    def complete_study(self, study_code: str, model_name: str, model_version: str,
                       grid_size: int, total_time_sec: float) -> None   # StudyNotFoundError
    def register_model(self, model_name: str, version: str,
                       trained_on: date | None = None, description: str | None = None) -> Model
    def fail_interrupted_studies(self) -> list[str]
        # por cada estudio en processing, en su transaccion: la etapa running (o la primera
        # waiting) -> failed, las siguientes -> skipped, el estudio -> failed. Devuelve codigos.
```

`fail_interrupted_studies` se llama una vez al arrancar. Supone un solo proceso de uvicorn
(004, research.md R4 y R5).

## result_store

```python
class ResultStore:
    def __init__(self, database: Database, storage: ObjectStorage) -> None
    def save_result(self, study_code: str, mask: ndarray, probability: ndarray,
                    summary: Mapping[str, Any], organ_mesh: bytes,
                    tumor_mesh: bytes, lesion_meshes: Sequence[bytes]) -> StoredResult
        # InvalidLesionError, PersistenceError (una malla por lesion, antes de subir nada),
        # StudyNotFoundError, StorageError, DatabaseUnavailableError
    def get_result(self, study_code: str) -> StoredResult              # StudyNotFoundError
    def read_file(self, study_code: str, file: ResultFile) -> bytes
        # organ.glb, tumor.glb o volume.npy; StorageObjectNotFoundError, StorageError
    def read_lesion_mesh(self, study_code: str, lesion_number: int) -> bytes
        # la malla de la fila n (desde 1, en orden de guardado); StorageObjectNotFoundError
```

`save_result` sube los cinco archivos y una malla por lesion (`lesion_meshes`, en el orden del
resumen). Después, en una sola unidad de trabajo, crea una fila de `lesion` por cada elemento
de `summary["regions"]` (FR-047a), cada una con su propio `mesh_path` y el organo del estudio
(004). Cambio que rompe compatibilidad: `lesion_meshes` es obligatorio.

`read_file` y `read_lesion_mesh` no comprueban el estado del estudio: eso lo hace el servicio. Desde la funcionalidad 002
(research.md R7) **ya no** registra el modelo ni marca las etapas 3 y 4: lo hace la tubería con
`ProcessingProgressStore.complete_stage`, y la etapa 4 se cierra después de guardar. Así el
resultado aparece entero o no aparece.

`get_result` nunca falla por falta de resultado (FR-049):

- Estudio inexistente: lanza `StudyNotFoundError`.
- Estudio existente con las etapas 3 y 4 en `completed`: devuelve las cinco rutas, la del
  volumen (`volume_path`, desde 004) y sus lesiones.
- Estudio existente en cualquier otro caso: devuelve un `StoredResult` vacío, con las cinco rutas
  en `None` y `lesions == []`. No lanza error. No consulta el bucket.
