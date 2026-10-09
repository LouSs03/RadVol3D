"""Pruebas de las mallas con marching cubes (FR-026; research.md R19).

No usan torch: scikit-image y trimesh si estan en el CI. Cada malla se vuelve a
abrir con trimesh para comprobar que el visor podria cargarla.
"""

import io

import numpy as np
import pytest
import trimesh

from radvol3d import config
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.meshing.meshing_strategy import MeshSet

N = 64
MM = config.MM_PER_VOXEL
CENTER = (N - 1) / 2


def sphere(center: tuple[float, float, float], radius: float, size: int = N) -> np.ndarray:
    z, y, x = np.indices((size, size, size))
    distance = (z - center[0]) ** 2 + (y - center[1]) ** 2 + (x - center[2]) ** 2
    return distance <= radius**2


def reload(glb: bytes) -> trimesh.Scene:
    assert glb.startswith(b"glTF")
    return trimesh.load(io.BytesIO(glb), file_type="glb")


def vertex_count(scene: trimesh.Scene) -> int:
    return sum(len(g.vertices) for g in scene.geometry.values())


def to_mm(index: float) -> float:
    """Coordenada en mm, con el origen en el centro del volumen."""
    return (index - CENTER) * MM


@pytest.fixture
def strategy() -> MarchingCubesStrategy:
    return MarchingCubesStrategy()


@pytest.mark.unit
def test_a_centered_sphere_gives_a_tumor_mesh_of_its_size_around_the_origin(
    strategy: MarchingCubesStrategy,
) -> None:
    mask = sphere((CENTER, CENTER, CENTER), 10).astype(np.uint8)
    volume = np.where(mask > 0, 0.8, 0.1).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask)

    assert isinstance(meshes, MeshSet)
    scene = reload(meshes.tumor)
    assert vertex_count(scene) > 0
    low, high = scene.bounds
    extent = high - low
    assert np.allclose(extent, 2 * 10 * MM, atol=MM)
    assert np.allclose((low + high) / 2, 0.0, atol=MM)


@pytest.mark.unit
def test_an_empty_mask_gives_a_valid_tumor_mesh_without_geometry(
    strategy: MarchingCubesStrategy,
) -> None:
    mask = np.zeros((N, N, N), dtype=np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 20), 0.8, 0.1).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask)

    assert vertex_count(reload(meshes.tumor)) == 0
    assert vertex_count(reload(meshes.organ)) > 0


@pytest.mark.unit
def test_a_constant_volume_gives_a_valid_organ_mesh_without_geometry(
    strategy: MarchingCubesStrategy,
) -> None:
    volume = np.full((N, N, N), 0.5, dtype=np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    meshes = strategy.build_meshes(volume, mask)

    assert vertex_count(reload(meshes.organ)) == 0
    assert vertex_count(reload(meshes.tumor)) == 0


@pytest.mark.unit
def test_the_organ_mesh_keeps_only_the_largest_region(strategy: MarchingCubesStrategy) -> None:
    big_center, small_center = (24.0, 24.0, 24.0), (52.0, 52.0, 52.0)
    volume = np.full((N, N, N), 0.1, dtype=np.float32)
    volume[sphere(big_center, 14)] = 0.8
    volume[sphere(small_center, 5)] = 0.8
    mask = np.zeros((N, N, N), dtype=np.uint8)

    meshes = strategy.build_meshes(volume, mask)

    low, high = reload(meshes.organ).bounds
    tolerance = 2 * MM  # la malla del organo usa un paso de 2 voxeles
    assert np.allclose(low, [to_mm(c - 14) for c in big_center], atol=tolerance)
    assert np.allclose(high, [to_mm(c + 14) for c in big_center], atol=tolerance)
    assert high.max() < to_mm(small_center[0] - 5)


@pytest.mark.unit
def test_organ_and_tumor_share_the_same_coordinates(strategy: MarchingCubesStrategy) -> None:
    organ = sphere((CENTER,) * 3, 25)
    tumor = sphere((CENTER + 6, CENTER, CENTER), 4)
    volume = np.where(organ, 0.7, 0.05).astype(np.float32)

    meshes = strategy.build_meshes(volume, tumor.astype(np.uint8))

    organ_low, organ_high = reload(meshes.organ).bounds
    tumor_low, tumor_high = reload(meshes.tumor).bounds
    assert np.all(tumor_low >= organ_low) and np.all(tumor_high <= organ_high)
    assert tumor_low[0] + tumor_high[0] > 0  # desplazado hacia +eje 0, como la mascara


@pytest.mark.unit
def test_the_organ_mesh_is_coarser_than_the_tumor_mesh(strategy: MarchingCubesStrategy) -> None:
    same = sphere((CENTER,) * 3, 20)
    volume = np.where(same, 0.8, 0.1).astype(np.float32)

    meshes = strategy.build_meshes(volume, same.astype(np.uint8))

    assert vertex_count(reload(meshes.organ)) < vertex_count(reload(meshes.tumor))


@pytest.mark.unit
def test_marching_cubes_has_a_name_but_no_model_row(strategy: MarchingCubesStrategy) -> None:
    assert strategy.model_name == "marching_cubes"
    assert strategy.model_version == "1.0.0"
