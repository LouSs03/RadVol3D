"""Superficie del modo de una radiografia (X2CT-GAN), con el voxel real de cada eje.

Es un camino propio, separado de MarchingCubesStrategy (modo de cuatro proyecciones),
que supone voxeles cubicos de config.MM_PER_VOXEL. Aqui el voxel cambia con cada placa
y no es cubico (el horizontal y el vertical salen del tamano del pixel del DICOM).

Que superficie es: el aire de los pulmones, sin ningun modelo ni segmentacion. La
region la elige LungAirRegion (la misma de las mallas del pulmon, sin cambios): umbrales
de Otsu calculados del propio volumen, la envolvente del cuerpo corte axial por corte
axial y las hasta dos componentes de aire encerradas por el cuerpo, con los vasos
rellenos. Si el volumen no tiene aire encerrado, LungAirRegion usa la region de tejido
(la silueta del cuerpo). No busca lesiones ni nodulos.

El procedimiento sigue al de MarchingCubesStrategy para el organo (paso de 2 voxeles,
filtro gaussiano, pulido laplaciano y decimacion), con dos diferencias: el espaciado de
marching cubes es el voxel de cada eje y el centro del volumen queda en el origen en
milimetros de cada eje. Las coordenadas son las de los ejes del volumen (R, A, S), como
espera static/js/volume_orientation.js.
"""

from collections.abc import Sequence

import numpy as np
import trimesh
from scipy import ndimage
from skimage.measure import marching_cubes

from radvol3d.services.meshing.lung_air_region import LungAirRegion
from radvol3d.services.meshing.organ_region import OrganRegionStrategy

STEP = 2
MAX_FACES = 50_000
TARGET_FACES = 30_000
LEVEL = 0.5


class RadiographSurface:
    """Genera la superficie (.glb) que dibuja el visor del modo de una radiografia."""

    def __init__(self, region: OrganRegionStrategy | None = None) -> None:
        self._region = region or LungAirRegion()

    def build(self, volume: np.ndarray, voxel_mm: Sequence[float]) -> bytes:
        """Superficie del aire pulmonar en mm (por eje), centrada; .glb vacio si no hay."""
        spacing = tuple(float(value) for value in voxel_mm)
        if len(spacing) != 3 or min(spacing) <= 0:
            raise ValueError("voxel_mm debe tener tres valores positivos.")
        region = self._region.region(np.asarray(volume, dtype=np.float32))
        mesh = _smooth_surface(
            region,
            spacing,
            sigma=self._region.smoothing_sigma,
            iterations=self._region.laplacian_iterations,
        )
        if mesh is None:
            return trimesh.Trimesh().export(file_type="glb")
        return mesh.export(file_type="glb")


def _smooth_surface(
    region: np.ndarray,
    spacing: tuple[float, float, float],
    sigma: float,
    iterations: int,
) -> trimesh.Trimesh | None:
    """Malla suavizada de la region binaria; None si no hay superficie."""
    if not region.any():
        return None
    pad = 1 + int(np.ceil(3 * sigma))
    field = ndimage.gaussian_filter(np.pad(region.astype(np.float32), pad), sigma)
    mesh = _extract(field, pad, region.shape, spacing)
    if mesh is None:
        mesh = _extract(np.pad(region.astype(np.float32), 1), 1, region.shape, spacing)
        if mesh is None:
            return None
    else:
        trimesh.smoothing.filter_laplacian(mesh, iterations=iterations)
    if len(mesh.faces) > MAX_FACES:
        mesh = mesh.simplify_quadric_decimation(face_count=TARGET_FACES)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def _extract(
    field: np.ndarray,
    pad: int,
    shape: tuple[int, ...],
    spacing: tuple[float, float, float],
) -> trimesh.Trimesh | None:
    """Isosuperficie en mm de cada eje, con el centro del volumen en el origen."""
    try:
        vertices, faces, _, _ = marching_cubes(
            field, level=LEVEL, spacing=spacing, step_size=STEP
        )
    except (ValueError, RuntimeError):
        return None
    center = (np.asarray(shape, dtype=np.float64) - 1) / 2
    vertices = vertices - (pad + center) * np.asarray(spacing, dtype=np.float64)
    return trimesh.Trimesh(vertices, faces, process=False)
