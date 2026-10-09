"""Pruebas de los cuatro filtros de la tuberia (research.md R6), con los dobles."""

import numpy as np
import pytest

from radvol3d import config
from radvol3d.domain.enums import StageNumber
from radvol3d.services.pipeline.filters import (
    MeshingFilter,
    PreprocessingFilter,
    ReconstructionFilter,
    SegmentationFilter,
)
from radvol3d.services.pipeline.pipeline_data import PipelineData
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files, valid_array

CODE = "it_a"


def initial_data(seed: int = 0) -> PipelineData:
    parsed = ProjectionLoader().parse(four_valid_files(seed=seed))
    return PipelineData(study_code=CODE, projections_by_angle=parsed)


def after_reconstruction() -> PipelineData:
    data = PreprocessingFilter(ProjectionLoader()).apply(initial_data())
    return ReconstructionFilter(FakeReconstructionStrategy()).apply(data)


@pytest.mark.unit
def test_preprocessing_stacks_the_projections_in_angle_order() -> None:
    data = initial_data(seed=4)

    result = PreprocessingFilter(ProjectionLoader()).apply(data)

    assert result.projections.shape == (4, config.GRID_SIZE, config.GRID_SIZE)
    assert result.projections.dtype == np.float32
    for position, angle in enumerate(config.PROJECTION_ANGLES):
        assert np.array_equal(result.projections[position], valid_array(angle, seed=4))


@pytest.mark.unit
def test_reconstruction_fills_the_volume_and_exposes_its_model() -> None:
    strategy = FakeReconstructionStrategy()
    stage = ReconstructionFilter(strategy)
    data = PreprocessingFilter(ProjectionLoader()).apply(initial_data())

    result = stage.apply(data)

    assert result.volume.shape == (config.GRID_SIZE,) * 3
    assert stage.model == (strategy.model_name, strategy.model_version)


@pytest.mark.unit
def test_segmentation_receives_the_study_code_and_fills_the_result() -> None:
    strategy = FakeSegmentationStrategy()
    stage = SegmentationFilter(strategy)

    result = stage.apply(after_reconstruction())

    assert result.segmentation.summary["study_code"] == CODE
    assert stage.model == ("fake_segmentation", "0.0.0")


@pytest.mark.unit
def test_meshing_uses_the_volume_the_mask_and_the_regions_with_lesion() -> None:
    received = {}

    class SpyMeshing(FakeMeshingStrategy):
        def build_meshes(self, volume, mask, regions):
            received["volume"], received["mask"] = volume, mask
            received["regions"] = list(regions)
            return super().build_meshes(volume, mask, regions)

    data = SegmentationFilter(FakeSegmentationStrategy()).apply(after_reconstruction())
    with_lesion = data.segmentation.summary["regions"][0]
    data.segmentation.summary["regions"].append({"has_lesion": False, "location": "x"})

    result = MeshingFilter(SpyMeshing()).apply(data)

    assert received["volume"] is data.volume
    assert received["mask"] is data.segmentation.mask
    assert received["regions"] == [with_lesion]
    assert result.meshes.tumor.startswith(b"glTF")
    assert len(result.meshes.lesions) == 1


@pytest.mark.unit
def test_stage_numbers_and_models_are_the_ones_of_each_stage() -> None:
    stages = [
        PreprocessingFilter(ProjectionLoader()),
        ReconstructionFilter(FakeReconstructionStrategy()),
        SegmentationFilter(FakeSegmentationStrategy()),
        MeshingFilter(FakeMeshingStrategy()),
    ]

    assert [s.stage_number for s in stages] == list(StageNumber)
    assert stages[0].model is None
    assert stages[3].model is None


@pytest.mark.unit
def test_no_filter_modifies_the_data_it_receives() -> None:
    data = initial_data()
    stages = [
        PreprocessingFilter(ProjectionLoader()),
        ReconstructionFilter(FakeReconstructionStrategy()),
        SegmentationFilter(FakeSegmentationStrategy()),
        MeshingFilter(FakeMeshingStrategy()),
    ]

    for stage in stages:
        before = (data.projections, data.volume, data.segmentation, data.meshes)
        result = stage.apply(data)
        assert (data.projections, data.volume, data.segmentation, data.meshes) == before
        assert result is not data
        data = result
