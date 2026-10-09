# Contrato: lo que `services/` ofrece a `api/` y a `main.py`

Es un contrato interno. Las firmas dicen qué entra, qué sale y qué error se lanza; no son la
implementación. Las entidades vienen de `domain/entities.py` y los errores, de
`domain/exceptions.py`.

Reglas comunes:

- Ningún método devuelve tipos de la persistencia, de psycopg ni de torch.
- Ningún mensaje de error contiene nombre, apellido ni DNI del paciente, ni el contenido de
  un archivo.
- Importar cualquier módulo de este contrato no importa `torch`.

## service_container (lo usa solo `main.py`)

```python
def build_service_container(settings: Settings, model_settings: ModelSettings) -> ServiceContainer
    # ConfigurationError, DatabaseUnavailableError (la base es obligatoria)
    # Un modelo que no carga NO lanza: queda no disponible (FR-019)

class ServiceContainer:
    study_service: StudyService
    def model_status(self) -> Mapping[str, bool]   # {"reconstruction:en1": True, "segmentation:lung": False}
    def close(self) -> None                        # cierra la base; idempotente
```

Uso en el `lifespan` (pseudocódigo):

```text
container = build_service_container(get_settings(), get_model_settings())
app.state.services = container
yield
container.close()
```

## api/dependencies

```python
def get_study_service(request: Request) -> StudyService   # lee request.app.state.services
```

`get_processing_pipeline` se elimina, junto con sus usos en los routers esqueleto. La
presentación habla solo con `StudyService`.

## StudyService

```python
@dataclass(frozen=True)
class ProjectionFile:
    angle_degrees: int
    content: bytes                  # bytes de un .npy en el convenio de TA-2
    original_name: str | None = None

@dataclass(frozen=True)
class StudyRequest:
    study_code: str
    organ: OrganName
    projections: list[ProjectionFile]
    patient: PatientDetails | None = None

class StudyService:
    def process_study(self, request: StudyRequest) -> Study
        # Antes de crear nada: InvalidStudyIdError, InvalidProjectionError, ModelNotAvailableError
        # Al registrar:        DuplicateStudyError, InvalidPatientDataError, StorageError,
        #                      DatabaseUnavailableError
        # Durante la tubería:  StageFailedError (el estudio queda en failed)
    def get_study(self, study_code: str) -> Study                 # StudyNotFoundError
    def list_studies(self) -> list[Study]
    def get_result(self, study_code: str) -> StoredResult        # StudyNotFoundError; vacío si no terminó
    def delete_study(self, study_code: str) -> None
        # StudyNotFoundError, StudyInProgressError, StorageError, DatabaseUnavailableError
```

`process_study` sigue este orden:

1. admisión de las proyecciones;
2. elección de estrategias;
3. `register_study`;
4. `start_processing`;
5. la tubería;
6. `complete_study`;
7. devuelve `get_study`.

`process_study` es síncrono. Dos llamadas en hilos distintos no comparten datos intermedios.

## Tubería

```python
class ProcessingPipeline:
    def run(self, study_code: str, projections_by_angle: Mapping[int, ndarray],
            strategies: StrategySet, progress: PipelineProgress) -> PipelineData
        # StageFailedError; antes de lanzarlo llama a progress.stage_failed(n)

class PipelineProgress(Protocol):
    def stage_started(self, study_code: str, stage: StageNumber) -> None
    def stage_completed(self, study_code: str, stage: StageNumber,
                        model_name: str | None = None, model_version: str | None = None) -> None
    def stage_failed(self, study_code: str, stage: StageNumber) -> None
    def save_volume(self, study_code: str, volume: ndarray) -> None
    def save_result(self, study_code: str, segmentation: SegmentationResult,
                    meshes: MeshSet) -> None
```

## Estrategias

```python
class ReconstructionStrategy(ABC):
    def reconstruct(self, projections: ndarray) -> ndarray
        # (4,128,128) float32, integrales de línea de TA-2  ->  (128,128,128) float32 en [0,1]
    model_name: str      # propiedad
    model_version: str   # propiedad

class SegmentationStrategy(ABC):
    def segment(self, volume: ndarray, study_code: str) -> SegmentationResult
        # volumen (N,N,N) float32 en [0,1]; mask uint8 {0,1}, probability float32 [0,1],
        # summary con las claves de data-model.md §4
    model_name: str
    model_version: str

class MeshingStrategy(ABC):
    def build_meshes(self, volume: ndarray, mask: ndarray) -> MeshSet
        # dos .glb válidos; sin superficie -> .glb válido sin geometría (no lanza)
```

Las estrategias reales se construyen con `from_weights(path)`, que importa torch de forma
perezosa. Cada instancia se puede usar desde varios hilos, porque serializa su inferencia
con un candado.

## Fábrica

```python
class StrategyFactory:
    def __init__(self,
                 reconstruction_builders: Mapping[str, Callable[[], ReconstructionStrategy]],
                 segmentation_builders: Mapping[OrganName, Callable[[], SegmentationStrategy]],
                 meshing_builder: Callable[[], MeshingStrategy],
                 reconstruction_key: str) -> None
    def preload(self) -> None              # construye cada estrategia una vez; nunca lanza
    def strategies_for(self, organ: OrganName) -> StrategySet   # ModelNotAvailableError
    def availability(self) -> Mapping[str, bool]
```

Los mensajes de `ModelNotAvailableError` son estos:

- clave de reconstrucción desconocida: "No hay estrategia de reconstrucción '<clave>'."
- órgano sin modelo (`liver`): "No hay modelo de segmentación de hígado todavía."
- modelo que no cargó: "El modelo <nombre> no está disponible en este servidor."

## Formato de las mallas

- Formato: glTF binario (`.glb`), con una sola malla triangular por archivo, sin materiales
  ni texturas.
- Unidades: milímetros, 2,5 mm por vóxel.
- Ejes: los de numpy en el orden (0, 1, 2), con origen en el centro del volumen. El órgano y
  el tumor comparten el sistema de coordenadas, así que se superponen sin transformar.
- Malla del tumor: a resolución completa. Malla del órgano: con paso de 2 vóxeles (R19).
- Sin superficie: un `.glb` válido sin vértices (172 bytes con trimesh 5.1).
