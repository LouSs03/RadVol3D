"""Interfaz del patron Strategy para la reconstruccion.

Toda estrategia recibe las cuatro proyecciones y devuelve el volumen. Como la
firma es la misma, la tuberia no necesita saber cual le toco.

Justificacion del patron en docs/architecture/design_patterns.md.
"""

from abc import ABC, abstractmethod
from typing import Any


class ReconstructionStrategy(ABC):
    """Reconstruye un volumen 3D a partir de cuatro proyecciones."""

    @abstractmethod
    def reconstruct(self, projections: Any) -> Any:
        """Recibe (4, N, N) float32 en [0,1] y devuelve (N, N, N) float32 en [0,1].

        Las proyecciones vienen normalizadas con la ventana HU de config.HU_WINDOW.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nombre con el que se registra en la tabla model."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Version del modelo. Junto al nombre identifica la fila en model."""
