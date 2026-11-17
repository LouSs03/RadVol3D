"""Pruebas de la superficie del modo de una radiografia (voxel real de cada eje)."""

import io

import numpy as np
import pytest
import trimesh

from radvol3d.services.meshing.organ_region import OrganRegionStrategy
from radvol3d.services.meshing.radiograph_surface import RadiographSurface

N = 64


class BoxRegion(OrganRegionStrategy):
    """Una caja de voxeles conocida: aisla la escala de la eleccion de la region."""

    smoothing_sigma = 0.5
    laplacian_iterations = 0

    def __init__(self, box: tuple[slice, slice, slice] | None) -> None:
        self._box = box

    def region(self, volume: np.ndarray) -> np.ndarray:
        mask = np.zeros(volume.shape, bool)
        if self._box is not None:
            mask[self._box] = True
        return mask


def load(glb: bytes) -> trimesh.Trimesh:
    return trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")


@pytest.mark.unit
def test_the_surface_is_scaled_with_the_voxel_of_each_axis() -> None:
    box = (slice(16, 48), slice(16, 48), slice(16, 48))  # 32 voxeles por lado
    surface = RadiographSurface(BoxRegion(box))

    mesh = load(surface.build(np.zeros((N,) * 3, np.float32), (2.0, 2.0, 5.0)))

    extents = mesh.extents
    # 32 voxeles: ~64 mm en R y A, ~160 mm en S (con el suavizado, unos voxeles menos).
    assert extents[0] == pytest.approx(64, abs=6)
    assert extents[1] == pytest.approx(64, abs=6)
    assert extents[2] == pytest.approx(160, abs=12)


@pytest.mark.unit
def test_the_surface_is_centered_on_the_volume() -> None:
    box = (slice(16, 48), slice(16, 48), slice(16, 48))
    mesh = load(RadiographSurface(BoxRegion(box)).build(np.zeros((N,) * 3, np.float32), (1, 1, 1)))

    assert np.abs(mesh.bounds.mean(axis=0)).max() < 1.5


@pytest.mark.unit
def test_an_empty_region_gives_a_valid_empty_glb() -> None:
    glb = RadiographSurface(BoxRegion(None)).build(np.zeros((N,) * 3, np.float32), (1, 1, 1))

    assert glb[:4] == b"glTF"


@pytest.mark.unit
@pytest.mark.parametrize("voxel", [(1, 1), (1, 0, 1), (1, -2, 1)])
def test_an_invalid_voxel_is_rejected(voxel) -> None:
    with pytest.raises(ValueError):
        RadiographSurface(BoxRegion(None)).build(np.zeros((N,) * 3, np.float32), voxel)


@pytest.mark.unit
def test_by_default_it_uses_the_lung_air_region() -> None:
    from radvol3d.services.meshing.lung_air_region import LungAirRegion

    assert isinstance(RadiographSurface()._region, LungAirRegion)
