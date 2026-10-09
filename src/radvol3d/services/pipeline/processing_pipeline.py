"""Las cuatro etapas encadenadas.

Recibe sus estrategias en cada corrida y no sabe cual le toco. Eso es lo que
permite probar la tuberia completa con dobles, sin GPU ni modelo, y servir a todos
los tipos de estudio con el mismo codigo.

Por cada etapa: avisa que empieza, corre el filtro, guarda lo que corresponde
(el volumen despues de la etapa 2, el resultado despues de la 4) y avisa que
termino, con el modelo de la etapa si lo tiene. Si algo falla en la etapa N, la
registra como fallida (las siguientes quedan skipped y el estudio failed) y lanza
StageFailedError con la causa encadenada. La instancia no guarda estado entre
corridas: dos estudios pueden pasar por ella a la vez.
"""

import logging
from collections.abc import Callable, Mapping

from numpy import ndarray

from radvol3d.domain.enums import StageNumber
from radvol3d.domain.exceptions import StageFailedError
from radvol3d.services.pipeline.filters import (
    MeshingFilter,
    PreprocessingFilter,
    ReconstructionFilter,
    SegmentationFilter,
)
from radvol3d.services.pipeline.pipeline_data import PipelineData
from radvol3d.services.pipeline.progress import PipelineProgress
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.strategy_factory import StrategySet

logger = logging.getLogger(__name__)

# Que se guarda al terminar cada filtro. None: la etapa no guarda nada.
_SaveStep = Callable[[PipelineProgress, PipelineData], None] | None


def _save_volume(progress: PipelineProgress, data: PipelineData) -> None:
    progress.save_volume(data.study_code, data.volume)


def _save_result(progress: PipelineProgress, data: PipelineData) -> None:
    progress.save_result(data.study_code, data.segmentation, data.meshes)


class ProcessingPipeline:
    """Encadena preprocesamiento, reconstruccion, segmentacion y mallas."""

    def __init__(self, loader: ProjectionLoader) -> None:
        self._loader = loader

    def run(
        self,
        study_code: str,
        projections_by_angle: Mapping[int, ndarray],
        strategies: StrategySet,
        progress: PipelineProgress,
    ) -> PipelineData:
        """Procesa un estudio completo y devuelve los datos de todas sus etapas."""
        data = PipelineData(study_code=study_code, projections_by_angle=projections_by_angle)
        for stage_filter, save in self._stages(strategies):
            stage = stage_filter.stage_number
            try:
                progress.stage_started(study_code, stage)
                data = stage_filter.apply(data)
                if save is not None:
                    save(progress, data)
                model_name, model_version = stage_filter.model or (None, None)
                progress.stage_completed(study_code, stage, model_name, model_version)
            except Exception as error:
                self._record_failure(study_code, stage, progress, error)
                raise StageFailedError(study_code, stage) from error
        return data

    @staticmethod
    def _record_failure(
        study_code: str, stage: StageNumber, progress: PipelineProgress, error: Exception
    ) -> None:
        """Registra la etapa fallida. Si eso tambien falla, lo deja en el log y sigue.

        El log guarda el tipo de la causa, nunca su texto: podria traer detalles
        internos que no deben salir del servidor.
        """
        logger.error(
            "Fallo la etapa %d del estudio %s (%s)",
            stage.value,
            study_code,
            type(error).__name__,
        )
        try:
            progress.stage_failed(study_code, stage)
        except Exception as record_error:  # noqa: BLE001 - el error de la etapa manda
            logger.error(
                "No se pudo registrar el fallo de la etapa %d del estudio %s (%s)",
                stage.value,
                study_code,
                type(record_error).__name__,
            )

    def _stages(self, strategies: StrategySet) -> list[tuple[object, _SaveStep]]:
        """Los cuatro filtros de esta corrida, cada uno con su paso de guardado."""
        return [
            (PreprocessingFilter(self._loader), None),
            (ReconstructionFilter(strategies.reconstruction), _save_volume),
            (SegmentationFilter(strategies.segmentation), None),
            (MeshingFilter(strategies.meshing), _save_result),
        ]
