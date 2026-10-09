"""Dobles de las estrategias.

Son la razon practica por la que se eligio el patron Strategy: con ellos se prueba
la tuberia completa sin GPU, sin PyTorch y sin archivo de pesos de 24 MB.
"""

import numpy as np

from radvol3d.domain.entities import Lesion, SegmentationResult
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class FakeReconstructionStrategy(ReconstructionStrategy):
    """Devuelve un volumen constante. Prueba la tuberia, no el modelo."""

    def __init__(self, grid_size: int = 128) -> None:
        self._grid_size = grid_size

    def reconstruct(self, projections):
        return np.full((self._grid_size,) * 3, 0.5, dtype=np.float32)

    @property
    def model_name(self) -> str:
        return "fake_reconstruction"

    @property
    def model_version(self) -> str:
        return "0.0.0"


class FakeSegmentationStrategy(SegmentationStrategy):
    """Marca un cubo fijo como lesion, con confianza conocida."""

    def segment(self, volume) -> SegmentationResult:
        mask = np.zeros(volume.shape, dtype=np.uint8)
        mask[60:68, 60:68, 60:68] = 1
        probability = np.where(mask > 0, 0.9, 0.05).astype(np.float32)
        lesion = Lesion(location="centro", volume_mm3=8000.0, confidence=0.9)
        return SegmentationResult(
            mask=mask,
            probability=probability,
            global_confidence=0.9,
            lesions=[lesion],
        )

    @property
    def model_name(self) -> str:
        return "fake_segmentation"

    @property
    def model_version(self) -> str:
        return "0.0.0"


class FakeMeshingStrategy(MeshingStrategy):
    """Devuelve un GLB minimo valido en su cabecera."""

    def build_mesh(self, mask) -> bytes:
        return b"glTF" + b"\x00" * 16
