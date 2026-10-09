"""Pruebas del adaptador PersistenceProgress: traduce el puerto a los almacenes."""

from unittest.mock import create_autospec

import numpy as np
import pytest

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import StageNumber
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.meshing_strategy import MeshSet
from radvol3d.services.pipeline.persistence_progress import PersistenceProgress

CODE = "it_a"


@pytest.fixture
def stores():
    return (
        create_autospec(ProcessingProgressStore, instance=True),
        create_autospec(StudyMetadataStore, instance=True),
        create_autospec(ResultStore, instance=True),
    )


@pytest.fixture
def progress(stores) -> PersistenceProgress:
    return PersistenceProgress(*stores)


@pytest.mark.unit
def test_stage_started_starts_the_stage(stores, progress: PersistenceProgress) -> None:
    progress.stage_started(CODE, StageNumber.RECONSTRUCTION)

    stores[0].start_stage.assert_called_once_with(CODE, StageNumber.RECONSTRUCTION)


@pytest.mark.unit
def test_stage_completed_passes_the_model(stores, progress: PersistenceProgress) -> None:
    progress.stage_completed(CODE, StageNumber.SEGMENTATION, "segmentation_lung", "1.0.0")

    stores[0].complete_stage.assert_called_once_with(
        CODE, StageNumber.SEGMENTATION, "segmentation_lung", "1.0.0"
    )


@pytest.mark.unit
def test_stage_completed_without_a_model(stores, progress: PersistenceProgress) -> None:
    progress.stage_completed(CODE, StageNumber.MESHING)

    stores[0].complete_stage.assert_called_once_with(CODE, StageNumber.MESHING, None, None)


@pytest.mark.unit
def test_save_volume_goes_to_the_metadata_store(stores, progress: PersistenceProgress) -> None:
    volume = np.zeros((2, 2, 2), dtype=np.float32)

    progress.save_volume(CODE, volume)

    stores[1].save_volume.assert_called_once_with(CODE, volume)


@pytest.mark.unit
def test_save_result_passes_mask_probability_summary_and_both_meshes(
    stores, progress: PersistenceProgress
) -> None:
    mask = np.zeros((2, 2, 2), dtype=np.uint8)
    probability = np.zeros((2, 2, 2), dtype=np.float32)
    summary = {"model_name": "m", "model_version": "1.0.0", "regions": []}
    segmentation = SegmentationResult(mask, probability, 0.9, summary=summary)
    meshes = MeshSet(organ=b"glTF-organ", tumor=b"glTF-tumor")

    progress.save_result(CODE, segmentation, meshes)

    stores[2].save_result.assert_called_once_with(
        CODE, mask, probability, summary, b"glTF-organ", b"glTF-tumor"
    )


@pytest.mark.unit
def test_stage_failed_fails_from_that_stage(stores, progress: PersistenceProgress) -> None:
    progress.stage_failed(CODE, StageNumber.SEGMENTATION)

    stores[0].fail_from_stage.assert_called_once_with(CODE, StageNumber.SEGMENTATION)
