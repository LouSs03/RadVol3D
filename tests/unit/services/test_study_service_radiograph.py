"""Pruebas del servicio de estudios en el modo de una radiografia (almacenes falsos)."""

from unittest.mock import Mock, create_autospec

import pytest

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import InputMode, OrganName, RemoteJobState, StudyStatus
from radvol3d.domain.exceptions import (
    InvalidRadiographError,
    ReconstructionServiceUnavailableError,
)
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard
from radvol3d.services.segmentation.pending_segmentation_strategy import (
    PendingSegmentationStrategy,
)
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyService
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeRadiographReconstructionStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.radiograph_files import fake_dicom

CODE = "rx_001"


class Harness:
    def __init__(self, reconstruction=None, configured: bool = True) -> None:
        self.recorder = Mock()
        self.metadata = create_autospec(StudyMetadataStore, instance=True)
        self.results = create_autospec(ResultStore, instance=True)
        self.progress = create_autospec(ProcessingProgressStore, instance=True)
        self.recorder.attach_mock(self.metadata, "metadata")
        self.recorder.attach_mock(self.progress, "progress")
        self.recorder.attach_mock(self.results, "results")
        self.reconstruction = reconstruction or FakeRadiographReconstructionStrategy()
        self.factory = StrategyFactory(
            reconstruction_builders={"en1": FakeReconstructionStrategy},
            segmentation_builders={OrganName.LUNG: FakeSegmentationStrategy},
            meshing_builder=FakeMeshingStrategy,
            reconstruction_key="en1",
            radiograph_reconstruction_builder=(lambda: self.reconstruction) if configured else None,
            radiograph_segmentation_builders={OrganName.LUNG: PendingSegmentationStrategy},
        )
        self.factory.preload()
        self.board = RemoteJobBoard()
        loader = ProjectionLoader()
        self.service = StudyService(
            metadata_store=self.metadata,
            result_store=self.results,
            progress_store=self.progress,
            factory=self.factory,
            pipeline=ProcessingPipeline(loader, self.board),
            loader=loader,
            board=self.board,
        )

    def call_names(self) -> list[str]:
        return [name for name, _, _ in self.recorder.mock_calls]


def radiograph_study(status: StudyStatus = StudyStatus.PROCESSING) -> Study:
    return Study(CODE, OrganName.LUNG, status, input_mode=InputMode.RADIOGRAPH)


@pytest.mark.unit
def test_a_radiograph_study_is_created_with_its_mode() -> None:
    harness = Harness()

    harness.service.create_study(CODE, OrganName.LUNG, None, InputMode.RADIOGRAPH)

    harness.metadata.create_study.assert_called_once_with(
        CODE, OrganName.LUNG, None, input_mode=InputMode.RADIOGRAPH
    )


@pytest.mark.unit
def test_the_radiograph_mode_only_accepts_the_lung() -> None:
    harness = Harness()

    with pytest.raises(InvalidRadiographError, match="pulmón"):
        harness.service.create_study(CODE, OrganName.LIVER, None, InputMode.RADIOGRAPH)

    harness.metadata.create_study.assert_not_called()


@pytest.mark.unit
def test_a_valid_dicom_is_stored_and_an_invalid_one_never_reaches_the_store() -> None:
    harness = Harness()

    harness.service.add_radiograph(CODE, fake_dicom(), "placa.dcm")
    with pytest.raises(InvalidRadiographError):
        harness.service.add_radiograph(CODE, b"%PDF" * 100, "placa.dcm")

    harness.metadata.add_radiograph.assert_called_once_with(CODE, fake_dicom())


@pytest.mark.unit
def test_the_claim_check_asks_the_remote_service_in_radiograph_mode() -> None:
    harness = Harness(FakeRadiographReconstructionStrategy(available=False))

    harness.service.start_processing(CODE)
    code, check = harness.metadata.claim_for_processing.call_args.args

    assert code == CODE
    check(OrganName.LUNG)  # cuatro proyecciones: hay modelo, no lanza
    with pytest.raises(ReconstructionServiceUnavailableError):
        check(OrganName.LUNG, InputMode.RADIOGRAPH)


@pytest.mark.unit
def test_run_processing_of_a_radiograph_runs_its_pipeline_and_completes() -> None:
    harness = Harness()
    harness.metadata.get_study.return_value = radiograph_study()
    harness.metadata.load_radiograph.return_value = fake_dicom()

    harness.service.run_processing(CODE)

    names = harness.call_names()
    assert "metadata.load_projections" not in names
    assert names.count("progress.start_stage") == 4
    assert names.index("metadata.save_volume") < names.index("results.save_result")
    model_name, model_version = harness.progress.complete_study.call_args.args[1:3]
    assert (model_name, model_version) == ("fake_radiograph_reconstruction", "0.0.0")
    assert harness.reconstruction.received == [fake_dicom()]


@pytest.mark.unit
def test_a_radiograph_study_fails_from_stage_1_when_the_mode_is_not_configured() -> None:
    harness = Harness(configured=False)
    harness.metadata.get_study.return_value = radiograph_study()

    harness.service.run_processing(CODE)

    harness.progress.fail_from_stage.assert_called_once()
    assert harness.progress.fail_from_stage.call_args.args[1].value == 1


@pytest.mark.unit
def test_the_remote_state_comes_from_the_board() -> None:
    harness = Harness()
    harness.board.update(CODE, RemoteJobState.RUNNING)

    assert harness.service.remote_state(CODE) is RemoteJobState.RUNNING
    assert harness.service.remote_state("otro") is None


@pytest.mark.unit
def test_mode_availability_follows_the_service_and_the_configuration() -> None:
    assert Harness().service.radiograph_mode_available() is True
    assert (
        Harness(
            FakeRadiographReconstructionStrategy(available=False)
        ).service.radiograph_mode_available()
        is False
    )
    assert Harness(configured=False).service.radiograph_mode_available() is False
