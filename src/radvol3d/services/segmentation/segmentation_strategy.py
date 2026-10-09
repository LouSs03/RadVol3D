"""Interfaz del patron Strategy para la segmentacion.

Hay un modelo entrenado por organo. Como todos cumplen esta interfaz, agregar un
tercer organo es agregar un archivo, no tocar la tuberia.
"""

from abc import ABC, abstractmethod
from typing import Any

from radvol3d.domain.entities import SegmentationResult


class SegmentationStrategy(ABC):
    """Segmenta el tumor sobre un volumen reconstruido."""

    @abstractmethod
    def segment(self, volume: Any) -> SegmentationResult:
        """Recibe (N, N, N) float32 en [0,1] y devuelve mascara, confianza y lesiones.

        La confianza por voxel va en el campo probability, en rango [0, 1].
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nombre con el que se registra en la tabla model."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Version del modelo."""
