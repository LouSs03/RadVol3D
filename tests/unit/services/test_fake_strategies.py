"""Comprueba que los dobles cumplen la interfaz de las estrategias.

Si esta prueba falla, los dobles dejaron de servir y todas las pruebas de la
tuberia que dependen de ellos quedan sin valor.
"""

import io
import threading

import numpy as np
import pytest

from radvol3d import config
from radvol3d.domain.enums import StageNumber
from radvol3d.services.meshing.meshing_strategy import MeshSet
from tests.fixtures.fake_progress import RecordingProgress
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files


@pytest.mark.unit
def test_fake_reconstruction_returns_the_expected_volume() -> None:
    strategy = FakeReconstructionStrategy(grid_size=config.GRID_SIZE)
    projections = np.zeros((4, config.GRID_SIZE, config.GRID_SIZE), dtype=np.float32)

    volume = strategy.reconstruct(projections)

    assert volume.shape == (config.GRID_SIZE,) * 3
    assert volume.dtype == np.float32
    assert float(volume.min()) >= 0.0
    assert float(volume.max()) <= 1.0


@pytest.mark.unit
def test_fake_reconstruction_depends_on_the_projections() -> None:
    # La prueba de concurrencia necesita distinguir dos estudios por su volumen.
    strategy = FakeReconstructionStrategy(grid_size=8)
    first = np.full((4, 8, 8), 0.2, dtype=np.float32)
    second = np.full((4, 8, 8), 0.7, dtype=np.float32)

    assert not np.array_equal(strategy.reconstruct(first), strategy.reconstruct(second))


@pytest.mark.unit
def test_fake_segmentation_delivers_confidence_per_voxel() -> None:
    volume = np.zeros((config.GRID_SIZE,) * 3, dtype=np.float32)

    result = FakeSegmentationStrategy().segment(volume, "it_a")

    assert result.mask.dtype == np.uint8
    assert set(np.unique(result.mask)) <= {0, 1}
    assert result.probability.shape == result.mask.shape
    assert float(result.probability.min()) >= 0.0
    assert float(result.probability.max()) <= 1.0
    assert 0.0 <= result.global_confidence <= 1.0


@pytest.mark.unit
def test_fake_segmentation_summary_has_what_the_result_store_requires() -> None:
    strategy = FakeSegmentationStrategy()
    volume = np.zeros((config.GRID_SIZE,) * 3, dtype=np.float32)

    result = strategy.segment(volume, "it_a")
    summary = result.summary

    assert summary["study_code"] == "it_a"
    assert summary["organ"] == "lung"
    assert summary["model_name"] == strategy.model_name
    assert summary["model_version"] == strategy.model_version
    assert len(summary["regions"]) == len(result.lesions) == 1
    region, lesion = summary["regions"][0], result.lesions[0]
    assert region["location"] == lesion.location
    assert region["volume_mm3"] == lesion.volume_mm3
    assert region["confidence"] == lesion.confidence
    assert region["max_diameter_mm"] == lesion.max_diameter_mm


@pytest.mark.unit
def test_fake_segmentation_regions_match_their_mask_like_en2() -> None:
    from radvol3d.services.meshing.lesion_regions import split_lesion_masks

    volume = np.zeros((config.GRID_SIZE,) * 3, dtype=np.float32)

    result = FakeSegmentationStrategy().segment(volume, "it_a")
    region = result.summary["regions"][0]

    assert region["voxels"] == int(result.mask.sum()) == 512
    assert region["centroid_voxel"] == [64, 64, 64]
    (only,) = split_lesion_masks(result.mask, result.summary["regions"])
    assert np.array_equal(only, result.mask > 0)


@pytest.mark.unit
def test_fake_meshing_returns_organ_tumor_and_one_glb_per_region() -> None:
    mask = np.zeros((8, 8, 8), dtype=np.uint8)
    volume = np.zeros((8, 8, 8), dtype=np.float32)

    meshes = FakeMeshingStrategy().build_meshes(volume, mask, [{}, {}])

    assert isinstance(meshes, MeshSet)
    assert meshes.organ.startswith(b"glTF")
    assert meshes.tumor.startswith(b"glTF")
    assert len(meshes.lesions) == 2
    assert all(glb.startswith(b"glTF") for glb in meshes.lesions)
    assert len({meshes.organ, meshes.tumor, *meshes.lesions}) == 4


@pytest.mark.unit
def test_fake_meshing_without_regions_has_no_lesion_meshes() -> None:
    mask = np.zeros((8, 8, 8), dtype=np.uint8)

    assert FakeMeshingStrategy().build_meshes(mask, mask, []).lesions == ()


@pytest.mark.unit
def test_recording_progress_keeps_the_events_in_order() -> None:
    progress = RecordingProgress()

    progress.stage_started("it_a", StageNumber.RECONSTRUCTION)
    progress.stage_completed("it_a", StageNumber.RECONSTRUCTION, "m", "1.0.0")
    progress.stage_failed("it_a", StageNumber.SEGMENTATION)

    assert progress.events == [
        ("started", "it_a", 2),
        ("completed", "it_a", 2, "m", "1.0.0"),
        ("failed", "it_a", 3),
    ]


@pytest.mark.unit
def test_recording_progress_can_fail_on_a_chosen_event() -> None:
    progress = RecordingProgress(fail_on=("save_volume", "it_a"))

    with pytest.raises(RuntimeError):
        progress.save_volume("it_a", np.zeros((2, 2, 2), dtype=np.float32))
    progress.save_volume("it_b", np.zeros((2, 2, 2), dtype=np.float32))

    assert ("save_volume", "it_b") in progress.events


@pytest.mark.unit
def test_recording_progress_is_safe_between_threads() -> None:
    progress = RecordingProgress()

    def record(code: str) -> None:
        for _ in range(200):
            progress.stage_started(code, StageNumber.PREPROCESSING)

    threads = [threading.Thread(target=record, args=(f"it_{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(progress.events) == 800


@pytest.mark.unit
def test_four_valid_files_are_npy_without_pickle_one_per_angle() -> None:
    files = four_valid_files(seed=1)

    assert [f.angle_degrees for f in files] == list(config.PROJECTION_ANGLES)
    for projection_file in files:
        array = np.load(io.BytesIO(projection_file.content), allow_pickle=False)
        assert array.shape == (config.GRID_SIZE, config.GRID_SIZE)
        assert array.dtype == np.float32
        assert np.isfinite(array).all()
