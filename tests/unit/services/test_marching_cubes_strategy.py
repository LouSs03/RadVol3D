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
from radvol3d.services.segmentation.lung_region_summary import summarize_regions

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


def regions_for(mask: np.ndarray) -> list[dict]:
    """Las regiones del resumen, calculadas como en EN-2."""
    binary = np.asarray(mask) > 0
    probability = np.where(binary, 0.9, 0.05).astype(np.float32)
    return summarize_regions(binary.astype(np.uint8), probability, MM)


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

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

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

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert vertex_count(reload(meshes.tumor)) == 0
    assert vertex_count(reload(meshes.organ)) > 0


@pytest.mark.unit
def test_a_constant_volume_gives_a_valid_organ_mesh_without_geometry(
    strategy: MarchingCubesStrategy,
) -> None:
    volume = np.full((N, N, N), 0.5, dtype=np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert vertex_count(reload(meshes.organ)) == 0
    assert vertex_count(reload(meshes.tumor)) == 0


@pytest.mark.unit
def test_the_organ_mesh_keeps_only_the_largest_region(strategy: MarchingCubesStrategy) -> None:
    big_center, small_center = (24.0, 24.0, 24.0), (52.0, 52.0, 52.0)
    volume = np.full((N, N, N), 0.1, dtype=np.float32)
    volume[sphere(big_center, 14)] = 0.8
    volume[sphere(small_center, 5)] = 0.8
    mask = np.zeros((N, N, N), dtype=np.uint8)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

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

    meshes = strategy.build_meshes(volume, tumor.astype(np.uint8), regions_for(tumor))

    organ_low, organ_high = reload(meshes.organ).bounds
    tumor_low, tumor_high = reload(meshes.tumor).bounds
    assert np.all(tumor_low >= organ_low) and np.all(tumor_high <= organ_high)
    assert tumor_low[0] + tumor_high[0] > 0  # desplazado hacia +eje 0, como la mascara


@pytest.mark.unit
def test_the_organ_mesh_is_coarser_than_the_tumor_mesh(strategy: MarchingCubesStrategy) -> None:
    same = sphere((CENTER,) * 3, 20)
    volume = np.where(same, 0.8, 0.1).astype(np.float32)

    meshes = strategy.build_meshes(volume, same.astype(np.uint8), regions_for(same))

    assert vertex_count(reload(meshes.organ)) < vertex_count(reload(meshes.tumor))


@pytest.mark.unit
def test_marching_cubes_has_a_name_but_no_model_row(strategy: MarchingCubesStrategy) -> None:
    assert strategy.model_name == "marching_cubes"
    assert strategy.model_version == "1.0.0"


# --- Una malla por lesion (funcionalidad 004, research.md R9) ---


@pytest.mark.unit
def test_each_lesion_gets_its_own_mesh_covering_only_its_region(
    strategy: MarchingCubesStrategy,
) -> None:
    big = sphere((20.0, 20.0, 20.0), 6)
    small = sphere((46.0, 44.0, 40.0), 3)
    mask = (big | small).astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 30), 0.7, 0.05).astype(np.float32)
    regions = regions_for(mask)

    meshes = strategy.build_meshes(volume, mask, regions)

    assert len(meshes.lesions) == 2
    first, second = (reload(glb) for glb in meshes.lesions)
    assert meshes.lesions[0] != meshes.lesions[1]
    first_low, first_high = first.bounds
    second_low, second_high = second.bounds
    # La primera region del resumen es la mas grande: la esfera de radio 6.
    assert np.allclose(first_high - first_low, 2 * 6 * MM, atol=MM)
    assert np.allclose((first_low + first_high) / 2, [to_mm(20.0)] * 3, atol=MM)
    assert np.allclose(
        (second_low + second_high) / 2, [to_mm(46.0), to_mm(44.0), to_mm(40.0)], atol=MM
    )
    assert np.all(first_high < second_low)  # cajas disjuntas


@pytest.mark.unit
def test_the_lesion_meshes_share_the_coordinates_of_the_tumor_mesh(
    strategy: MarchingCubesStrategy,
) -> None:
    mask = sphere((CENTER + 6, CENTER, CENTER), 4).astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert np.allclose(reload(meshes.lesions[0]).bounds, reload(meshes.tumor).bounds)


@pytest.mark.unit
def test_no_regions_gives_no_lesion_meshes(strategy: MarchingCubesStrategy) -> None:
    mask = np.zeros((N, N, N), dtype=np.uint8)
    volume = np.full((N, N, N), 0.1, dtype=np.float32)

    assert strategy.build_meshes(volume, mask, []).lesions == ()


@pytest.mark.unit
def test_a_region_without_surface_gives_a_valid_empty_mesh(
    strategy: MarchingCubesStrategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from radvol3d.services.meshing import marching_cubes_strategy as module

    mask = sphere((CENTER,) * 3, 3).astype(np.uint8)
    regions = regions_for(mask)
    monkeypatch.setattr(
        module, "split_lesion_masks", lambda m, r: [np.zeros(m.shape, dtype=bool)]
    )

    meshes = strategy.build_meshes(np.full((N, N, N), 0.1, np.float32), mask, regions)

    assert len(meshes.lesions) == 1
    assert vertex_count(reload(meshes.lesions[0])) == 0


@pytest.mark.unit
def test_a_mesh_set_without_lesions_defaults_to_an_empty_tuple() -> None:
    assert MeshSet(organ=b"o", tumor=b"t").lesions == ()
