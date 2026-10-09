"""Caso de uso: procesar, consultar y borrar estudios.

Es lo unico que ve la presentacion. Recibe todas sus dependencias por el
constructor (los almacenes de la persistencia, la fabrica, la tuberia y el
cargador) y no construye ninguna: las arma service_container al arrancar.
"""

import time
from dataclasses import dataclass, field

from radvol3d.domain.entities import PatientDetails, StoredResult, Study
from radvol3d.domain.enums import OrganName
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from radvol3d.services.pipeline.persistence_progress import PersistenceProgress
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.strategy_factory import StrategyFactory


@dataclass(frozen=True)
class StudyRequest:
    """Lo que hace falta para procesar un estudio nuevo."""

    study_code: str
    organ: OrganName
    projections: list[ProjectionFile] = field(default_factory=list)
    patient: PatientDetails | None = None


class StudyService:
    """Coordina la tuberia con la persistencia."""

    def __init__(
        self,
        metadata_store: StudyMetadataStore,
        result_store: ResultStore,
        progress_store: ProcessingProgressStore,
        factory: StrategyFactory,
        pipeline: ProcessingPipeline,
        loader: ProjectionLoader,
    ) -> None:
        self._metadata_store = metadata_store
        self._result_store = result_store
        self._progress_store = progress_store
        self._factory = factory
        self._pipeline = pipeline
        self._loader = loader

    def process_study(self, request: StudyRequest) -> Study:
        """Registra el estudio, lo pasa por las cuatro etapas y lo devuelve terminado.

        Antes de crear nada se leen las proyecciones y se eligen las estrategias: una
        entrada invalida o un modelo no disponible fallan sin dejar un estudio a medias.
        """
        started = time.perf_counter()
        by_angle = self._loader.parse(request.projections)
        strategies = self._factory.strategies_for(request.organ)

        names = {p.angle_degrees: p.original_name for p in request.projections}
        uploads = [
            ProjectionUpload(angle, array, names.get(angle))
            for angle, array in by_angle.items()
        ]
        self._metadata_store.register_study(
            request.study_code, request.organ, uploads, request.patient
        )
        self._progress_store.start_processing(request.study_code)

        progress = PersistenceProgress(
            self._progress_store, self._metadata_store, self._result_store
        )
        data = self._pipeline.run(request.study_code, by_angle, strategies, progress)

        segmentation = strategies.segmentation
        self._progress_store.complete_study(
            request.study_code,
            segmentation.model_name,
            segmentation.model_version,
            int(data.volume.shape[0]),
            time.perf_counter() - started,
        )
        return self._metadata_store.get_study(request.study_code)

    def get_study(self, study_code: str) -> Study:
        """Devuelve el estudio con su paciente, proyecciones, etapas y lesiones."""
        return self._metadata_store.get_study(study_code)

    def get_result(self, study_code: str) -> StoredResult:
        """Devuelve el resultado; vacio si el estudio todavia no termino."""
        return self._result_store.get_result(study_code)

    def list_studies(self) -> list[Study]:
        """Devuelve los estudios del mas reciente al mas antiguo, sin datos anidados."""
        return self._metadata_store.list_studies()

    def delete_study(self, study_code: str) -> None:
        """Borra el estudio con sus filas y sus archivos; rechaza uno en processing."""
        self._metadata_store.delete_study(study_code)
