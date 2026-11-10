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

Modo de una radiografia (guia de Lourdes, 7 de noviembre de 2026): el mismo flujo en
tres pasos, con add_radiograph en lugar de add_projections. start_processing revisa
antes que el servicio externo responda (si no, el estudio sigue en pending y el modo
se informa como no disponible) y run_processing corre la tuberia de una radiografia.
El modo de cuatro proyecciones no cambia.
"""

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial

from radvol3d.domain.entities import PatientDetails, StoredResult, Study, StudyHistoryPage
from radvol3d.domain.enums import (
    InputMode,
    OrganName,
    RemoteJobState,
    ResultFile,
    StageNumber,
    StudyStatus,
)
from radvol3d.domain.exceptions import (
    InvalidRadiographError,
    InvalidStudyStateError,
    ModelNotAvailableError,
    ReconstructionServiceUnavailableError,
    StageFailedError,
)
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from radvol3d.services.pipeline.persistence_progress import PersistenceProgress
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.pipeline.radiograph_check import validate_radiograph
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard
from radvol3d.services.strategy_factory import (
    RADIOGRAPH_UNAVAILABLE,
    RadiographStrategySet,
    StrategyFactory,
    StrategySet,
)

# Los organos que admite el modo de una radiografia: el modelo AXON se entreno con
# radiografias de torax frontales (PA).
RADIOGRAPH_ORGANS = frozenset({OrganName.LUNG})

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
        board: RemoteJobBoard | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._result_store = result_store
        self._progress_store = progress_store
        self._factory = factory
        self._pipeline = pipeline
        self._loader = loader
        self._board = board or RemoteJobBoard()

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
        input_mode: InputMode = InputMode.PROJECTIONS,
    ) -> Study:
        """Crea el estudio en pending, sin proyecciones ni radiografia.

        No pide modelo para el organo: un estudio de higado se registra aunque todavia
        no se pueda procesar (HU-2.2). El modelo se comprueba en start_processing, que
        deja el estudio en pending si no lo hay.

        El modo de una radiografia solo admite pulmon (InvalidRadiographError si no).
        Se crea aunque el servicio externo este apagado: eso se revisa al procesar.
        """
        mode = InputMode(input_mode)
        if mode is InputMode.RADIOGRAPH and OrganName(organ) not in RADIOGRAPH_ORGANS:
            raise InvalidRadiographError(
                "El modo de una radiografía solo admite pulmón (radiografía de tórax)."
            )
        if mode is InputMode.PROJECTIONS:
            # La misma llamada de siempre: el modo de cuatro proyecciones no cambia.
            return self._metadata_store.create_study(study_code, organ, patient)
        return self._metadata_store.create_study(study_code, organ, patient, input_mode=mode)

    def add_radiograph(
        self, study_code: str, content: bytes, filename: str | None = None
    ) -> Study:
        """Valida el DICOM y lo guarda en un estudio de una radiografia en pending.

        Si el archivo no es un DICOM aceptable, lanza InvalidRadiographError (o
        RadiographTooLargeError) y no guarda nada. El nombre del archivo solo sirve para
        revisar la extension: no se guarda.
        """
        data = validate_radiograph(content, filename)
        return self._metadata_store.add_radiograph(study_code, data)

    def radiograph_mode_available(self) -> bool:
        """True si el modo de una radiografia esta configurado y el servicio responde.

        Revisa /health con el tiempo de espera corto del cliente (5 s). Nunca lanza.
        """
        try:
            strategies = self._factory.radiograph_strategies_for(OrganName.LUNG)
        except ModelNotAvailableError:
            return False
        try:
            return bool(strategies.reconstruction.is_available())
        except Exception as error:  # noqa: BLE001 - la consulta nunca tumba la pagina
            logger.warning(
                "No se pudo consultar el servicio de reconstruccion (%s)", type(error).__name__
            )
            return False

    def remote_state(self, study_code: str) -> RemoteJobState | None:
        """En que paso va el trabajo externo del estudio (en cola, reconstruyendo)."""
        return self._board.get(study_code)

    def add_projections(self, study_code: str, files: Sequence[ProjectionFile]) -> Study:
        """Valida las cuatro proyecciones y las guarda en un estudio en pending.

        Si un archivo es invalido, lanza InvalidProjectionError (nombra el angulo) y no
        guarda ninguno.
        """
        by_angle = self._loader.parse(files)
        return self._metadata_store.add_projections(study_code, self._uploads(files, by_angle))

    def start_processing(self, study_code: str, reconstruction_key: str | None = None) -> None:
        """Reclama el estudio para procesarlo: pasa de pending a processing.

        Dentro de la misma transaccion comprueba que haya modelo para su organo; si no,
        lanza ModelNotAvailableError y el estudio sigue en pending. La tuberia la corre
        despues run_processing, en segundo plano.

        Corre dentro de POST /process, que debe responder en menos de un segundo
        (SC-002): por eso no lee el estudio aparte ni lo vuelve a leer al final.

        En el modo de una radiografia, check_organ revisa ademas que el servicio externo
        responda (/health, 5 s como maximo); si no, lanza
        ReconstructionServiceUnavailableError y el estudio sigue en pending.
        """
        check = partial(self._check_strategies, reconstruction_key=reconstruction_key)
        self._metadata_store.claim_for_processing(study_code, check)

    def _check_strategies(
        self,
        organ: OrganName,
        input_mode: InputMode | None = None,
        reconstruction_key: str | None = None,
    ) -> StrategySet | None:
        """Lo que check_organ comprueba antes de reclamar el estudio.

        reconstruction_key elige el modelo de un estudio de 4 proyecciones; el modo de
        una radiografia siempre usa el servicio externo, asi que ahi no se usa.
        """
        if input_mode is not InputMode.RADIOGRAPH:
            return self._factory.strategies_for(organ, reconstruction_key)
        strategies = self._factory.radiograph_strategies_for(organ)
        if not strategies.reconstruction.is_available():
            raise ReconstructionServiceUnavailableError(RADIOGRAPH_UNAVAILABLE)
        return None

    def run_processing(self, study_code: str, reconstruction_key: str | None = None) -> None:
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
            if study.input_mode is InputMode.RADIOGRAPH:
                radiograph_strategies = self._factory.radiograph_strategies_for(study.organ)
                radiograph = self._metadata_store.load_radiograph(study_code)
                failed_stage = StageNumber.MESHING
                self._run_radiograph_pipeline(
                    study_code, radiograph, radiograph_strategies, started
                )
                return
            strategies = self._factory.strategies_for(study.organ, reconstruction_key)
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

    def list_history(
        self, limit: int = 50, offset: int = 0, national_id: str | None = None
    ) -> StudyHistoryPage:
        """Una pagina del historial; con national_id, solo los estudios de ese DNI.

        Solo un estudio completed tiene resultado (research.md R4 de 005): en los
        demas, el numero de lesiones y el volumen quedan en None aunque la base tenga
        filas de lesion, como las de un estudio que fallo despues de guardarlas.
        """
        page = self._metadata_store.list_history(limit, offset, national_id)
        entries = [
            entry
            if entry.status is StudyStatus.COMPLETED
            else replace(entry, lesion_count=None, total_lesion_volume_mm3=None)
            for entry in page.entries
        ]
        return replace(page, entries=entries)

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

    def _run_radiograph_pipeline(
        self,
        study_code: str,
        radiograph: bytes,
        strategies: RadiographStrategySet,
        started: float,
    ) -> None:
        """Corre las cuatro etapas de una radiografia y cierra el estudio en completed.

        El estudio queda enlazado al modelo de reconstruccion (AXON): la segmentacion
        todavia es el gancho pendiente y no es un modelo de verdad.
        """
        progress = PersistenceProgress(
            self._progress_store, self._metadata_store, self._result_store
        )
        data = self._pipeline.run_radiograph(study_code, radiograph, strategies, progress)
        reconstruction = strategies.reconstruction
        self._progress_store.complete_study(
            study_code,
            reconstruction.model_name,
            reconstruction.model_version,
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
