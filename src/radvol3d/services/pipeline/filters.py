"""Los filtros de la tuberia (Pipes and Filters).

Cada filtro hace una sola etapa: recibe un PipelineData, llena su campo y devuelve
una copia nueva. No guarda estado entre corridas, asi que la misma instancia sirve
para varios estudios a la vez.

El modo de una radiografia cambia solo las dos primeras etapas
(RadiographPreprocessingFilter y RadiographReconstructionFilter); la segmentacion y
las mallas son los mismos filtros de siempre.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import RemoteJobState, StageNumber
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.pipeline.pipeline_data import PipelineData
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.pipeline.radiograph_check import validate_radiograph
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard
from radvol3d.services.reconstruction.radiograph_reconstruction_strategy import (
    RadiographReconstructionStrategy,
)
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class PreprocessingFilter:
    """Etapa 1: apila las cuatro proyecciones en (4, N, N), en el orden de los angulos."""

    stage_number = StageNumber.PREPROCESSING
    model: tuple[str, str] | None = None

    def __init__(self, loader: ProjectionLoader) -> None:
        self._loader = loader

    def apply(self, data: PipelineData) -> PipelineData:
        return replace(data, projections=self._loader.stack(data.projections_by_angle))


class ReconstructionFilter:
    """Etapa 2: reconstruye el volumen con la estrategia recibida."""

    stage_number = StageNumber.RECONSTRUCTION

    def __init__(self, strategy: ReconstructionStrategy) -> None:
        self._strategy = strategy

    @property
    def model(self) -> tuple[str, str]:
        return self._strategy.model_name, self._strategy.model_version

    def apply(self, data: PipelineData) -> PipelineData:
        return replace(data, volume=self._strategy.reconstruct(data.projections))


class RadiographPreprocessingFilter:
    """Etapa 1 del modo de una radiografia: vuelve a validar el DICOM guardado.

    La conversion que el modelo necesita (invertir si es MONOCHROME1, llevar a
    1024 x 1024, orientar) la hace el servicio externo: aqui no se toca la imagen.
    """

    stage_number = StageNumber.PREPROCESSING
    model: tuple[str, str] | None = None

    def apply(self, data: PipelineData) -> PipelineData:
        return replace(data, radiograph=validate_radiograph(data.radiograph or b""))


class RadiographReconstructionFilter:
    """Etapa 2 del modo de una radiografia: reconstruye con el servicio externo.

    Va avisando en la pizarra si el trabajo esta en cola o reconstruyendose, y la
    limpia al terminar, bien o mal.
    """

    stage_number = StageNumber.RECONSTRUCTION

    def __init__(
        self, strategy: RadiographReconstructionStrategy, board: RemoteJobBoard | None = None
    ) -> None:
        self._strategy = strategy
        self._board = board

    @property
    def model(self) -> tuple[str, str]:
        return self._strategy.model_name, self._strategy.model_version

    def apply(self, data: PipelineData) -> PipelineData:
        try:
            volume = self._strategy.reconstruct(data.radiograph, self._reporter(data.study_code))
        finally:
            if self._board is not None:
                self._board.clear(data.study_code)
        return replace(data, volume=volume)

    def _reporter(self, study_code: str) -> Callable[[RemoteJobState], None] | None:
        """La funcion que anota el estado del trabajo del estudio en la pizarra."""
        board = self._board
        if board is None:
            return None

        def report(state: RemoteJobState) -> None:
            board.update(study_code, state)

        return report


class SegmentationFilter:
    """Etapa 3: segmenta el tumor sobre el volumen reconstruido."""

    stage_number = StageNumber.SEGMENTATION

    def __init__(self, strategy: SegmentationStrategy) -> None:
        self._strategy = strategy

    @property
    def model(self) -> tuple[str, str]:
        return self._strategy.model_name, self._strategy.model_version

    def apply(self, data: PipelineData) -> PipelineData:
        return replace(
            data, segmentation=self._strategy.segment(data.volume, data.study_code)
        )


class MeshingFilter:
    """Etapa 4: genera las mallas desde el volumen, la mascara y las regiones con lesion.

    Las regiones salen del resumen de la segmentacion; las que no son lesion
    (has_lesion distinto de true) no generan malla, igual que no generan fila.

    Si la estrategia descarta lesiones (MeshSet.discarded), sus regiones quedan en el
    resumen con has_lesion en false y el motivo en "discarded", y los totales del
    resumen pasan a contar solo las que quedan. Asi no generan fila y el resultado
    guardado sigue alineado con sus mallas.
    """

    stage_number = StageNumber.MESHING
    model: tuple[str, str] | None = None

    def __init__(self, strategy: MeshingStrategy) -> None:
        self._strategy = strategy

    def apply(self, data: PipelineData) -> PipelineData:
        regions = [
            region
            for region in data.segmentation.summary.get("regions", [])
            if region.get("has_lesion", True) is True
        ]
        meshes = self._strategy.build_meshes(data.volume, data.segmentation.mask, regions)
        segmentation = data.segmentation
        if meshes.discarded:
            segmentation = discard_regions(segmentation, regions, meshes.discarded)
        return replace(data, segmentation=segmentation, meshes=meshes)


DISCARD_REASON = "fuera_del_organo"


def discard_regions(
    segmentation: SegmentationResult,
    regions: Sequence[Mapping[str, Any]],
    discarded: Sequence[int],
) -> SegmentationResult:
    """Marca como descartadas las regiones en esas posiciones de regions.

    Devuelve una copia: el resumen original no se modifica.
    """
    positions = set(discarded)
    dropped = {id(regions[index]) for index in positions}
    summary = dict(segmentation.summary)
    summary["regions"] = [
        {**region, "has_lesion": False, "discarded": DISCARD_REASON}
        if id(region) in dropped
        else region
        for region in summary.get("regions", [])
    ]
    kept = [region for region in summary["regions"] if region.get("has_lesion", True) is True]
    if "has_lesion" in summary:
        summary["has_lesion"] = bool(kept)
    if "lesion_count" in summary:
        summary["lesion_count"] = len(kept)
    if "total_volume_mm3" in summary:
        summary["total_volume_mm3"] = round(sum(region["volume_mm3"] for region in kept), 2)
    summary["discarded_count"] = len(dropped)
    lesions = segmentation.lesions
    if len(lesions) == len(regions):
        lesions = [lesion for index, lesion in enumerate(lesions) if index not in positions]
    return replace(segmentation, summary=summary, lesions=lesions)
