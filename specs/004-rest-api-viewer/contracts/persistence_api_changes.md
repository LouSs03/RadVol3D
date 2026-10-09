# Contrato: cambios en la persistencia

Amplía [specs/001-persistence-schema-migration/contracts/persistence_api.md](../../001-persistence-schema-migration/contracts/persistence_api.md)
y [specs/002-services-pipeline/contracts/persistence_api_changes.md](../../002-services-pipeline/contracts/persistence_api_changes.md).
Ese contrato se reescribe en el mismo pull request para que refleje esto.

## Esquema

`docs/database/schema/002_add_lesion_organ.sql` (research.md R11): `lesion.organ`
`varchar(32) not null`, con `check (organ in ('lung', 'liver'))`, llenado para las filas que
ya existan. Se aplica sobre la 001 en la base real y en la de prueba.

## storage_layout

```python
def lesion_mesh_path(study_code: str, lesion_number: int) -> str
    # "<study_code>/meshes/lesion_<NNN>.glb", lesion_number >= 1.
    # InvalidStudyIdError; InvalidLesionError si lesion_number < 1 o no es int.
```

La nota "ruta reservada `lesion_<region_id>.glb`" se reemplaza por esta función.

## ObjectStorage

```python
def list_names(self, folder: str) -> list[str]
    # Nombres de los archivos directamente dentro de la carpeta. [] si no existe.
    # StorageError si el bucket falla.
```

## StudyMetadataStore

```python
def create_study(
    study_code: str, organ: OrganName | str, patient: PatientDetails | None = None
) -> Study
    # Paciente (find_or_create), estudio pending y cuatro etapas waiting, en una transacción.
    # No sube nada. DuplicateStudyError, InvalidStudyIdError, UnknownOrganError,
    # InvalidPatientDataError

def add_projections(study_code: str, projections: list[ProjectionUpload]) -> Study
    # Una transacción: lock_status; exige pending y cero proyecciones
    # (InvalidStudyStateError); valida los cuatro ángulos; sube y registra.
    # Si algo falla, nada queda registrado.

def claim_for_processing(study_code: str) -> None
    # Una transacción: lock_status; exige pending y cuatro proyecciones; pasa a processing.
    # InvalidStudyStateError, StudyNotFoundError

def load_projections(study_code: str) -> dict[int, np.ndarray]
    # Baja los cuatro .npy del bucket. StorageObjectNotFoundError, StorageError

def register_study(...)   # misma firma; ahora create_study + add_projections
def delete_study(...)     # misma firma; borra también los lesion_*.glb de <code>/meshes/
```

## ProcessingProgressStore

```python
def fail_interrupted_studies() -> list[str]
    # Por cada estudio en processing, una transacción: la etapa running (o la primera
    # waiting) -> failed, las siguientes -> skipped, el estudio -> failed. Devuelve códigos.
```

## ResultStore

```python
def save_result(
    study_code: str,
    mask: np.ndarray,
    probability: np.ndarray,
    summary: Mapping[str, Any],
    organ_mesh: bytes,
    tumor_mesh: bytes,
    lesion_meshes: Sequence[bytes],       # nuevo
) -> StoredResult
    # PersistenceError si len(lesion_meshes) != número de lesiones del resumen (antes de
    # subir nada). Sube lesion_<NNN>.glb por cada una; cada fila de lesion guarda su
    # propia ruta en mesh_path y el órgano del estudio en organ.

def get_result(study_code: str) -> StoredResult      # + volume_path; lesiones con organ

def read_file(study_code: str, file: ResultFile) -> bytes
    # Baja organ.glb, tumor.glb o volume.npy (este último, los bytes del .npy tal cual).

def read_lesion_mesh(study_code: str, lesion_number: int) -> bytes
    # Lee el mesh_path de la fila n (orden por lesion_id) y baja el archivo.
    # StorageObjectNotFoundError si n está fuera de rango o el archivo falta.
```

`read_file` y `read_lesion_mesh` no comprueban el estado: eso lo hace el servicio.

## LesionRepository

- `add_many`: el insert toma `organ` del estudio (`insert ... select ... join organ`).
  `Lesion.organ` se ignora al guardar.
- `list_by_study`: devuelve también `organ`.
