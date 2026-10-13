"""Extrae las superficies con marching cubes y las exporta en GLB (research.md R19).

- Tumor: la superficie de la mascara de segmentacion, a resolucion completa.
- Lesiones: una superficie por region del resumen, separada de la mascara con
  split_lesion_masks (research.md R9 de 004), con el mismo paso que el tumor. Se
  descartan las lesiones con la mayoria de sus vertices fuera de la caja de la region
  del organo, en voxeles y antes de suavizar (MeshSet.discarded); el tumor es la union
  de las que quedan.
- Organo: la superficie de una region del volumen reconstruido, que elige la
  OrganRegionStrategy recibida (organ_region.py). En el pulmon es el aire que encierra
  el cuerpo (LungAirRegion); por omision, el tejido mas brillante
  (LargestComponentRegion). Se extrae con un paso de 2 voxeles: basta como contexto y
  el archivo pesa ~7 veces menos. La region es binaria y su superficie directa sale
  escalonada, como una masa de voxeles.

Las tres mallas se suavizan del mismo modo: filtro gaussiano antes de marching cubes,
pulido laplaciano despues y, si pasan de MAX_FACES caras, decimacion cuadrica (requiere
fast-simplification). El organo, con el suavizado que trae su estrategia de region;
tumor y lesiones, con SMOOTHING_SIGMA y LAPLACIAN_ITERATIONS. Las caras quedan
orientadas hacia afuera. El organo se corta en 0.5; las lesiones, en el nivel que
conserva su cantidad de voxeles (ver _smooth_mesh).

La malla del organo depende de la calidad de la reconstruccion: si el volumen sale
borroso, la superficie tambien (FR-026a). Un umbral fijo en HU queda como mejora.

Todas las mallas comparten coordenadas: milimetros (config.MM_PER_VOXEL por voxel),
ejes de numpy en orden (0, 1, 2) y origen en el centro del volumen. Asi el visor
las superpone sin transformarlas. Si no hay superficie, se devuelve un .glb valido
sin geometria.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import trimesh
from scipy import ndimage
from skimage.measure import marching_cubes

from radvol3d import config
from radvol3d.services.meshing.lesion_regions import split_lesion_masks
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy, MeshSet
from radvol3d.services.meshing.organ_region import LargestComponentRegion, OrganRegionStrategy

# Paso de marching cubes para cada malla, en voxeles.
TUMOR_STEP = 1
ORGAN_STEP = 2

# Suavizado de tumor y lesiones: desvio del filtro gaussiano (en voxeles) e iteraciones
# del laplaciano. El del organo lo trae su estrategia de region.
SMOOTHING_SIGMA = 1.5
LAPLACIAN_ITERATIONS = 5
# Por encima de MAX_FACES caras se decima hasta TARGET_FACES.
MAX_FACES = 50_000
TARGET_FACES = 30_000
# Una lesion se descarta si mas de esta fraccion de sus vertices cae fuera de la caja
# del organo: son las que quedaban en las puntas del artefacto, fuera del organo.
MAX_OUTSIDE_FRACTION = 0.5


class MarchingCubesStrategy(MeshingStrategy):
    """Genera la malla del organo, la del tumor y una por lesion con marching cubes."""

    model_name = "marching_cubes"
    model_version = "1.3.0"

    def __init__(
        self,
        mm_per_voxel: float = config.MM_PER_VOXEL,
        organ_region: OrganRegionStrategy | None = None,
    ) -> None:
        self._mm_per_voxel = float(mm_per_voxel)
        self._organ_region = organ_region or LargestComponentRegion()

    @property
    def organ_region(self) -> OrganRegionStrategy:
        """La estrategia que elige la region de la malla del organo."""
        return self._organ_region

    def build_meshes(
        self, volume: Any, mask: Any, regions: Sequence[Mapping[str, Any]]
    ) -> MeshSet:
        volume = np.asarray(volume, dtype=np.float32)
        tumor = np.asarray(mask) > 0
        lesion_masks = split_lesion_masks(tumor, regions)
        organ_region = self._organ_region.region(volume)
        organ = self._smooth_mesh(
            organ_region,
            ORGAN_STEP,
            sigma=self._organ_region.smoothing_sigma,
            iterations=self._organ_region.laplacian_iterations,
        )
        lesions = [
            self._smooth_mesh(lesion, TUMOR_STEP, keep_volume=True) for lesion in lesion_masks
        ]
        organ_box = self._region_box(organ_region)
        discarded = tuple(
            index for index, lesion in enumerate(lesions) if _mostly_outside(lesion, organ_box)
        )
        kept = [lesion for index, lesion in enumerate(lesions) if index not in discarded]
        return MeshSet(
            organ=_glb(organ),
            tumor=_glb(self._tumor_mesh(tumor, lesion_masks, kept)),
            lesions=tuple(_glb(lesion) for lesion in kept),
            discarded=discarded,
        )

    def _tumor_mesh(
        self,
        tumor: np.ndarray,
        lesion_masks: Sequence[np.ndarray],
        kept: Sequence[trimesh.Trimesh | None],
    ) -> trimesh.Trimesh | None:
        """El tumor: las mallas de las lesiones que quedan, juntas en una sola.

        Se juntan las mallas ya hechas y no se suaviza la mascara entera: con el
        filtro, las lesiones chicas se desvanecen en el conjunto aunque cada una por
        separado tenga malla. Sin regiones, la superficie de la mascara completa.
        """
        if not lesion_masks:
            return self._smooth_mesh(tumor, TUMOR_STEP, keep_volume=True)
        meshes = [mesh for mesh in kept if mesh is not None]
        return trimesh.util.concatenate(meshes) if meshes else None

    def _region_box(self, region: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        """Caja de la region en mm, en las coordenadas de las mallas; None si esta vacia.

        Sale de los voxeles y no de la malla suavizada: asi cambiar el suavizado del
        organo no cambia que lesiones se descartan. Lleva medio voxel por lado, donde
        marching cubes pone la superficie de una region binaria.
        """
        if not region.any():
            return None
        indices = np.argwhere(region)
        center = (np.asarray(region.shape, dtype=np.float64) - 1) / 2
        low = (indices.min(axis=0) - 0.5 - center) * self._mm_per_voxel
        high = (indices.max(axis=0) + 0.5 - center) * self._mm_per_voxel
        return low, high

    def _smooth_mesh(
        self,
        region: np.ndarray,
        step: int,
        keep_volume: bool = False,
        sigma: float = SMOOTHING_SIGMA,
        iterations: int = LAPLACIAN_ITERATIONS,
    ) -> trimesh.Trimesh | None:
        """Malla suavizada de la region; None si no hay superficie que extraer.

        Con keep_volume, el nivel de corte no es 0.5 sino el que deja dentro tantos
        voxeles como tiene la region. Las lesiones lo necesitan: muchas son laminas de
        uno o dos voxeles que con 0.5 no llegan al nivel o quedan en el 2-6 % de su
        volumen (prueba_real_001). Con este nivel conservan el 85 % en la mediana.
        """
        if not region.any():
            return None
        # El margen supera el alcance del filtro (3 sigma): la superficie sigue
        # cerrada aunque la region toque el limite del volumen.
        pad = 1 + int(np.ceil(3 * sigma))
        field = ndimage.gaussian_filter(np.pad(region.astype(np.float32), pad), sigma)
        level = _volume_level(field, int(region.sum())) if keep_volume else 0.5
        mesh = self._extract(field, pad, region.shape, step, level)
        if mesh is None:
            # Si aun asi no hay superficie, se extrae sin suavizar antes que perderla.
            mesh = self._extract(np.pad(region.astype(np.float32), 1), 1, region.shape, step)
            if mesh is None:
                return None
        else:
            # Con el volumen constante (volume_constraint) el pulido no encoge la malla.
            trimesh.smoothing.filter_laplacian(mesh, iterations=iterations)
        if len(mesh.faces) > MAX_FACES:
            mesh = mesh.simplify_quadric_decimation(face_count=TARGET_FACES)
        # marching cubes deja las caras orientadas hacia adentro (volumen negativo):
        # se invierten para que las normales apunten afuera y la luz caiga bien.
        if mesh.volume < 0:
            mesh.invert()
        return mesh

    def _extract(
        self,
        field: np.ndarray,
        pad: int,
        shape: tuple[int, ...],
        step: int,
        level: float = 0.5,
    ) -> trimesh.Trimesh | None:
        """Isosuperficie del campo en level, en mm y centrada; None si no hay superficie.

        field es la region con pad voxeles de margen por lado, que aqui se descuentan.
        """
        spacing = (self._mm_per_voxel,) * 3
        try:
            vertices, faces, _, _ = marching_cubes(
                field, level=level, spacing=spacing, step_size=step
            )
        except (ValueError, RuntimeError):
            # scikit-image lanza ValueError si el nivel queda fuera de los datos y
            # RuntimeError si no encuentra superficie.
            return None
        center = (np.asarray(shape, dtype=np.float64) - 1) / 2
        vertices = vertices - (pad + center) * self._mm_per_voxel
        return trimesh.Trimesh(vertices, faces, process=False)


def _volume_level(field: np.ndarray, voxels: int) -> float:
    """Nivel que deja por encima exactamente los voxels valores mas altos del campo."""
    top = np.sort(np.partition(field.ravel(), -(voxels + 1))[-(voxels + 1) :])
    return float(top[0] + top[1]) / 2


def _mostly_outside(
    lesion: trimesh.Trimesh | None, organ_box: tuple[np.ndarray, np.ndarray] | None
) -> bool:
    """True si mas de MAX_OUTSIDE_FRACTION de los vertices cae fuera de la caja del organo.

    Sin organo o sin lesion no hay con que comparar: la lesion se conserva.
    """
    if lesion is None or organ_box is None:
        return False
    low, high = organ_box
    outside = np.any((lesion.vertices < low) | (lesion.vertices > high), axis=1)
    return float(outside.mean()) > MAX_OUTSIDE_FRACTION


def _glb(mesh: trimesh.Trimesh | None) -> bytes:
    """La malla en .glb; sin malla, un .glb valido sin geometria."""
    return _empty_glb() if mesh is None else mesh.export(file_type="glb")


def _empty_glb() -> bytes:
    """Un .glb valido sin geometria (trimesh.Scene() vacio no se puede exportar)."""
    return trimesh.Trimesh().export(file_type="glb")
