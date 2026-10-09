"""Dobles de las estrategias.

Son la razon practica por la que se eligio el patron Strategy: con ellos se prueba
la tuberia completa sin GPU, sin PyTorch y sin archivo de pesos de 24 MB.
"""

import numpy as np

from radvol3d.domain.entities import Lesion, SegmentationResult
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy, MeshSet
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy

# Un cubo de 8 voxeles de lado a 2,5 mm por voxel: 8000 mm3 y 34,64 mm de diagonal.
_LESION = Lesion(
    location="centro",
    volume_mm3=8000.0,
    confidence=0.9,
    max_diameter_mm=34.64,
)


class FakeReconstructionStrategy(ReconstructionStrategy):
    """Devuelve un volumen constante que depende de las proyecciones.

    Prueba la tuberia, no el modelo. Que el valor dependa de la entrada permite
    comprobar que dos estudios procesados a la vez no se mezclan.
    """

    def __init__(self, grid_size: int = 128) -> None:
        self._grid_size = grid_size

    def reconstruct(self, projections):
        value = float(np.asarray(projections, dtype=np.float64).mean()) % 1.0
        return np.full((self._grid_size,) * 3, value, dtype=np.float32)

    @property
    def model_name(self) -> str:
        return "fake_reconstruction"

    @property
    def model_version(self) -> str:
        return "0.0.0"


class FakeSegmentationStrategy(SegmentationStrategy):
    """Marca un cubo fijo como lesion, con confianza conocida y un resumen valido."""

    def segment(self, volume, study_code: str) -> SegmentationResult:
        mask = np.zeros(volume.shape, dtype=np.uint8)
        mask[60:68, 60:68, 60:68] = 1
        probability = np.where(mask > 0, 0.9, 0.05).astype(np.float32)
        summary = {
            "study_code": study_code,
            "organ": "lung",
            "model_name": self.model_name,
            "model_version": self.model_version,
            "has_lesion": True,
            "lesion_count": 1,
            "global_confidence": 0.9,
            "regions": [
                {
                    "has_lesion": True,
                    "location": _LESION.location,
                    "volume_mm3": _LESION.volume_mm3,
                    "max_diameter_mm": _LESION.max_diameter_mm,
                    "confidence": _LESION.confidence,
                    "region_id": 1,
                }
            ],
        }
        return SegmentationResult(
            mask=mask,
            probability=probability,
            global_confidence=0.9,
            lesions=[_LESION],
            summary=summary,
        )

    @property
    def model_name(self) -> str:
        return "fake_segmentation"

    @property
    def model_version(self) -> str:
        return "0.0.0"


class FakeMeshingStrategy(MeshingStrategy):
    """Devuelve dos GLB minimos, validos en su cabecera y distintos entre si."""

    def build_meshes(self, volume, mask) -> MeshSet:
        return MeshSet(organ=b"glTF" + b"\x01" * 16, tumor=b"glTF" + b"\x02" * 16)


# ---------------------------------------------------------------------------
# Dobles que fallan: lanzan un error con un texto interno que NUNCA debe llegar al
# mensaje que ve el usuario. Exponen el mismo modelo que los dobles normales.
# ---------------------------------------------------------------------------

INTERNAL_DETAIL = "detalle interno"


class FailingReconstructionStrategy(FakeReconstructionStrategy):
    def reconstruct(self, projections):
        raise RuntimeError(INTERNAL_DETAIL)


class FailingSegmentationStrategy(FakeSegmentationStrategy):
    def segment(self, volume, study_code: str) -> SegmentationResult:
        raise RuntimeError(INTERNAL_DETAIL)


class FailingMeshingStrategy(FakeMeshingStrategy):
    def build_meshes(self, volume, mask) -> MeshSet:
        raise RuntimeError(INTERNAL_DETAIL)
