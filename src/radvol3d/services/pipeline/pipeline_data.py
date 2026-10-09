"""Los datos que viajan de un filtro al siguiente dentro de la tuberia.

Son inmutables y propios de cada corrida: cada filtro devuelve una copia con su
campo lleno (dataclasses.replace). Asi dos estudios procesados a la vez nunca
comparten un arreglo intermedio.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from numpy import ndarray

from radvol3d.domain.entities import SegmentationResult
from radvol3d.services.meshing.meshing_strategy import MeshSet


@dataclass(frozen=True)
class PipelineData:
    """Estado de un estudio dentro de la tuberia. Cada etapa llena un campo."""

    study_code: str
    projections_by_angle: Mapping[int, ndarray]
    projections: ndarray | None = None
    volume: ndarray | None = None
    segmentation: SegmentationResult | None = None
    meshes: MeshSet | None = None
