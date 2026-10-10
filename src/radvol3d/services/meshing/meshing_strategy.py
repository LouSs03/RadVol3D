"""Interfaz del patron Strategy para la generacion de mallas."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MeshSet:
    """Las mallas de un estudio, cada una como los bytes de un archivo .glb.

    lesions trae una malla por region con lesion, en el orden del resumen de la
    segmentacion, salvo las descartadas. Esta vacia si no hay lesiones.

    discarded trae las posiciones (desde 0, en la lista de regiones recibida) de las
    lesiones que la estrategia descarto, por ejemplo por quedar fuera del organo.
    No tienen malla en lesions y no deben generar fila.
    """

    organ: bytes
    tumor: bytes
    lesions: tuple[bytes, ...] = ()
    discarded: tuple[int, ...] = ()


class MeshingStrategy(ABC):
    """Convierte el volumen y la mascara en las mallas que carga el visor."""

    @abstractmethod
    def build_meshes(
        self, volume: Any, mask: Any, regions: Sequence[Mapping[str, Any]]
    ) -> MeshSet:
        """Recibe el volumen (N, N, N) float32 en [0, 1], la mascara (N, N, N) uint8 y
        las regiones del resumen con lesion (cada una con voxels y centroid_voxel).

        Devuelve la malla del organo (desde el volumen), la del tumor (desde la
        mascara) y una por region, en el orden de regions, menos las que descarte
        (sus posiciones van en MeshSet.discarded). Si no hay superficie que
        extraer, devuelve un .glb valido sin geometria y no lanza: el visor no tiene
        que distinguir ese caso.
        """
