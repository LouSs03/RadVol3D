"""Puerto por el que la tuberia informa su avance y guarda lo que produce.

Es un Protocol: la tuberia no sabe si del otro lado esta la persistencia real
(PersistenceProgress) o un doble de prueba que solo anota los eventos.
"""

from typing import Protocol

from numpy import ndarray

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import StageNumber
from radvol3d.services.meshing.meshing_strategy import MeshSet


class PipelineProgress(Protocol):
    """Lo que la tuberia necesita para registrar cada etapa y guardar sus salidas."""

    def stage_started(self, study_code: str, stage: StageNumber) -> None:
        """La etapa empieza: pasa a running."""

    def stage_completed(
        self,
        study_code: str,
        stage: StageNumber,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        """La etapa termina bien: pasa a completed y, si lo hay, registra su modelo."""

    def stage_failed(self, study_code: str, stage: StageNumber) -> None:
        """La etapa falla: queda en failed, las siguientes en skipped y el estudio en failed."""

    def save_volume(self, study_code: str, volume: ndarray) -> None:
        """Guarda el volumen reconstruido (despues de la etapa 2)."""

    def save_result(
        self, study_code: str, segmentation: SegmentationResult, meshes: MeshSet
    ) -> None:
        """Guarda mascara, probabilidad, resumen, lesiones y mallas (despues de la etapa 4)."""
