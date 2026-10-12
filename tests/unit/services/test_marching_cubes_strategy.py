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
    assert strategy.model_version == "1.2.0"


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
    # El filtro gaussiano mete la superficie de una esfera chica ~0,4 voxeles por lado.
    assert np.allclose(first_high - first_low, 2 * 6 * MM, atol=1.5 * MM)
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


# --- Suavizado y decimacion de la malla del organo ---


def organ_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    return trimesh.util.concatenate(list(scene.geometry.values()))


@pytest.mark.unit
def test_the_organ_surface_is_smooth_not_a_staircase_of_voxels(
    strategy: MarchingCubesStrategy,
) -> None:
    radius = 20
    volume = np.where(sphere((CENTER,) * 3, radius), 0.8, 0.1).astype(np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    mesh = organ_mesh(reload(strategy.build_meshes(volume, mask, []).organ))

    distances = np.linalg.norm(mesh.vertices, axis=1)
    # Sin suavizar, los escalones de la esfera binaria dispersan el radio ~0.3 voxeles.
    assert distances.std() < 0.15 * MM
    assert abs(distances.mean() - radius * MM) < MM


@pytest.mark.unit
def test_an_organ_touching_the_border_still_gives_a_closed_surface(
    strategy: MarchingCubesStrategy,
) -> None:
    volume = np.full((N, N, N), 0.1, dtype=np.float32)
    volume[:30, 10:50, 10:50] = 0.8
    mask = np.zeros((N, N, N), dtype=np.uint8)

    mesh = organ_mesh(reload(strategy.build_meshes(volume, mask, []).organ))

    assert mesh.is_watertight


@pytest.mark.unit
def test_an_organ_mesh_with_too_many_faces_is_decimated(
    strategy: MarchingCubesStrategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from radvol3d.services.meshing import marching_cubes_strategy as module

    monkeypatch.setattr(module, "MAX_FACES", 1_000)
    monkeypatch.setattr(module, "TARGET_FACES", 500)
    volume = np.where(sphere((CENTER,) * 3, 20), 0.8, 0.1).astype(np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    mesh = organ_mesh(reload(strategy.build_meshes(volume, mask, []).organ))

    assert 0 < len(mesh.faces) <= 1_000


@pytest.mark.unit
def test_the_organ_faces_point_outwards(strategy: MarchingCubesStrategy) -> None:
    volume = np.where(sphere((CENTER,) * 3, 20), 0.8, 0.1).astype(np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    mesh = organ_mesh(reload(strategy.build_meshes(volume, mask, []).organ))

    assert mesh.volume > 0


@pytest.mark.unit
def test_thin_spikes_around_the_organ_are_trimmed(strategy: MarchingCubesStrategy) -> None:
    body = sphere((CENTER,) * 3, 14)
    spike = np.zeros_like(body)
    spike[int(CENTER) - 1 : int(CENTER) + 2, int(CENTER) - 1 : int(CENTER) + 2, 4:60] = True
    volume = np.where(body | spike, 0.8, 0.1).astype(np.float32)
    mask = np.zeros((N, N, N), dtype=np.uint8)

    low, high = reload(strategy.build_meshes(volume, mask, []).organ).bounds

    # La punta llega casi al borde; sin ella, la caja es la de la esfera.
    assert np.allclose(high - low, 2 * 14 * MM, atol=2 * MM)


@pytest.mark.unit
def test_an_organ_thinner_than_the_opening_is_kept(strategy: MarchingCubesStrategy) -> None:
    volume = np.full((N, N, N), 0.1, dtype=np.float32)
    volume[20:44, 20:44, 30:34] = 0.8  # una placa de 4 voxeles de espesor
    mask = np.zeros((N, N, N), dtype=np.uint8)

    assert vertex_count(reload(strategy.build_meshes(volume, mask, []).organ)) > 0


# --- Lesiones: suavizado y descarte fuera del organo ---


@pytest.mark.unit
def test_a_lesion_outside_the_organ_box_is_discarded_and_left_out_of_the_tumor(
    strategy: MarchingCubesStrategy,
) -> None:
    inside = sphere((CENTER,) * 3, 4)
    outside = sphere((6.0, 6.0, 6.0), 4)
    mask = (inside | outside).astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 14), 0.7, 0.05).astype(np.float32)
    regions = regions_for(mask)

    meshes = strategy.build_meshes(volume, mask, regions)

    outside_position = next(
        i for i, region in enumerate(regions) if region["centroid_voxel"] == [6, 6, 6]
    )
    assert meshes.discarded == (outside_position,)
    assert len(meshes.lesions) == 1
    assert np.allclose(reload(meshes.tumor).bounds, reload(meshes.lesions[0]).bounds)


@pytest.mark.unit
def test_lesions_inside_the_organ_box_are_all_kept(strategy: MarchingCubesStrategy) -> None:
    mask = (sphere((24.0, 31.0, 31.0), 4) | sphere((40.0, 31.0, 31.0), 4)).astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert meshes.discarded == ()
    assert len(meshes.lesions) == 2


@pytest.mark.unit
def test_the_lesion_surface_is_smooth_not_a_staircase_of_voxels(
    strategy: MarchingCubesStrategy,
) -> None:
    mask = sphere((CENTER,) * 3, 10).astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    lesion = organ_mesh(reload(strategy.build_meshes(volume, mask, regions_for(mask)).lesions[0]))

    distances = np.linalg.norm(lesion.vertices, axis=1)
    assert distances.std() < 0.15 * MM
    assert lesion.volume > 0


@pytest.mark.unit
def test_a_tiny_lesion_still_gets_a_mesh(strategy: MarchingCubesStrategy) -> None:
    mask = np.zeros((N, N, N), dtype=np.uint8)
    mask[31, 31, 31:33] = 1  # dos voxeles: el filtro gaussiano la deja bajo 0.5
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert vertex_count(reload(meshes.lesions[0])) > 0


@pytest.mark.unit
def test_the_tumor_is_the_union_of_the_kept_lesion_meshes(
    strategy: MarchingCubesStrategy,
) -> None:
    mask = sphere((24.0, 31.0, 31.0), 5)
    mask[40, 31, 31:33] = True  # una lesion de dos voxeles, que el filtro desvanece
    mask = mask.astype(np.uint8)
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    tumor = organ_mesh(reload(meshes.tumor))
    lesions = [organ_mesh(reload(glb)) for glb in meshes.lesions]
    assert len(lesions) == 2
    assert tumor.volume == pytest.approx(sum(lesion.volume for lesion in lesions))


@pytest.mark.unit
def test_a_thin_sheet_lesion_keeps_most_of_its_volume(strategy: MarchingCubesStrategy) -> None:
    mask = np.zeros((N, N, N), dtype=np.uint8)
    mask[31, 20:44, 20:44] = 1  # una lamina de un voxel de espesor
    volume = np.where(sphere((CENTER,) * 3, 25), 0.7, 0.05).astype(np.float32)

    lesion = organ_mesh(reload(strategy.build_meshes(volume, mask, regions_for(mask)).lesions[0]))

    assert lesion.volume > 0.7 * mask.sum() * MM**3


@pytest.mark.unit
@pytest.mark.parametrize("sigma", [1.5, 2.5, 5.0])
def test_the_organ_smoothing_does_not_change_which_lesions_are_discarded(
    strategy: MarchingCubesStrategy, monkeypatch: pytest.MonkeyPatch, sigma: float
) -> None:
    from radvol3d.services.meshing import marching_cubes_strategy as module

    monkeypatch.setattr(module, "ORGAN_SMOOTHING_SIGMA", sigma)
    volume = np.where(sphere((CENTER,) * 3, 14), 0.7, 0.05).astype(np.float32)
    # Junto al borde: dentro de la caja de la region del organo, pero fuera de la caja
    # de su malla en cuanto el suavizado la encoge (con la caja de la malla, sigma 2.5
    # ya la descartaba).
    mask = sphere((45.0, CENTER, CENTER), 2).astype(np.uint8)

    meshes = strategy.build_meshes(volume, mask, regions_for(mask))

    assert meshes.discarded == ()
    assert len(meshes.lesions) == 1
