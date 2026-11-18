"""Las etapas de un estudio de una radiografia reconstruido con X2CT-GAN.

Es un camino propio, separado de ProcessingPipeline (modo de cuatro proyecciones y
modo de una radiografia con AXON), que no cambia. Usa las mismas cuatro filas de
processing_stage de todo estudio, con este significado:

    1 preprocesamiento -> carga y validacion del DICOM
    2 reconstruccion   -> X2CT-GAN (incluye su preprocesamiento a 128 x 128) y la
                          validacion frontal (services/reconstruction/frontal_validation.py)
    3 segmentacion     -> skipped: este modo no tiene segmentacion
    4 mallas           -> visualizacion: la superficie del aire pulmonar para el visor

Si una etapa falla, queda en failed, las siguientes en skipped y el estudio en failed
(ProcessingProgressStore.fail_from_stage), y se lanza StageFailedError, igual que la
tuberia de siempre. Si todo sale bien, el estudio se cierra en completed con el modelo
X2CT-GAN.
"""

import logging
import time
from typing import Protocol

from radvol3d import config
from radvol3d.domain.enums import StageNumber
from radvol3d.domain.exceptions import StageFailedError
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.radiograph_result_store import RadiographResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.radiograph_surface import RadiographSurface
from radvol3d.services.pipeline.radiograph_check import validate_radiograph
from radvol3d.services.reconstruction.frontal_validation import validate_files
from radvol3d.services.reconstruction.x2ct_strategy import X2ctReconstruction

logger = logging.getLogger(__name__)


class X2ctReconstructor(Protocol):
    """Lo que esta corrida necesita de X2ctStrategy (un doble en las pruebas)."""

    model_name: str
    model_version: str

    def reconstruct_study(self, radiograph: bytes) -> X2ctReconstruction: ...


class X2ctRadiographRun:
    """Corre las etapas de un estudio de una radiografia con X2CT-GAN."""

    def __init__(
        self,
        progress_store: ProcessingProgressStore,
        metadata_store: StudyMetadataStore,
        result_store: RadiographResultStore,
        surface: RadiographSurface | None = None,
    ) -> None:
        self._progress = progress_store
        self._metadata = metadata_store
        self._results = result_store
        self._surface = surface or RadiographSurface()

    def run(
        self,
        study_code: str,
        radiograph: bytes,
        strategy: X2ctReconstructor,
        started: float,
    ) -> X2ctReconstruction:
        """Corre las etapas y cierra el estudio. Lanza StageFailedError si una falla."""
        stage = StageNumber.PREPROCESSING
        try:
            self._progress.start_stage(study_code, stage)
            radiograph = validate_radiograph(radiograph)
            self._progress.complete_stage(study_code, stage)

            stage = StageNumber.RECONSTRUCTION
            self._progress.start_stage(study_code, stage)
            reconstruction = strategy.reconstruct_study(radiograph)
            self._metadata.save_volume(study_code, reconstruction.volume)
            self._results.save_reconstruction(
                study_code, reconstruction.files, reconstruction.view()
            )
            self._save_validation(study_code, reconstruction)
            self._progress.complete_stage(
                study_code, stage, strategy.model_name, strategy.model_version
            )

            stage = StageNumber.SEGMENTATION
            self._progress.skip_stage(study_code, stage)

            stage = StageNumber.MESHING
            self._progress.start_stage(study_code, stage)
            surface = self._surface.build(reconstruction.volume, reconstruction.voxel_mm)
            self._results.save_organ_mesh(study_code, surface)
            self._progress.complete_stage(study_code, stage)
        except Exception as error:
            self._record_failure(study_code, stage, error)
            raise StageFailedError(study_code, stage) from error

        self._progress.complete_study(
            study_code,
            strategy.model_name,
            strategy.model_version,
            config.GRID_SIZE,
            time.perf_counter() - started,
        )
        return reconstruction

    def _save_validation(self, study_code: str, reconstruction: X2ctReconstruction) -> None:
        """Calcula y guarda la validacion frontal. Si falla, el estudio sigue igual.

        La validacion es informativa: si no se puede calcular ahora, el visor la pide y se
        calcula la primera vez que se abre (StudyService.radiograph_validation).
        """
        try:
            validation = validate_files(reconstruction.files)
            self._results.save_files(study_code, validation.files())
            logger.info(
                "Validacion frontal del estudio %s en %.2f s",
                study_code,
                validation.values["tiempo_s"],
            )
        except Exception as error:  # noqa: BLE001 - la validacion no tumba el estudio
            logger.warning(
                "No se pudo calcular la validacion frontal del estudio %s (%s)",
                study_code,
                type(error).__name__,
            )

    def _record_failure(self, study_code: str, stage: StageNumber, error: Exception) -> None:
        """Registra la etapa fallida. El log guarda el tipo del error, nunca su texto."""
        logger.error(
            "Fallo la etapa %d del estudio %s (%s)", stage.value, study_code, type(error).__name__
        )
        try:
            self._progress.fail_from_stage(study_code, stage)
        except Exception as record_error:  # noqa: BLE001 - el error de la etapa manda
            logger.error(
                "No se pudo registrar el fallo de la etapa %d del estudio %s (%s)",
                stage.value,
                study_code,
                type(record_error).__name__,
            )
