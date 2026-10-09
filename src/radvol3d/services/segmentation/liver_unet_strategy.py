"""Segmentacion de tumor de higado. Pendiente de entrenar."""

from typing import Any

from radvol3d.domain.entities import SegmentationResult
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class LiverUnetStrategy(SegmentationStrategy):
    """Segmenta tumor hepatico."""

    def __init__(self, weights_path: str) -> None:
        self._weights_path = weights_path

    def segment(self, volume: Any, study_code: str) -> SegmentationResult:
        raise NotImplementedError("TODO: entrenar e integrar el modelo de higado")

    @property
    def model_name(self) -> str:
        return "segmentation_liver"

    @property
    def model_version(self) -> str:
        return "1.0.0"
