"""Interfaz del patron Strategy para la generacion de mallas."""

from abc import ABC, abstractmethod
from typing import Any


class MeshingStrategy(ABC):
    """Convierte una mascara binaria en una malla que el visor pueda cargar."""

    @abstractmethod
    def build_mesh(self, mask: Any) -> bytes:
        """Recibe (N, N, N) uint8 en {0,1} y devuelve los bytes de un archivo GLB."""
