"""Los cuatro filtros de la tuberia (Pipes and Filters).

Cada filtro hace una sola etapa: recibe un PipelineData, llena su campo y devuelve
una copia nueva. No guarda estado entre corridas, asi que la misma instancia sirve
para varios estudios a la vez.
"""

from dataclasses import replace

from radvol3d.domain.enums import StageNumber
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.pipeline.pipeline_data import PipelineData
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
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
    """Etapa 4: genera las mallas desde el volumen y la mascara del tumor."""

    stage_number = StageNumber.MESHING
    model: tuple[str, str] | None = None

    def __init__(self, strategy: MeshingStrategy) -> None:
        self._strategy = strategy

    def apply(self, data: PipelineData) -> PipelineData:
        return replace(
            data, meshes=self._strategy.build_meshes(data.volume, data.segmentation.mask)
        )
