"""Pruebas de la region del pulmon para su malla (lung_air_region.py).

Usan un torax sintetico en la ventana de -1000 a 1000 HU, desenfocado como sale de
EN-1: aire 0, pulmon 0,075 (-850 HU), tejido 0,5 y hueso 0,85. Cada prueba reproduce
un caso que se encontro con estudios reales (docs/models/meshing.md). Sin torch.
"""

import io

import numpy as np
import pytest
import trimesh
from scipy import ndimage
from skimage.morphology import convex_hull_image

from radvol3d import config
from radvol3d.services.meshing.lung_air_region import (
    AXIAL_AXIS,
    LungAirRegion,
    density_thresholds,
    lung_region,
)
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.meshing.organ_region import LargestComponentRegion

N = 64
AIR, LUNG, TISSUE, BONE = 0.0, 0.075, 0.5, 0.85
COORDINATES = (np.arange(N) - (N - 1) / 2) / (N / 2)
A0, A1, A2 = np.meshgrid(COORDINATES, COORDINATES, COORDINATES, indexing="ij")


def ellipsoid(center, axes) -> np.ndarray:
    return (
        ((A0 - center[0]) / axes[0]) ** 2
        + ((A1 - center[1]) / axes[1]) ** 2
        + ((A2 - center[2]) / axes[2]) ** 2
    ) <= 1


def cylinder(center, axes) -> np.ndarray:
    """Cilindro a lo largo del eje axial (eje 2)."""
    return (((A0 - center[0]) / axes[0]) ** 2 + ((A1 - center[1]) / axes[1]) ** 2) <= 1


def thorax(body_axes=(0.62, 0.85), arm=False, noise=0.0):
    """Volumen, pulmones verdaderos y cuerpo de un torax sintetico."""
    body = cylinder((0, 0), body_axes)
    lungs = ellipsoid((0, -0.38, 0), (0.45, 0.26, 0.6)) | ellipsoid(
        (0, 0.38, 0), (0.45, 0.26, 0.6)
    )
    volume = np.full((N, N, N), AIR, np.float32)
    volume[body] = TISSUE
    volume[lungs] = LUNG
    volume[cylinder((0.5, 0), (0.08, 0.08))] = BONE  # columna
    if arm:
        # Un brazo junto al cuerpo: la envolvente convexa encierra el aire entre ambos.
        volume[cylinder((-0.82, 0.62), (0.12, 0.12))] = TISSUE
    volume = ndimage.gaussian_filter(volume, 1.0)
    if noise:
        volume = volume + np.random.default_rng(0).normal(0, noise, volume.shape)
    return np.clip(volume, 0, 1).astype(np.float32), lungs, body


def dice(found: np.ndarray, truth: np.ndarray) -> float:
    return 2 * float((found & truth).sum()) / float(found.sum() + truth.sum())


def components(mask: np.ndarray) -> int:
    return ndimage.label(mask)[1]


@pytest.mark.unit
def test_the_axial_axis_is_the_rotation_axis_of_the_projections() -> None:
    assert AXIAL_AXIS == 2


@pytest.mark.unit
def test_the_thresholds_separate_pure_air_lung_and_tissue() -> None:
    volume, _, _ = thorax()

    air, tissue = density_thresholds(volume)

    assert AIR < air < LUNG < tissue < TISSUE


@pytest.mark.unit
def test_the_tissue_region_of_a_thorax_is_the_body_and_not_the_lungs() -> None:
    # El motivo de esta estrategia: en un torax, lo brillante es el cuerpo.
    volume, lungs, body = thorax()

    tissue_region = LargestComponentRegion().region(volume)

    assert dice(tissue_region, lungs) < 0.1
    assert dice(tissue_region, body) > 0.7


@pytest.mark.unit
def test_both_lungs_are_found_as_two_pieces() -> None:
    volume, lungs, body = thorax()

    found = LungAirRegion().region(volume)

    assert found.dtype == bool and found.shape == volume.shape
    assert dice(found, lungs) > 0.9
    assert components(found) == 2
    assert found.sum() < 0.3 * body.sum()


@pytest.mark.unit
def test_a_body_cut_by_the_field_of_view_still_gives_the_lungs() -> None:
    volume, lungs, _ = thorax(body_axes=(0.62, 1.15))

    assert dice(lung_region(volume), lungs) > 0.9


@pytest.mark.unit
@pytest.mark.parametrize("last_slice", [22, 40])
def test_a_study_that_ends_in_the_middle_of_the_lungs_still_gives_them(last_slice: int) -> None:
    # Los cortes sin datos despues del final no son aire de afuera del cuerpo. Si lo
    # fueran, un pulmon cortado cerca del vertice tocaria "afuera" en toda su cara.
    volume, lungs, _ = thorax()
    volume[:, :, last_slice:] = AIR
    lungs[:, :, last_slice:] = False

    assert dice(lung_region(volume), lungs) > 0.8


@pytest.mark.unit
def test_a_dark_truncated_border_of_the_field_of_view_is_not_outside_air() -> None:
    # Con el cuerpo cortado por el campo de vision, la reconstruccion oscurece el borde.
    # Lo que ahi queda con densidad de pulmon no es aire de afuera.
    volume, lungs, _ = thorax()
    volume = ndimage.shift(volume, (0, 12, 0), order=0)
    lungs = ndimage.shift(lungs, (0, 12, 0), order=0)
    volume[:, -4:, :] *= 0.2

    assert dice(lung_region(volume), lungs) > 0.85


@pytest.mark.unit
def test_the_air_between_an_arm_and_the_body_is_left_out() -> None:
    volume, lungs, _ = thorax(arm=True)
    concavity = np.zeros(volume.shape, dtype=bool)
    for z in range(N):
        axial = volume[:, :, z]
        concavity[:, :, z] = convex_hull_image(axial > 0.25) & (axial < 0.03)
    assert concavity.any()

    found = lung_region(volume)

    assert not (found & concavity).any()
    assert dice(found, lungs) > 0.9


@pytest.mark.unit
def test_lung_density_material_outside_the_body_is_left_out() -> None:
    # Una manta o espuma entre el brazo y el cuerpo: no es aire puro, pero toca el
    # aire de afuera en buena parte de su superficie.
    volume, lungs, _ = thorax(arm=True)
    pocket = np.zeros(volume.shape, dtype=bool)
    for z in range(N):
        axial = volume[:, :, z]
        pocket[:, :, z] = convex_hull_image(axial > 0.25) & (axial < 0.03)
    volume[pocket] = 0.07

    found = lung_region(volume)

    assert not (found & pocket).any()
    assert dice(found, lungs) > 0.9


@pytest.mark.unit
def test_a_gas_pocket_does_not_take_the_place_of_a_lung() -> None:
    # Con un solo pulmon a la vista, el gas del estomago seria la segunda componente.
    volume, lungs, _ = thorax()
    hidden = ellipsoid((0, -0.38, 0), (0.45, 0.26, 0.6))
    volume[ndimage.binary_dilation(hidden)] = TISSUE
    volume = ndimage.gaussian_filter(volume, 0.7)
    gas = ellipsoid((-0.1, -0.3, 0.85), (0.3, 0.3, 0.12))
    volume[gas] = AIR

    found = lung_region(volume)

    assert not (found & gas).any()
    assert dice(found, lungs & ~hidden) > 0.9
    assert components(found) == 1


@pytest.mark.unit
def test_the_vessels_inside_a_lung_are_part_of_it() -> None:
    volume, lungs, _ = thorax()
    vessel = cylinder((0.0, 0.38), (0.06, 0.06)) & ellipsoid((0, 0.38, 0), (0.45, 0.26, 0.5))
    volume[vessel] = TISSUE

    found = lung_region(volume)

    assert (found & vessel).sum() > 0.9 * vessel.sum()


@pytest.mark.unit
def test_a_gas_pocket_in_the_abdomen_is_left_out() -> None:
    volume, lungs, _ = thorax()
    gas = ellipsoid((-0.2, 0.0, 0.85), (0.12, 0.12, 0.1))
    volume[gas] = AIR

    found = lung_region(volume)

    assert not (found & gas).any()
    assert dice(found, lungs) > 0.9


@pytest.mark.unit
def test_lung_patches_that_come_out_almost_as_pure_air_stay_in_the_lung() -> None:
    # La reconstruccion deja ~16 % del pulmon con densidad de aire puro.
    volume, lungs, _ = thorax()
    patch = ellipsoid((0, 0.38, 0.2), (0.15, 0.1, 0.15))
    volume[patch] = 0.01

    found = lung_region(volume)

    assert (found & patch).sum() == patch.sum()


@pytest.mark.unit
def test_noise_in_the_reconstruction_does_not_lose_the_lungs() -> None:
    volume, lungs, _ = thorax(noise=0.02)

    found = lung_region(volume)

    assert dice(found, lungs) > 0.9
    assert components(found) == 2


@pytest.mark.unit
def test_the_result_does_not_depend_on_the_in_plane_orientation() -> None:
    volume, lungs, _ = thorax()

    found = lung_region(np.ascontiguousarray(np.swapaxes(volume, 0, 1)))

    assert dice(found, np.swapaxes(lungs, 0, 1)) > 0.9


@pytest.mark.unit
def test_a_volume_without_enclosed_air_falls_back_to_the_tissue_region() -> None:
    # Como el fantoma elipsoide de la referencia: un objeto brillante sobre fondo negro.
    volume = np.where(ellipsoid((0, 0, 0), (0.6, 0.45, 0.3)), 0.6, 0.0).astype(np.float32)

    assert not lung_region(volume).any()
    assert np.array_equal(
        LungAirRegion().region(volume), LargestComponentRegion().region(volume)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "volume",
    [
        np.full((N, N, N), 0.5, dtype=np.float32),
        np.zeros((N, N, N), dtype=np.float32),
        np.full((N, N, N), np.nan, dtype=np.float32),
    ],
    ids=["constante", "vacio", "nan"],
)
def test_a_volume_without_content_gives_an_empty_region(volume: np.ndarray) -> None:
    found = LungAirRegion().region(volume)

    assert found.shape == volume.shape and not found.any()


@pytest.mark.unit
def test_the_lung_mesh_has_the_volume_of_the_lungs_and_not_of_the_body() -> None:
    volume, lungs, body = thorax()

    glb = MarchingCubesStrategy(organ_region=LungAirRegion()).build_meshes(
        volume, np.zeros(volume.shape, np.uint8), []
    ).organ
    mesh = trimesh.util.concatenate(
        list(trimesh.load(io.BytesIO(glb), file_type="glb").geometry.values())
    )
    voxel = config.MM_PER_VOXEL**3

    assert mesh.volume == pytest.approx(lungs.sum() * voxel, rel=0.2)
    assert mesh.volume < 0.3 * body.sum() * voxel
