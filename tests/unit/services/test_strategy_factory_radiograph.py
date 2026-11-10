"""Pruebas de la fabrica en el modo de una radiografia."""

import pytest

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.services.segmentation.pending_segmentation_strategy import (
    PendingSegmentationStrategy,
)
from radvol3d.services.strategy_factory import StrategyFactory
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeRadiographReconstructionStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)


def factory(radiograph_builder=FakeRadiographReconstructionStrategy) -> StrategyFactory:
    built = StrategyFactory(
        reconstruction_builders={"en1": FakeReconstructionStrategy},
        segmentation_builders={OrganName.LUNG: FakeSegmentationStrategy},
        meshing_builder=FakeMeshingStrategy,
        reconstruction_key="en1",
        radiograph_reconstruction_builder=radiograph_builder,
        radiograph_segmentation_builders={OrganName.LUNG: PendingSegmentationStrategy},
    )
    built.preload()
    return built


@pytest.mark.unit
def test_the_radiograph_strategies_of_the_lung_are_built_once() -> None:
    built = factory()

    first = built.radiograph_strategies_for(OrganName.LUNG)
    second = built.radiograph_strategies_for("lung")

    assert isinstance(first.reconstruction, FakeRadiographReconstructionStrategy)
    assert isinstance(first.segmentation, PendingSegmentationStrategy)
    assert first.reconstruction is second.reconstruction
    assert first.meshing is built.meshing_for(OrganName.LUNG)
    assert built.radiograph_mode_configured() is True
    assert built.availability()["radiograph:reconstruction"] is True


@pytest.mark.unit
def test_without_configuration_the_mode_is_not_available() -> None:
    built = factory(radiograph_builder=None)

    with pytest.raises(ModelNotAvailableError, match="no está disponible"):
        built.radiograph_strategies_for(OrganName.LUNG)
    assert built.radiograph_mode_configured() is False
    assert "radiograph:reconstruction" not in built.availability()


@pytest.mark.unit
def test_the_liver_has_no_radiograph_mode() -> None:
    with pytest.raises(ModelNotAvailableError, match="hígado"):
        factory().radiograph_strategies_for(OrganName.LIVER)


@pytest.mark.unit
def test_the_four_projections_mode_is_not_affected() -> None:
    built = factory()

    assert isinstance(
        built.strategies_for(OrganName.LUNG).reconstruction, FakeReconstructionStrategy
    )
