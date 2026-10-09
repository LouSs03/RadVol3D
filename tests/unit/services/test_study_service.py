"""Pruebas del servicio de estudios con almacenes falsos y la fabrica con dobles."""

from unittest.mock import Mock, create_autospec

import numpy as np
import pytest

from radvol3d import config
from radvol3d.domain.entities import PatientDetails, StoredResult, Study
from radvol3d.domain.enums import OrganName, StageNumber, StudyStatus
from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidProjectionError,
    ModelNotAvailableError,
    StageFailedError,
)
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyRequest, StudyService
from tests.fixtures.fake_strategies import (
    FailingSegmentationStrategy,
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files, valid_array

CODE = "it_a"
PATIENT = PatientDetails(first_name="Ana", last_name="Pérez", national_id="12345678")


class Harness:
    """Servicio armado con almacenes falsos que anotan sus llamadas en un solo registro."""

    def __init__(self, segmentation_type: type = FakeSegmentationStrategy) -> None:
        self.recorder = Mock()
        self.metadata = create_autospec(StudyMetadataStore, instance=True)
        self.results = create_autospec(ResultStore, instance=True)
        self.progress = create_autospec(ProcessingProgressStore, instance=True)
        self.recorder.attach_mock(self.metadata, "metadata")
        self.recorder.attach_mock(self.results, "results")
        self.recorder.attach_mock(self.progress, "progress")
        self.finished_study = Study(CODE, OrganName.LUNG, StudyStatus.COMPLETED)
        self.metadata.get_study.return_value = self.finished_study
        self.factory = StrategyFactory(
            reconstruction_builders={"en1": FakeReconstructionStrategy},
            segmentation_builders={OrganName.LUNG: segmentation_type},
            meshing_builder=FakeMeshingStrategy,
            reconstruction_key="en1",
        )
        self.factory.preload()
        loader = ProjectionLoader()
        self.service = StudyService(
            metadata_store=self.metadata,
            result_store=self.results,
            progress_store=self.progress,
            factory=self.factory,
            pipeline=ProcessingPipeline(loader),
            loader=loader,
        )

    def request(self, **overrides) -> StudyRequest:
        values = {
            "study_code": CODE,
            "organ": OrganName.LUNG,
            "projections": four_valid_files(seed=7),
            "patient": PATIENT,
        }
        values.update(overrides)
        return StudyRequest(**values)

    def call_names(self) -> list[str]:
        return [name for name, _, _ in self.recorder.mock_calls]


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.mark.unit
def test_process_study_returns_the_finished_study(harness: Harness) -> None:
    study = harness.service.process_study(harness.request())

    assert study is harness.finished_study
    harness.metadata.get_study.assert_called_with(CODE)


@pytest.mark.unit
def test_process_study_calls_the_stores_in_order(harness: Harness) -> None:
    harness.service.process_study(harness.request())

    names = harness.call_names()
    assert names[0] == "metadata.register_study"
    assert names[1] == "progress.start_processing"
    assert names[-2] == "progress.complete_study"
    assert names[-1] == "metadata.get_study"
    middle = names[2:-2]
    assert middle.count("progress.start_stage") == 4
    assert middle.count("progress.complete_stage") == 4
    assert middle.index("metadata.save_volume") < middle.index("results.save_result")


@pytest.mark.unit
def test_register_receives_one_upload_per_angle_and_the_patient(harness: Harness) -> None:
    harness.service.process_study(harness.request())

    args = harness.metadata.register_study.call_args.args
    assert args[0] == CODE
    assert args[1] is OrganName.LUNG
    uploads = args[2]
    assert all(isinstance(u, ProjectionUpload) for u in uploads)
    assert sorted(u.angle_degrees for u in uploads) == list(config.PROJECTION_ANGLES)
    for upload in uploads:
        assert np.array_equal(upload.array, valid_array(upload.angle_degrees, seed=7))
        assert upload.original_name == f"angle_{upload.angle_degrees:03d}.npy"
    assert args[3] == PATIENT


@pytest.mark.unit
def test_complete_study_gets_the_segmentation_model_the_grid_and_the_time(
    harness: Harness,
) -> None:
    harness.service.process_study(harness.request())

    code, model_name, model_version, grid_size, total_time = (
        harness.progress.complete_study.call_args.args
    )
    assert code == CODE
    assert (model_name, model_version) == ("fake_segmentation", "0.0.0")
    assert grid_size == config.GRID_SIZE
    assert total_time > 0


@pytest.mark.unit
def test_stages_two_and_three_are_closed_with_their_models(harness: Harness) -> None:
    harness.service.process_study(harness.request())

    calls = [c.args for c in harness.progress.complete_stage.call_args_list]
    assert (CODE, StageNumber.RECONSTRUCTION, "fake_reconstruction", "0.0.0") in calls
    assert (CODE, StageNumber.SEGMENTATION, "fake_segmentation", "0.0.0") in calls


@pytest.mark.unit
def test_get_study_delegates_to_the_metadata_store(harness: Harness) -> None:
    assert harness.service.get_study(CODE) is harness.finished_study

    harness.metadata.get_study.assert_called_once_with(CODE)


@pytest.mark.unit
def test_get_result_delegates_to_the_result_store(harness: Harness) -> None:
    harness.results.get_result.return_value = StoredResult(CODE)

    assert harness.service.get_result(CODE) == StoredResult(CODE)

    harness.results.get_result.assert_called_once_with(CODE)


# ---------------------------------------------------------------------------
# Errores (historia 2; FR-031, FR-032, SC-007)
# ---------------------------------------------------------------------------


def invalid_requests(harness: Harness) -> list[StudyRequest]:
    from tests.fixtures.projection_files import png_bytes

    files = four_valid_files()
    with_png = [
        ProjectionFile(f.angle_degrees, png_bytes() if f.angle_degrees == 90 else f.content)
        for f in files
    ]
    return [
        harness.request(projections=files[:3]),
        harness.request(projections=with_png),
        harness.request(organ=OrganName.LIVER),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("case", [0, 1, 2])
def test_an_invalid_request_fails_without_registering_anything(
    harness: Harness, case: int
) -> None:
    request = invalid_requests(harness)[case]

    with pytest.raises((InvalidProjectionError, ModelNotAvailableError)):
        harness.service.process_study(request)

    harness.metadata.register_study.assert_not_called()
    assert harness.call_names() == []


@pytest.mark.unit
def test_a_failing_stage_propagates_and_the_study_is_not_completed() -> None:
    harness = Harness(segmentation_type=FailingSegmentationStrategy)

    with pytest.raises(StageFailedError) as caught:
        harness.service.process_study(harness.request())

    assert caught.value.stage_number is StageNumber.SEGMENTATION
    harness.progress.complete_study.assert_not_called()
    harness.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.SEGMENTATION)


@pytest.mark.unit
def test_a_duplicate_study_propagates_without_running_the_pipeline(harness: Harness) -> None:
    harness.metadata.register_study.side_effect = DuplicateStudyError("Ya existe it_a.")

    with pytest.raises(DuplicateStudyError):
        harness.service.process_study(harness.request())

    harness.progress.start_processing.assert_not_called()
    harness.progress.start_stage.assert_not_called()


@pytest.mark.unit
def test_no_error_or_log_contains_personal_data_of_the_patient(caplog) -> None:
    personal = (PATIENT.first_name, PATIENT.last_name, PATIENT.national_id)
    harness = Harness()
    errors: list[Exception] = []

    with caplog.at_level("DEBUG"):
        for request in invalid_requests(harness):
            try:
                harness.service.process_study(request)
            except Exception as error:  # noqa: BLE001 - se juntan todos para revisarlos
                errors.append(error)
        failing = Harness(segmentation_type=FailingSegmentationStrategy)
        try:
            failing.service.process_study(failing.request())
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    assert len(errors) == 4
    for error in errors:
        for value in personal:
            assert value not in str(error)
            assert value not in repr(error)
    for value in personal:
        assert value not in caplog.text


# ---------------------------------------------------------------------------
# Consultar y borrar (historia 3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_studies_delegates_to_the_metadata_store(harness: Harness) -> None:
    harness.metadata.list_studies.return_value = [harness.finished_study]

    assert harness.service.list_studies() == [harness.finished_study]


@pytest.mark.unit
def test_delete_study_delegates_to_the_metadata_store(harness: Harness) -> None:
    harness.service.delete_study(CODE)

    harness.metadata.delete_study.assert_called_once_with(CODE)


@pytest.mark.unit
@pytest.mark.parametrize("error_type", ["StudyNotFoundError", "StudyInProgressError"])
def test_delete_study_errors_propagate(harness: Harness, error_type: str) -> None:
    from radvol3d.domain import exceptions

    error = getattr(exceptions, error_type)("mensaje")
    harness.metadata.delete_study.side_effect = error

    with pytest.raises(type(error)):
        harness.service.delete_study(CODE)


# ---------------------------------------------------------------------------
# Flujo en tres pasos de la funcionalidad 004 (contracts/services_api_changes.md)
# ---------------------------------------------------------------------------


def pending_study(organ: OrganName = OrganName.LUNG) -> Study:
    return Study(CODE, organ, StudyStatus.PENDING)


def stored_projections() -> dict[int, np.ndarray]:
    return {angle: valid_array(angle, seed=7) for angle in config.PROJECTION_ANGLES}


@pytest.mark.unit
def test_create_study_checks_the_model_before_creating(harness: Harness) -> None:
    harness.metadata.create_study.return_value = pending_study()

    study = harness.service.create_study(CODE, OrganName.LUNG, PATIENT)

    assert study.status is StudyStatus.PENDING
    harness.metadata.create_study.assert_called_once_with(CODE, OrganName.LUNG, PATIENT)


@pytest.mark.unit
def test_create_study_for_an_organ_without_model_creates_nothing(harness: Harness) -> None:
    with pytest.raises(ModelNotAvailableError):
        harness.service.create_study(CODE, OrganName.LIVER)

    harness.metadata.create_study.assert_not_called()


@pytest.mark.unit
def test_add_projections_parses_the_files_and_stores_one_upload_per_angle(
    harness: Harness,
) -> None:
    harness.service.add_projections(CODE, four_valid_files(seed=7))

    code, uploads = harness.metadata.add_projections.call_args.args
    assert code == CODE
    assert sorted(u.angle_degrees for u in uploads) == list(config.PROJECTION_ANGLES)
    for upload in uploads:
        assert np.array_equal(upload.array, valid_array(upload.angle_degrees, seed=7))
        assert upload.original_name == f"angle_{upload.angle_degrees:03d}.npy"


@pytest.mark.unit
def test_add_projections_with_an_invalid_file_touches_nothing(harness: Harness) -> None:
    files = four_valid_files()
    files[1] = ProjectionFile(45, b"no es un npy", "angle_045.npy")

    with pytest.raises(InvalidProjectionError, match="45"):
        harness.service.add_projections(CODE, files)

    assert harness.call_names() == []


@pytest.mark.unit
def test_start_processing_claims_the_study_with_the_model_check(harness: Harness) -> None:
    harness.service.start_processing(CODE)

    code, check = harness.metadata.claim_for_processing.call_args.args
    assert code == CODE
    check(OrganName.LUNG)  # hay modelo: no lanza
    with pytest.raises(ModelNotAvailableError):
        check(OrganName.LIVER)
    # No vuelve a leer el estudio: cada ida a la base cuesta (SC-002).
    harness.metadata.get_study.assert_not_called()


@pytest.mark.unit
def test_start_processing_without_a_model_propagates_the_error(harness: Harness) -> None:
    # La persistencia lanza el error del chequeo dentro de la transaccion y la revierte.
    harness.metadata.claim_for_processing.side_effect = ModelNotAvailableError("sin modelo")

    with pytest.raises(ModelNotAvailableError):
        harness.service.start_processing(CODE)


@pytest.mark.unit
def test_run_processing_runs_the_pipeline_and_completes_the_study(harness: Harness) -> None:
    harness.metadata.get_study.return_value = pending_study()
    harness.metadata.load_projections.return_value = stored_projections()

    harness.service.run_processing(CODE)

    names = harness.call_names()
    assert names.count("progress.start_stage") == 4
    assert names.index("metadata.save_volume") < names.index("results.save_result")
    harness.progress.complete_study.assert_called_once()
    harness.progress.start_processing.assert_not_called()


@pytest.mark.unit
def test_run_processing_never_raises_when_a_stage_fails(caplog) -> None:
    harness = Harness(segmentation_type=FailingSegmentationStrategy)
    harness.metadata.get_study.return_value = pending_study()
    harness.metadata.load_projections.return_value = stored_projections()

    with caplog.at_level("ERROR"):
        harness.service.run_processing(CODE)

    # La tuberia ya registro el fallo; el servicio no lo vuelve a marcar.
    harness.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.SEGMENTATION)
    harness.progress.complete_study.assert_not_called()
    assert CODE in caplog.text
    assert "detalle interno" not in caplog.text


@pytest.mark.unit
def test_run_processing_fails_from_stage_one_when_the_projections_cannot_be_read(
    harness: Harness, caplog
) -> None:
    from radvol3d.domain.exceptions import StorageError

    harness.metadata.get_study.return_value = pending_study()
    harness.metadata.load_projections.side_effect = StorageError("bucket caido con una-clave")

    with caplog.at_level("ERROR"):
        harness.service.run_processing(CODE)

    harness.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.PREPROCESSING)
    assert "StorageError" in caplog.text
    assert CODE in caplog.text
    assert "una-clave" not in caplog.text


@pytest.mark.unit
def test_run_processing_fails_the_last_stage_when_closing_the_study_fails(
    harness: Harness,
) -> None:
    harness.metadata.get_study.return_value = pending_study()
    harness.metadata.load_projections.return_value = stored_projections()
    harness.progress.complete_study.side_effect = RuntimeError("se cayo la base")

    harness.service.run_processing(CODE)

    harness.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.MESHING)


@pytest.mark.unit
def test_run_processing_survives_when_recording_the_failure_also_fails(
    harness: Harness, caplog
) -> None:
    harness.metadata.get_study.return_value = pending_study()
    harness.metadata.load_projections.side_effect = RuntimeError("primero")
    harness.progress.fail_from_stage.side_effect = RuntimeError("despues")

    with caplog.at_level("ERROR"):
        harness.service.run_processing(CODE)

    assert "primero" not in caplog.text
    assert "despues" not in caplog.text


@pytest.mark.unit
def test_recover_interrupted_studies_delegates_to_the_progress_store(harness: Harness) -> None:
    harness.progress.fail_interrupted_studies.return_value = ["it_a", "it_b"]

    assert harness.service.recover_interrupted_studies() == ["it_a", "it_b"]


# ---------------------------------------------------------------------------
# Resultado y descargas (funcionalidad 004, historia 3)
# ---------------------------------------------------------------------------


def stored_result() -> StoredResult:
    return StoredResult(CODE, volume_path=f"{CODE}/volume.npy")


@pytest.mark.unit
@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
def test_the_result_of_a_study_that_is_not_completed_is_rejected_with_its_state(
    harness: Harness, status: str
) -> None:
    from radvol3d.domain.enums import ResultFile
    from radvol3d.domain.exceptions import InvalidStudyStateError

    harness.metadata.get_study.return_value = Study(CODE, OrganName.LUNG, StudyStatus(status))

    for call in (
        lambda: harness.service.get_completed_result(CODE),
        lambda: harness.service.read_result_file(CODE, ResultFile.ORGAN_MESH),
        lambda: harness.service.read_lesion_mesh(CODE, 1),
    ):
        with pytest.raises(InvalidStudyStateError, match=status):
            call()

    harness.results.get_result.assert_not_called()
    harness.results.read_file.assert_not_called()
    harness.results.read_lesion_mesh.assert_not_called()


@pytest.mark.unit
def test_a_completed_study_delegates_its_result_and_files_to_the_result_store(
    harness: Harness,
) -> None:
    from radvol3d.domain.enums import ResultFile

    harness.results.get_result.return_value = stored_result()
    harness.results.read_file.return_value = b"glTF-organ"
    harness.results.read_lesion_mesh.return_value = b"glTF-1"

    assert harness.service.get_completed_result(CODE) == stored_result()
    assert harness.service.read_result_file(CODE, ResultFile.ORGAN_MESH) == b"glTF-organ"
    assert harness.service.read_lesion_mesh(CODE, 1) == b"glTF-1"
    harness.results.read_file.assert_called_once_with(CODE, ResultFile.ORGAN_MESH)
    harness.results.read_lesion_mesh.assert_called_once_with(CODE, 1)
