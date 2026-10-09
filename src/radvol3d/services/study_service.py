"""Caso de uso: procesar, consultar y borrar estudios.

Es lo unico que ve la presentacion. Recibe todas sus dependencias por el
constructor (los almacenes de la persistencia, la fabrica, la tuberia y el
cargador) y no construye ninguna: las arma service_container al arrancar.

Hay dos formas de procesar un estudio:

- process_study: todo en una llamada (registro, tuberia y cierre). Es la de 002.
- El flujo en tres pasos de la API (funcionalidad 004): create_study,
  add_projections y start_processing dentro de cada peticion, y run_processing en una
  tarea en segundo plano, despues de responder.

Las dos corren la tuberia y cierran el estudio con el mismo codigo (_run_pipeline).
"""

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from radvol3d.domain.entities import PatientDetails, StoredResult, Study
from radvol3d.domain.enums import OrganName, ResultFile, StageNumber, StudyStatus
from radvol3d.domain.exceptions import InvalidStudyStateError, StageFailedError
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from radvol3d.services.pipeline.persistence_progress import PersistenceProgress
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.strategy_factory import StrategyFactory, StrategySet

logger = logging.getLogger(__name__)


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

        self._metadata_store.register_study(
            request.study_code,
            request.organ,
            self._uploads(request.projections, by_angle),
            request.patient,
        )
        self._progress_store.start_processing(request.study_code)
        self._run_pipeline(request.study_code, by_angle, strategies, started)
        return self._metadata_store.get_study(request.study_code)

    def create_study(
        self,
        study_code: str,
        organ: OrganName,
        patient: PatientDetails | None = None,
    ) -> Study:
        """Crea el estudio en pending, sin proyecciones.

        Antes comprueba que haya modelo para el organo: un estudio de un organo que no
        se puede procesar no se crea (ModelNotAvailableError).
        """
        self._factory.strategies_for(organ)
        return self._metadata_store.create_study(study_code, organ, patient)

    def add_projections(self, study_code: str, files: Sequence[ProjectionFile]) -> Study:
        """Valida las cuatro proyecciones y las guarda en un estudio en pending.

        Si un archivo es invalido, lanza InvalidProjectionError (nombra el angulo) y no
        guarda ninguno.
        """
        by_angle = self._loader.parse(files)
        return self._metadata_store.add_projections(study_code, self._uploads(files, by_angle))

    def start_processing(self, study_code: str) -> Study:
        """Reclama el estudio para procesarlo: pasa de pending a processing.

        Comprueba primero que haya modelo para su organo; si no, lanza
        ModelNotAvailableError y el estudio sigue en pending. La tuberia la corre
        despues run_processing, en segundo plano.
        """
        study = self._metadata_store.get_study(study_code)
        self._factory.strategies_for(study.organ)
        self._metadata_store.claim_for_processing(study_code)
        return self._metadata_store.get_study(study_code)

    def run_processing(self, study_code: str) -> None:
        """Corre la tuberia de un estudio ya reclamado. Nunca lanza.

        Es la tarea en segundo plano de la API: nadie espera su resultado, asi que
        todo fallo queda en el estado del estudio y en el registro (con el codigo y
        el tipo del error, nunca su texto).

        - Si falla una etapa, la tuberia ya la registro como failed.
        - Si falla algo antes de la tuberia (leer el estudio o bajar las
          proyecciones), el estudio falla desde la etapa 1.
        - Si falla el cierre del estudio, despues de la etapa 4, falla desde la 4.
        """
        started = time.perf_counter()
        failed_stage = StageNumber.PREPROCESSING
        try:
            study = self._metadata_store.get_study(study_code)
            strategies = self._factory.strategies_for(study.organ)
            by_angle = self._metadata_store.load_projections(study_code)
            failed_stage = StageNumber.MESHING
            self._run_pipeline(study_code, by_angle, strategies, started)
        except StageFailedError:
            return
        except Exception as error:  # noqa: BLE001 - la tarea en segundo plano no lanza
            logger.error(
                "No se pudo procesar el estudio %s (%s)", study_code, type(error).__name__
            )
            self._record_failure(study_code, failed_stage)

    def get_completed_result(self, study_code: str) -> StoredResult:
        """Devuelve el resultado de un estudio completed, con sus lesiones y sus rutas.

        Lanza InvalidStudyStateError si el estudio no termino: a diferencia de
        get_result, aqui un resultado vacio no tiene sentido.
        """
        self._require_completed(study_code)
        return self._result_store.get_result(study_code)

    def read_result_file(self, study_code: str, file: ResultFile) -> bytes:
        """Bytes de la malla del organo, la del tumor o el volumen de un estudio completed."""
        self._require_completed(study_code)
        return self._result_store.read_file(study_code, file)

    def read_lesion_mesh(self, study_code: str, lesion_number: int) -> bytes:
        """Bytes de la malla de la lesion numero lesion_number (desde 1)."""
        self._require_completed(study_code)
        return self._result_store.read_lesion_mesh(study_code, lesion_number)

    def recover_interrupted_studies(self) -> list[str]:
        """Pasa a failed los estudios que quedaron en processing al apagarse el servicio."""
        return self._progress_store.fail_interrupted_studies()

    def get_study(self, study_code: str) -> Study:
        """Devuelve el estudio con su paciente, proyecciones, etapas y lesiones."""
        return self._metadata_store.get_study(study_code)

    def get_result(self, study_code: str) -> StoredResult:
        """Devuelve el resultado; vacio si el estudio todavia no termino."""
        return self._result_store.get_result(study_code)

    def list_studies(self) -> list[Study]:
        """Devuelve los estudios del mas reciente al mas antiguo, sin datos anidados."""
        return self._metadata_store.list_studies()

    def _run_pipeline(
        self,
        study_code: str,
        by_angle: Mapping[int, object],
        strategies: StrategySet,
        started: float,
    ) -> None:
        """Corre las cuatro etapas y cierra el estudio en completed."""
        progress = PersistenceProgress(
            self._progress_store, self._metadata_store, self._result_store
        )
        data = self._pipeline.run(study_code, by_angle, strategies, progress)

        segmentation = strategies.segmentation
        self._progress_store.complete_study(
            study_code,
            segmentation.model_name,
            segmentation.model_version,
            int(data.volume.shape[0]),
            time.perf_counter() - started,
        )

    def _require_completed(self, study_code: str) -> None:
        """Lanza InvalidStudyStateError si el estudio no esta en completed."""
        status = self._metadata_store.get_study(study_code).status
        if status is not StudyStatus.COMPLETED:
            raise InvalidStudyStateError(
                f"El estudio '{study_code}' esta en {status.value}: el resultado solo "
                "existe cuando el estudio termina (completed)."
            )

    def _record_failure(self, study_code: str, stage: StageNumber) -> None:
        """Marca el estudio como fallido. Si eso tambien falla, solo queda en el registro."""
        try:
            self._progress_store.fail_from_stage(study_code, stage)
        except Exception as error:  # noqa: BLE001 - el primer error es el que importa
            logger.error(
                "No se pudo registrar el fallo del estudio %s (%s)",
                study_code,
                type(error).__name__,
            )

    @staticmethod
    def _uploads(
        files: Sequence[ProjectionFile], by_angle: Mapping[int, object]
    ) -> list[ProjectionUpload]:
        """Una ProjectionUpload por angulo, con el nombre original del archivo."""
        names = {p.angle_degrees: p.original_name for p in files}
        return [
            ProjectionUpload(angle, array, names.get(angle)) for angle, array in by_angle.items()
        ]

    def delete_study(self, study_code: str) -> None:
        """Borra el estudio con sus filas y sus archivos; rechaza uno en processing."""
        self._metadata_store.delete_study(study_code)
