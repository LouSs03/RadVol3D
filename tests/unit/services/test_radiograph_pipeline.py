"""Pruebas de la tuberia del modo de una radiografia, con RecordingProgress."""

import pytest

from radvol3d.domain.enums import RemoteJobState
from radvol3d.domain.exceptions import StageFailedError
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard
from radvol3d.services.segmentation.pending_segmentation_strategy import (
    PendingSegmentationStrategy,
)
from radvol3d.services.strategy_factory import RadiographStrategySet
from tests.fixtures.fake_progress import RecordingProgress
from tests.fixtures.fake_strategies import (
    FailingRadiographReconstructionStrategy,
    FakeMeshingStrategy,
    FakeRadiographReconstructionStrategy,
)
from tests.fixtures.radiograph_files import fake_dicom

CODE = "rx_001"


def strategies(reconstruction=None) -> RadiographStrategySet:
    return RadiographStrategySet(
        reconstruction=reconstruction or FakeRadiographReconstructionStrategy(),
        segmentation=PendingSegmentationStrategy(),
        meshing=FakeMeshingStrategy(),
    )


@pytest.mark.unit
def test_the_four_stages_run_in_order_with_the_remote_model_in_stage_2() -> None:
    progress = RecordingProgress()
    reconstruction = FakeRadiographReconstructionStrategy()

    data = ProcessingPipeline(ProjectionLoader()).run_radiograph(
        CODE, fake_dicom(), strategies(reconstruction), progress
    )

    assert progress.events == [
        ("started", CODE, 1),
        ("completed", CODE, 1, None, None),
        ("started", CODE, 2),
        ("save_volume", CODE),
        ("completed", CODE, 2, "fake_radiograph_reconstruction", "0.0.0"),
        ("started", CODE, 3),
        ("completed", CODE, 3, "segmentation_pending", "0"),
        ("started", CODE, 4),
        ("save_result", CODE),
        ("completed", CODE, 4, None, None),
    ]
    assert reconstruction.received == [fake_dicom()]
    assert data.segmentation.lesions == []
    assert data.meshes.lesions == ()


@pytest.mark.unit
def test_a_file_that_is_not_dicom_fails_in_stage_1() -> None:
    progress = RecordingProgress()

    with pytest.raises(StageFailedError) as caught:
        ProcessingPipeline(ProjectionLoader()).run_radiograph(
            CODE, b"no es dicom" * 50, strategies(), progress
        )

    assert caught.value.stage_number.value == 1
    assert ("failed", CODE, 1) in progress.events


@pytest.mark.unit
def test_a_failing_service_fails_stage_2_and_clears_the_board() -> None:
    progress = RecordingProgress()
    board = RemoteJobBoard()
    board.update(CODE, RemoteJobState.RUNNING)

    with pytest.raises(StageFailedError) as caught:
        ProcessingPipeline(ProjectionLoader(), board).run_radiograph(
            CODE, fake_dicom(), strategies(FailingRadiographReconstructionStrategy()), progress
        )

    assert caught.value.stage_number.value == 2
    assert board.get(CODE) is None


@pytest.mark.unit
def test_the_states_of_the_remote_job_reach_the_board() -> None:
    board = RemoteJobBoard()
    seen: list = []

    class Spy(FakeRadiographReconstructionStrategy):
        def reconstruct(self, radiograph, report=None):
            report(RemoteJobState.QUEUED)
            seen.append(board.get(CODE))
            report(RemoteJobState.RUNNING)
            seen.append(board.get(CODE))
            return super().reconstruct(radiograph)

    ProcessingPipeline(ProjectionLoader(), board).run_radiograph(
        CODE, fake_dicom(), strategies(Spy()), RecordingProgress()
    )

    assert seen == [RemoteJobState.QUEUED, RemoteJobState.RUNNING]
    assert board.get(CODE) is None
