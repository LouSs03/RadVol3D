# Contrato: cambios en lo que `persistence/` ofrece a `services/`

Este documento complementa a `specs/001-persistence-schema-migration/contracts/persistence_api.md`.
Donde dice "cambia", reemplaza lo que dice ese documento. Las reglas comunes de ese contrato
siguen vigentes. Al implementar, el contrato 001 se actualiza para que quede un solo documento
vigente.

## settings (nuevo)

```python
class ModelSettings:
    model_bucket: str | None
    en1_weights_object: str | None
    en2_weights_object: str | None
    model_cache_dir: Path            # por omisión .cache/models
    reconstruction_strategy: str     # por omisión "en1"

def get_model_settings() -> ModelSettings    # nunca lanza por un campo faltante
```

## object_storage (agrega)

```python
class ObjectStorage:
    @classmethod
    def from_settings(cls, settings: Settings, bucket: str | None = None) -> "ObjectStorage"
        # bucket=None mantiene el comportamiento actual (settings.storage_bucket)
    def remove_many(self, paths: Sequence[str]) -> None     # StorageError
        # Una ruta que no existe no es un error. Lista vacía: no hace nada.
```

- **Concurrencia.** Una instancia serializa sus llamadas al bucket con un candado propio. El
  cliente HTTP de Supabase no admite dos peticiones a la vez desde hilos distintos
  (research.md R13).

## model_weights_store (nuevo)

```python
class ModelWeightsStore:
    def __init__(self, storage: ObjectStorage, cache_dir: Path) -> None
    def fetch(self, object_path: str) -> Path
        # StorageObjectNotFoundError, StorageError
        # Si ya está en la caché, no baja nada. Escribe en un temporal y lo renombra.
```

## processing_progress_store (nuevo)

Cada método es una unidad de trabajo completa.

```python
class ProcessingProgressStore:
    def __init__(self, database: Database) -> None
    def start_processing(self, study_code: str) -> None                 # StudyNotFoundError
    def start_stage(self, study_code: str, stage: StageNumber) -> None  # StudyNotFoundError
    def complete_stage(self, study_code: str, stage: StageNumber,
                       model_name: str | None = None, model_version: str | None = None) -> None
        # StudyNotFoundError. Si se da un modelo, get_or_create antes de enlazarlo.
    def fail_from_stage(self, study_code: str, stage: StageNumber) -> None
        # etapa -> failed, etapas siguientes -> skipped, estudio -> failed; StudyNotFoundError
    def complete_study(self, study_code: str, model_name: str, model_version: str,
                       grid_size: int, total_time_sec: float) -> None   # StudyNotFoundError
    def register_model(self, model_name: str, version: str,
                       trained_on: date | None = None, description: str | None = None) -> Model
```

## study_metadata_store (agrega)

```python
class StudyMetadataStore:
    def delete_study(self, study_code: str) -> None
        # InvalidStudyIdError, StudyNotFoundError, StudyInProgressError, StorageError,
        # DatabaseUnavailableError
```

`delete_study` hace todo en una transacción, en este orden:

1. `select ... for update` sobre el estudio;
2. comprueba su estado;
3. `delete from study` (lo que cuelga de él cae en cascada);
4. `remove_many` de las diez rutas de `storage_layout`;
5. confirma.

Si el bucket falla, se revierte y el estudio sigue completo. Los pacientes y los modelos no se
borran.

## repositories (agrega)

```python
class StudyRepository:
    def lock_status(self, study_code: str) -> StudyStatus   # select ... for update; StudyNotFoundError
    def delete(self, study_code: str) -> None                # StudyNotFoundError
```

## result_store (cambia)

```python
class ResultStore:
    def save_result(self, study_code: str, mask: ndarray, probability: ndarray,
                    summary: Mapping[str, Any], organ_mesh: bytes,
                    tumor_mesh: bytes) -> StoredResult
        # InvalidLesionError, StudyNotFoundError, StorageError, DatabaseUnavailableError
```

- **Cambia:** `save_result` sube los cinco archivos e inserta las lesiones en una unidad de
  trabajo. **Ya no** marca las etapas 3 y 4 ni registra el modelo de la etapa 3. Ahora lo hace
  la tubería, con `ProcessingProgressStore.complete_stage` (research.md R7).
- **Sigue igual:** `get_result` devuelve resultado solo si las etapas 3 y 4 están en
  `completed`. Como la etapa 4 se cierra después de `save_result`, el resultado aparece entero
  o no aparece.
- **Sigue igual:** el resumen se valida y debe traer `model_name` y `model_version`.
