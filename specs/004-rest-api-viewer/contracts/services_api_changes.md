# Contrato: cambios en lo que `services/` ofrece a `api/` y a `main.py`

Amplía [specs/002-services-pipeline/contracts/services_api.md](../../002-services-pipeline/contracts/services_api.md).
Lo que no aparece aquí no cambia. Las reglas comunes de ese contrato siguen valiendo: ningún
método devuelve tipos de la persistencia ni de torch, y ningún mensaje trae datos del
paciente.

## StudyService: métodos nuevos

```python
def create_study(
    study_code: str, organ: OrganName, patient: PatientDetails | None = None
) -> Study
    # Comprueba primero que haya modelo para el órgano (factory.strategies_for).
    # Study en pending, sin proyecciones, con sus cuatro etapas en waiting.
    # InvalidStudyIdError, UnknownOrganError, InvalidPatientDataError,
    # DuplicateStudyError, ModelNotAvailableError

def add_projections(study_code: str, files: Sequence[ProjectionFile]) -> Study
    # ProjectionLoader.parse (sin cambios) y luego persistencia.add_projections.
    # InvalidProjectionError (nombra el ángulo), InvalidStudyStateError, StudyNotFoundError

def start_processing(study_code: str) -> None
    # claim_for_processing(study_code, factory.strategies_for): pending + 4 proyecciones
    # -> processing, con bloqueo de fila; el modelo del organo se comprueba dentro de la
    # misma transaccion (si falta, ModelNotAvailableError y el estudio sigue en pending).
    # No lee el estudio aparte ni lo devuelve: POST /process debe responder en menos de
    # 1 s (SC-002), y con la base a ~0,13 s por consulta cada lectura cuenta.
    # InvalidStudyStateError, StudyNotFoundError, ModelNotAvailableError

def run_processing(study_code: str) -> None
    # Para la tarea en segundo plano. NUNCA lanza.
    # load_projections -> pipeline.run -> complete_study.
    # Un fallo de la tubería ya queda registrado por la tubería (002).
    # Un fallo antes de la tubería: fail_from_stage(PREPROCESSING).
    # Registra código + tipo de error, nunca el texto.

def get_completed_result(study_code: str) -> StoredResult
    # InvalidStudyStateError si el estudio no está completed. StudyNotFoundError.
    # Cada Lesion trae organ y su propio mesh_path.

def read_result_file(study_code: str, file: ResultFile) -> bytes
    # Exige completed. InvalidStudyStateError, StudyNotFoundError,
    # StorageObjectNotFoundError

def read_lesion_mesh(study_code: str, lesion_number: int) -> bytes
    # lesion_number desde 1, en el orden de get_completed_result().lesions.
    # Fuera de rango: StorageObjectNotFoundError. Exige completed.

def recover_interrupted_studies() -> list[str]
    # Pasa a failed los estudios en processing (research.md R5). Devuelve sus códigos.
```

## StudyService: métodos que cambian

```python
def process_study(request: StudyRequest) -> Study
    # Misma firma, mismo resultado y mismo orden de llamadas que en 002: sigue usando
    # register_study (una sola transacción para registrar todo). Comparte con
    # run_processing la ejecución de la tubería y el cierre del estudio
    # (_run_pipeline). Relanza StageFailedError si la tubería falló.
    # Se decidió no componerlo con create_study + add_projections + start_processing:
    # serían tres transacciones para lo que hoy es una, sin ganar nada.
```

`get_study`, `get_result`, `list_studies` y `delete_study` no cambian de firma. `delete_study`
borra también las mallas por lesión (persistencia).

## service_container

`build_service_container` llama a `study_service.recover_interrupted_studies()` una vez,
después de armar el servicio, y registra cuántos estudios recuperó.

## Meshing

```python
@dataclass(frozen=True)
class MeshSet:
    organ: bytes
    tumor: bytes
    lesions: tuple[bytes, ...] = ()     # nuevo: un .glb por región, en el orden del resumen

class MeshingStrategy(ABC):
    def build_meshes(
        self, volume: Any, mask: Any, regions: Sequence[Mapping[str, Any]]
    ) -> MeshSet
        # regions: summary["regions"] con has_lesion verdadero; cada una con voxels y
        # centroid_voxel. len(MeshSet.lesions) == len(regions).

# services/meshing/lesion_regions.py
def split_lesion_masks(mask: ndarray, regions: Sequence[Mapping[str, Any]]) -> list[ndarray]
    # ValueError si una región no tiene su componente conexa.
```

`MeshingFilter` pasa las regiones del resumen. `PersistenceProgress.save_result` pasa
`meshes.lesions` a `ResultStore.save_result`. Los dobles de `tests/fixtures/` se actualizan:
`FakeSegmentationStrategy` agrega `voxels` y `centroid_voxel` a su región, y
`FakeMeshingStrategy` devuelve una `.glb` falsa por región.

## api/dependencies

Sin cambios: `get_study_service(request)`.
