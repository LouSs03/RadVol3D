"""Extrae las superficies con marching cubes y las exporta en GLB (research.md R19).

- Tumor: la superficie de la mascara de segmentacion, a resolucion completa.
- Organo: la superficie del volumen reconstruido. El umbral sale del propio volumen
  por el metodo de Otsu, sin ningun numero fijado a mano. Se conserva solo la region
  conexa mas grande, con sus huecos rellenos, para descartar islas de ruido, y se
  extrae con un paso de 2 voxeles: basta como contexto y el archivo pesa ~7 veces
  menos.

La malla del organo depende de la calidad de la reconstruccion: si el volumen sale
borroso, la superficie tambien (FR-026a). Un umbral fijo en HU queda como mejora.

Las dos mallas comparten coordenadas: milimetros (config.MM_PER_VOXEL por voxel),
ejes de numpy en orden (0, 1, 2) y origen en el centro del volumen. Asi el visor
las superpone sin transformarlas. Si no hay superficie, se devuelve un .glb valido
sin geometria.
"""

import numpy as np
import trimesh
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.measure import marching_cubes

from radvol3d import config
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy, MeshSet

# Paso de marching cubes para cada malla, en voxeles.
TUMOR_STEP = 1
ORGAN_STEP = 2


class MarchingCubesStrategy(MeshingStrategy):
    """Genera la malla del organo y la del tumor con marching cubes."""

    model_name = "marching_cubes"
    model_version = "1.0.0"

    def __init__(self, mm_per_voxel: float = config.MM_PER_VOXEL) -> None:
        self._mm_per_voxel = float(mm_per_voxel)

    def build_meshes(self, volume, mask) -> MeshSet:
        volume = np.asarray(volume, dtype=np.float32)
        tumor = np.asarray(mask) > 0
        return MeshSet(
            organ=self._surface(self._organ_region(volume), volume.shape, ORGAN_STEP),
            tumor=self._surface(tumor, volume.shape, TUMOR_STEP),
        )

    @staticmethod
    def _organ_region(volume: np.ndarray) -> np.ndarray:
        """Region del organo: Otsu, la componente conexa mas grande y sus huecos rellenos."""
        if not np.isfinite(volume).all() or float(volume.min()) == float(volume.max()):
            return np.zeros(volume.shape, dtype=bool)
        foreground = volume > threshold_otsu(volume)
        labels, count = ndimage.label(foreground)
        if count == 0:
            return foreground
        sizes = ndimage.sum(foreground, labels, range(1, count + 1))
        largest = labels == int(np.argmax(sizes)) + 1
        return ndimage.binary_fill_holes(largest)

    def _surface(self, region: np.ndarray, shape: tuple[int, ...], step: int) -> bytes:
        """Malla de la region en .glb; vacia si no hay superficie que extraer."""
        if not region.any():
            return _empty_glb()
        # El borde de un voxel cierra la superficie si la region toca el limite.
        padded = np.pad(region.astype(np.float32), 1)
        spacing = (self._mm_per_voxel,) * 3
        try:
            vertices, faces, _, _ = marching_cubes(
                padded, level=0.5, spacing=spacing, step_size=step
            )
        except (ValueError, RuntimeError):
            # scikit-image lanza ValueError si el nivel queda fuera de los datos y
            # RuntimeError si no encuentra superficie.
            return _empty_glb()
        center = (np.asarray(shape, dtype=np.float64) - 1) / 2
        vertices = vertices - (1 + center) * self._mm_per_voxel
        return trimesh.Trimesh(vertices, faces, process=False).export(file_type="glb")


def _empty_glb() -> bytes:
    """Un .glb valido sin geometria (trimesh.Scene() vacio no se puede exportar)."""
    return trimesh.Trimesh().export(file_type="glb")
