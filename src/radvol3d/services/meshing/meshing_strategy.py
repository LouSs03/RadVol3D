"""Interfaz del patron Strategy para la generacion de mallas."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MeshSet:
    """Las dos mallas de un estudio, cada una como los bytes de un archivo .glb."""

    organ: bytes
    tumor: bytes


class MeshingStrategy(ABC):
    """Convierte el volumen y la mascara en las mallas que carga el visor."""

    @abstractmethod
    def build_meshes(self, volume: Any, mask: Any) -> MeshSet:
        """Recibe el volumen (N, N, N) float32 en [0, 1] y la mascara (N, N, N) uint8.

        Devuelve la malla del organo (desde el volumen) y la del tumor (desde la
        mascara). Si no hay superficie que extraer, devuelve un .glb valido sin
        geometria y no lanza: el visor no tiene que distinguir ese caso.
        """
