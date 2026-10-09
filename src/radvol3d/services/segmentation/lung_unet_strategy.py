"""Segmentacion de tumor de pulmon con la U-Net 3D residual EN-2.

Los pesos viven en Supabase Storage. Metricas y referencia en
docs/models/segmentation_lung_en2.md.
"""

from typing import Any

from radvol3d.domain.entities import SegmentationResult
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class LungUnetStrategy(SegmentationStrategy):
    """Segmenta tumor pulmonar."""

    def __init__(self, weights_path: str) -> None:
        self._weights_path = weights_path
        # TODO: cargar los pesos una sola vez

    def segment(self, volume: Any, study_code: str) -> SegmentationResult:
        # El volumen debe llegar normalizado a [0,1] con la ventana de config.HU_WINDOW,
        # la misma que uso la reconstruccion. Si llega en HU crudos el modelo devuelve
        # ruido sin avisar, asi que se valida antes de inferir.
        raise NotImplementedError("TODO: envolver el modulo de inferencia de EN-2")

    @property
    def model_name(self) -> str:
        return "segmentation_lung"

    @property
    def model_version(self) -> str:
        return "1.0.0"
