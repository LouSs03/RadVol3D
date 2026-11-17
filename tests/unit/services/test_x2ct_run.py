"""Pruebas de las etapas del modo de una radiografia con X2CT-GAN (almacenes falsos)."""

from unittest.mock import Mock, call, create_autospec

import numpy as np
import pytest

from radvol3d.domain.enums import InputMode, OrganName, StageNumber, StudyStatus
from radvol3d.domain.exceptions import InvalidRadiographError, StageFailedError
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.radiograph_result_store import RadiographResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.radiograph_surface import RadiographSurface
from radvol3d.services.pipeline.x2ct_run import X2ctRadiographRun
from radvol3d.services.reconstruction.x2ct_strategy import MODEL_NAME, MODEL_VERSION, X2ctStrategy
from tests.fixtures.radiograph_files import fake_dicom
from tests.fixtures.x2ct_fakes import FakeX2ctReconstructor

CODE = "rx_x2ct"


class Harness:
    def __init__(self, reconstructor=None) -> None:
        self.recorder = Mock()
        self.progress = create_autospec(ProcessingProgressStore, instance=True)
        self.metadata = create_autospec(StudyMetadataStore, instance=True)
        self.results = create_autospec(RadiographResultStore, instance=True)
        self.surface = create_autospec(RadiographSurface, instance=True)
        self.surface.build.return_value = b"glTF-superficie"
        for name in ("progress", "metadata", "results", "surface"):
            self.recorder.attach_mock(getattr(self, name), name)
        self.strategy = X2ctStrategy(reconstructor or FakeX2ctReconstructor())
        self.run = X2ctRadiographRun(self.progress, self.metadata, self.results, self.surface)


@pytest.mark.unit
def test_the_stages_run_in_order_and_segmentation_is_skipped() -> None:
    h = Harness()

    result = h.run.run(CODE, fake_dicom(), h.strategy, started=0.0)

    names = [c[0] for c in h.recorder.mock_calls]
    assert names == [
        "progress.start_stage",
        "progress.complete_stage",
        "progress.start_stage",
        "metadata.save_volume",
        "results.save_reconstruction",
        "progress.complete_stage",
        "progress.skip_stage",
        "progress.start_stage",
        "surface.build",
        "results.save_organ_mesh",
        "progress.complete_stage",
        "progress.complete_study",
    ]
    h.progress.skip_stage.assert_called_once_with(CODE, StageNumber.SEGMENTATION)
    assert call(CODE, StageNumber.RECONSTRUCTION, MODEL_NAME, MODEL_VERSION) in (
        h.progress.complete_stage.call_args_list
    )
    h.results.save_organ_mesh.assert_called_once_with(CODE, b"glTF-superficie")
    assert h.progress.complete_study.call_args.args[:4] == (CODE, MODEL_NAME, MODEL_VERSION, 128)
    np.testing.assert_array_equal(h.metadata.save_volume.call_args.args[1], result.volume)


@pytest.mark.unit
def test_the_surface_uses_the_voxel_of_the_reconstruction() -> None:
    h = Harness()

    result = h.run.run(CODE, fake_dicom(), h.strategy, started=0.0)

    assert h.surface.build.call_args.args[1] == result.voxel_mm


@pytest.mark.unit
def test_the_output_package_and_the_view_are_saved_with_the_study() -> None:
    h = Harness()

    h.run.run(CODE, fake_dicom(), h.strategy, started=0.0)

    code, files, view = h.results.save_reconstruction.call_args.args
    assert code == CODE
    assert set(files) == {"volumen.nii.gz", "entrada_modelo_128.png", "metadatos.json"}
    assert set(view) >= {"voxel_mm", "relative_measurements", "warnings"}


@pytest.mark.unit
def test_an_invalid_dicom_fails_in_stage_one_and_nothing_is_reconstructed() -> None:
    model = FakeX2ctReconstructor()
    h = Harness(model)

    with pytest.raises(StageFailedError):
        h.run.run(CODE, b"no es un dicom", h.strategy, started=0.0)

    h.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.PREPROCESSING)
    assert model.inputs == []
    h.progress.complete_study.assert_not_called()


@pytest.mark.unit
def test_a_model_error_fails_in_stage_two() -> None:
    model = FakeX2ctReconstructor()
    model.reconstruir = Mock(side_effect=RuntimeError("detalle interno"))
    h = Harness(model)

    with pytest.raises(StageFailedError) as caught:
        h.run.run(CODE, fake_dicom(), h.strategy, started=0.0)

    assert isinstance(caught.value.__cause__, RuntimeError)
    h.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.RECONSTRUCTION)
    h.progress.skip_stage.assert_not_called()


@pytest.mark.unit
def test_a_surface_error_fails_in_the_visualization_stage() -> None:
    h = Harness()
    h.surface.build.side_effect = ValueError("sin superficie")

    with pytest.raises(StageFailedError):
        h.run.run(CODE, fake_dicom(), h.strategy, started=0.0)

    h.progress.fail_from_stage.assert_called_once_with(CODE, StageNumber.MESHING)


@pytest.mark.unit
def test_validate_rejects_what_the_upload_would_reject() -> None:
    from radvol3d.services.pipeline.radiograph_check import validate_radiograph

    with pytest.raises(InvalidRadiographError):
        validate_radiograph(b"no es un dicom")


# --- StudyService: el modo de una radiografia con X2CT-GAN va por su camino ----------


def study_service_with_x2ct(run: X2ctRadiographRun | None, reconstruction):
    from radvol3d.persistence.result_store import ResultStore
    from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
    from radvol3d.services.pipeline.projection_loader import ProjectionLoader
    from radvol3d.services.segmentation.pending_segmentation_strategy import (
        PendingSegmentationStrategy,
    )
    from radvol3d.services.strategy_factory import StrategyFactory
    from radvol3d.services.study_service import StudyService
    from tests.fixtures.fake_strategies import (
        FakeMeshingStrategy,
        FakeReconstructionStrategy,
        FakeSegmentationStrategy,
    )

    factory = StrategyFactory(
        reconstruction_builders={"en1": FakeReconstructionStrategy},
        segmentation_builders={OrganName.LUNG: FakeSegmentationStrategy},
        meshing_builder=FakeMeshingStrategy,
        reconstruction_key="en1",
        radiograph_reconstruction_builder=lambda: reconstruction,
        radiograph_segmentation_builders={OrganName.LUNG: PendingSegmentationStrategy},
    )
    factory.preload()
    metadata = create_autospec(StudyMetadataStore, instance=True)
    progress = create_autospec(ProcessingProgressStore, instance=True)
    pipeline = create_autospec(ProcessingPipeline, instance=True)
    service = StudyService(
        metadata_store=metadata,
        result_store=create_autospec(ResultStore, instance=True),
        progress_store=progress,
        factory=factory,
        pipeline=pipeline,
        loader=ProjectionLoader(),
        radiograph_results=create_autospec(RadiographResultStore, instance=True),
        x2ct_run=run,
    )
    return service, metadata, progress, pipeline


def radiograph_study():
    from radvol3d.domain.entities import Study

    return Study(CODE, OrganName.LUNG, StudyStatus.PROCESSING, input_mode=InputMode.RADIOGRAPH)


@pytest.mark.unit
def test_study_service_sends_an_x2ct_study_to_its_own_run() -> None:
    run = create_autospec(X2ctRadiographRun, instance=True)
    strategy = X2ctStrategy(FakeX2ctReconstructor())
    service, metadata, progress, pipeline = study_service_with_x2ct(run, strategy)
    metadata.get_study.return_value = radiograph_study()
    metadata.load_radiograph.return_value = fake_dicom()

    service.run_processing(CODE)

    run.run.assert_called_once()
    assert run.run.call_args.args[:3] == (CODE, fake_dicom(), strategy)
    pipeline.run_radiograph.assert_not_called()
    progress.fail_from_stage.assert_not_called()


@pytest.mark.unit
def test_study_service_keeps_the_axon_path_for_other_engines() -> None:
    from tests.fixtures.fake_strategies import FakeRadiographReconstructionStrategy

    run = create_autospec(X2ctRadiographRun, instance=True)
    service, metadata, _, pipeline = study_service_with_x2ct(
        run, FakeRadiographReconstructionStrategy()
    )
    metadata.get_study.return_value = radiograph_study()
    metadata.load_radiograph.return_value = fake_dicom()
    pipeline.run_radiograph.return_value = Mock(volume=np.zeros((128, 128, 128), np.float32))

    service.run_processing(CODE)

    run.run.assert_not_called()
    pipeline.run_radiograph.assert_called_once()


@pytest.mark.unit
def test_with_x2ct_the_mode_is_available_without_axon() -> None:
    service, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))

    assert service.radiograph_mode_available() is True


# --- StudyService: datos del visor del modo de una radiografia ----------------------


def completed_study(input_mode=InputMode.RADIOGRAPH, model=None):
    from radvol3d.domain.entities import Study

    return Study(CODE, OrganName.LUNG, StudyStatus.COMPLETED, input_mode=input_mode, model=model)


@pytest.mark.unit
def test_the_view_of_an_x2ct_study_comes_from_its_store() -> None:
    service, metadata, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))
    metadata.get_study.return_value = completed_study()
    service._radiograph_results.has_view.return_value = True
    service._radiograph_results.read_view.return_value = {"voxel_mm": [3, 3, 3]}

    assert service.radiograph_view(CODE) == {"voxel_mm": [3, 3, 3]}


@pytest.mark.unit
def test_a_study_reconstructed_with_axon_is_shown_with_the_system_grid() -> None:
    from radvol3d import config
    from radvol3d.domain.entities import Model

    service, metadata, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))
    metadata.get_study.return_value = completed_study(
        model=Model("reconstruction_axon_coarsediff", "remote-1")
    )
    service._radiograph_results.has_view.return_value = False

    view = service.radiograph_view(CODE)

    assert view["voxel_mm"] == [config.MM_PER_VOXEL] * 3
    assert view["relative_measurements"] is False
    assert view["has_reconstruction_files"] is False
    assert view["model_name"] == "reconstruction_axon_coarsediff"


@pytest.mark.unit
def test_a_study_of_four_projections_has_no_radiograph_view() -> None:
    from radvol3d.domain.exceptions import InvalidStudyStateError

    service, metadata, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))
    metadata.get_study.return_value = completed_study(InputMode.PROJECTIONS)

    with pytest.raises(InvalidStudyStateError):
        service.radiograph_view(CODE)


@pytest.mark.unit
def test_an_unfinished_study_has_no_radiograph_view_nor_files() -> None:
    from radvol3d.domain.entities import Study
    from radvol3d.domain.exceptions import InvalidStudyStateError

    service, metadata, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))
    metadata.get_study.return_value = Study(
        CODE, OrganName.LUNG, StudyStatus.PROCESSING, input_mode=InputMode.RADIOGRAPH
    )

    with pytest.raises(InvalidStudyStateError):
        service.radiograph_view(CODE)
    with pytest.raises(InvalidStudyStateError):
        service.read_radiograph_output(CODE, "metadatos.json")


@pytest.mark.unit
def test_the_x2ct_files_are_read_from_its_store() -> None:
    service, metadata, *_ = study_service_with_x2ct(None, X2ctStrategy(FakeX2ctReconstructor()))
    metadata.get_study.return_value = completed_study()
    service._radiograph_results.read_file.return_value = b"{}"

    assert service.read_radiograph_output(CODE, "metadatos.json") == b"{}"
    service._radiograph_results.read_file.assert_called_once_with(CODE, "metadatos.json")
