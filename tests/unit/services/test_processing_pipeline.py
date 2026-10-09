"""Pruebas de la tuberia (FR-006, FR-007; research.md R6), con RecordingProgress."""

import inspect

import pytest

from radvol3d import config
from radvol3d.domain.exceptions import StageFailedError
from radvol3d.services.pipeline import processing_pipeline
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.strategy_factory import StrategySet
from tests.fixtures.fake_progress import RecordingProgress
from tests.fixtures.fake_strategies import (
    INTERNAL_DETAIL,
    FailingMeshingStrategy,
    FailingReconstructionStrategy,
    FailingSegmentationStrategy,
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files

CODE = "it_a"


def fake_strategies() -> StrategySet:
    return StrategySet(
        reconstruction=FakeReconstructionStrategy(),
        segmentation=FakeSegmentationStrategy(),
        meshing=FakeMeshingStrategy(),
    )


def run(progress: RecordingProgress, code: str = CODE, seed: int = 0):
    loader = ProjectionLoader()
    parsed = loader.parse(four_valid_files(seed=seed))
    return ProcessingPipeline(loader).run(code, parsed, fake_strategies(), progress)


@pytest.mark.unit
def test_the_four_stages_run_in_order_and_each_one_is_recorded() -> None:
    progress = RecordingProgress()

    run(progress)

    assert progress.events == [
        ("started", CODE, 1),
        ("completed", CODE, 1, None, None),
        ("started", CODE, 2),
        ("save_volume", CODE),
        ("completed", CODE, 2, "fake_reconstruction", "0.0.0"),
        ("started", CODE, 3),
        ("completed", CODE, 3, "fake_segmentation", "0.0.0"),
        ("started", CODE, 4),
        ("save_result", CODE),
        ("completed", CODE, 4, None, None),
    ]


@pytest.mark.unit
def test_run_returns_the_data_with_the_four_outputs() -> None:
    data = run(RecordingProgress())

    assert data.study_code == CODE
    assert data.projections.shape == (4, config.GRID_SIZE, config.GRID_SIZE)
    assert data.volume.shape == (config.GRID_SIZE,) * 3
    assert data.segmentation.mask.shape == data.volume.shape
    assert data.meshes.organ.startswith(b"glTF")


@pytest.mark.unit
def test_what_is_saved_is_what_the_stages_produced() -> None:
    progress = RecordingProgress()

    data = run(progress)

    assert progress.volumes[CODE] is data.volume
    segmentation, meshes = progress.results[CODE]
    assert segmentation is data.segmentation
    assert meshes is data.meshes


@pytest.mark.unit
def test_the_pipeline_keeps_no_state_between_runs() -> None:
    loader = ProjectionLoader()
    pipeline = ProcessingPipeline(loader)
    progress = RecordingProgress()

    first = pipeline.run("it_a", loader.parse(four_valid_files(seed=1)), fake_strategies(), progress)
    second = pipeline.run("it_b", loader.parse(four_valid_files(seed=2)), fake_strategies(), progress)

    assert first.study_code == "it_a"
    assert second.study_code == "it_b"
    assert float(first.volume[0, 0, 0]) != float(second.volume[0, 0, 0])


@pytest.mark.unit
def test_the_pipeline_has_no_condition_on_the_organ() -> None:
    source = inspect.getsource(processing_pipeline)

    assert "organ" not in source


# ---------------------------------------------------------------------------
# Fallos (historia 2, escenario 4; FR-008)
# ---------------------------------------------------------------------------


class FailingLoader(ProjectionLoader):
    """Falla al apilar: hace fallar la etapa 1."""

    def stack(self, by_angle):
        raise RuntimeError(INTERNAL_DETAIL)


def strategies_failing_at(stage: int) -> StrategySet:
    return StrategySet(
        reconstruction=(
            FailingReconstructionStrategy() if stage == 2 else FakeReconstructionStrategy()
        ),
        segmentation=FailingSegmentationStrategy() if stage == 3 else FakeSegmentationStrategy(),
        meshing=FailingMeshingStrategy() if stage == 4 else FakeMeshingStrategy(),
    )


def run_failing_at(stage: int, progress: RecordingProgress):
    loader = FailingLoader() if stage == 1 else ProjectionLoader()
    parsed = ProjectionLoader().parse(four_valid_files())
    return ProcessingPipeline(loader).run(CODE, parsed, strategies_failing_at(stage), progress)


@pytest.mark.unit
@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_a_failing_stage_is_recorded_and_raises_stage_failed(stage: int) -> None:
    progress = RecordingProgress()

    with pytest.raises(StageFailedError) as caught:
        run_failing_at(stage, progress)

    error = caught.value
    assert error.stage_number == stage
    assert error.study_code == CODE
    assert isinstance(error.__cause__, RuntimeError)
    assert INTERNAL_DETAIL not in str(error)
    assert progress.events[-1] == ("failed", CODE, stage)
    assert not any(e[0] == "completed" and e[2] == stage for e in progress.events)
    assert not any(e[0] == "started" and e[2] > stage for e in progress.events)


@pytest.mark.unit
@pytest.mark.parametrize(("event", "stage"), [("save_volume", 2), ("save_result", 4)])
def test_a_failing_save_fails_its_stage(event: str, stage: int) -> None:
    progress = RecordingProgress(fail_on=(event, CODE))

    with pytest.raises(StageFailedError) as caught:
        run(progress)

    assert caught.value.stage_number == stage
    assert progress.events[-1] == ("failed", CODE, stage)


@pytest.mark.unit
def test_if_recording_the_failure_also_fails_the_stage_error_is_still_raised() -> None:
    progress = RecordingProgress(fail_on=("failed", CODE))

    with pytest.raises(StageFailedError) as caught:
        run_failing_at(3, progress)

    assert caught.value.stage_number == 3


@pytest.mark.unit
def test_the_log_names_the_stage_and_the_error_type_but_not_its_text(caplog) -> None:
    with caplog.at_level("ERROR"), pytest.raises(StageFailedError):
        run_failing_at(3, RecordingProgress())

    text = caplog.text
    assert CODE in text
    assert "RuntimeError" in text
    assert INTERNAL_DETAIL not in text
