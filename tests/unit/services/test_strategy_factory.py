"""Pruebas de la fabrica de estrategias (Factory Method; research.md R12)."""

import pytest

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError, StorageError
from radvol3d.services.strategy_factory import StrategyFactory, StrategySet
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)


class CountingBuilder:
    """Constructor sin argumentos que cuenta cuantas veces se llamo."""

    def __init__(self, strategy_type: type) -> None:
        self.strategy_type = strategy_type
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.strategy_type()


@pytest.fixture
def builders() -> dict[str, CountingBuilder]:
    return {
        "reconstruction": CountingBuilder(FakeReconstructionStrategy),
        "segmentation": CountingBuilder(FakeSegmentationStrategy),
        "meshing": CountingBuilder(FakeMeshingStrategy),
    }


@pytest.fixture
def factory(builders: dict[str, CountingBuilder]) -> StrategyFactory:
    return StrategyFactory(
        reconstruction_builders={"en1": builders["reconstruction"]},
        segmentation_builders={OrganName.LUNG: builders["segmentation"]},
        meshing_builder=builders["meshing"],
        reconstruction_key="en1",
    )


@pytest.mark.unit
def test_preload_calls_each_builder_exactly_once(
    factory: StrategyFactory, builders: dict[str, CountingBuilder]
) -> None:
    factory.preload()
    factory.strategies_for(OrganName.LUNG)
    factory.strategies_for(OrganName.LUNG)

    assert [b.calls for b in builders.values()] == [1, 1, 1]


@pytest.mark.unit
def test_nothing_is_built_before_preload(
    builders: dict[str, CountingBuilder], factory: StrategyFactory
) -> None:
    assert [b.calls for b in builders.values()] == [0, 0, 0]


@pytest.mark.unit
def test_strategies_for_lung_returns_the_same_instances_every_time(
    factory: StrategyFactory,
) -> None:
    factory.preload()

    first = factory.strategies_for(OrganName.LUNG)
    second = factory.strategies_for(OrganName.LUNG)

    assert isinstance(first, StrategySet)
    assert isinstance(first.reconstruction, FakeReconstructionStrategy)
    assert isinstance(first.segmentation, FakeSegmentationStrategy)
    assert isinstance(first.meshing, FakeMeshingStrategy)
    assert first.reconstruction is second.reconstruction
    assert first.segmentation is second.segmentation
    assert first.meshing is second.meshing


@pytest.mark.unit
def test_the_organ_can_arrive_as_text(factory: StrategyFactory) -> None:
    factory.preload()

    assert factory.strategies_for("lung") == factory.strategies_for(OrganName.LUNG)


@pytest.mark.unit
def test_availability_reports_every_loaded_strategy(factory: StrategyFactory) -> None:
    factory.preload()

    assert factory.availability() == {
        "reconstruction:en1": True,
        "segmentation:lung": True,
        "meshing": True,
    }


# ---------------------------------------------------------------------------
# Errores (historia 2, escenarios 3 y 5; FR-004, FR-019)
# ---------------------------------------------------------------------------

SECRET_PATH = "segmentation_lung/1.0.0/weights.pth?token=secreto-firmado"


def failing_builder(error: Exception):
    def build():
        raise error

    return build


def factory_with_segmentation(builder, reconstruction_key: str = "en1") -> StrategyFactory:
    return StrategyFactory(
        reconstruction_builders={"en1": FakeReconstructionStrategy},
        segmentation_builders={OrganName.LUNG: builder},
        meshing_builder=FakeMeshingStrategy,
        reconstruction_key=reconstruction_key,
    )


@pytest.mark.unit
def test_liver_has_no_model_yet(factory: StrategyFactory) -> None:
    factory.preload()

    with pytest.raises(ModelNotAvailableError) as caught:
        factory.strategies_for(OrganName.LIVER)

    assert str(caught.value) == "No hay modelo de segmentación de hígado todavía."


@pytest.mark.unit
def test_an_unknown_reconstruction_key_is_reported() -> None:
    factory = factory_with_segmentation(FakeSegmentationStrategy, reconstruction_key="fbp")
    factory.preload()

    with pytest.raises(ModelNotAvailableError) as caught:
        factory.strategies_for(OrganName.LUNG)

    assert str(caught.value) == "No hay estrategia de reconstrucción 'fbp'."


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        ImportError("No module named 'torch'"),
        FileNotFoundError(SECRET_PATH),
        StorageError(f"No se pudo leer el archivo '{SECRET_PATH}' del almacenamiento."),
    ],
)
def test_a_builder_that_fails_leaves_the_model_unavailable(error: Exception, caplog) -> None:
    factory = factory_with_segmentation(failing_builder(error))

    with caplog.at_level("WARNING"):
        factory.preload()  # no lanza

    assert factory.availability()["segmentation:lung"] is False
    assert factory.availability()["reconstruction:en1"] is True
    with pytest.raises(ModelNotAvailableError) as caught:
        factory.strategies_for(OrganName.LUNG)
    assert str(caught.value) == "El modelo segmentation:lung no está disponible en este servidor."
    assert type(error).__name__ in caplog.text
    assert "secreto-firmado" not in caplog.text
    assert "secreto-firmado" not in str(caught.value)


@pytest.mark.unit
def test_strategies_before_preload_are_not_available(factory: StrategyFactory) -> None:
    with pytest.raises(ModelNotAvailableError):
        factory.strategies_for(OrganName.LUNG)


@pytest.mark.unit
def test_model_strategies_lists_the_loaded_reconstruction_and_segmentation(
    factory: StrategyFactory,
) -> None:
    factory.preload()

    names = sorted(s.model_name for s in factory.model_strategies())

    assert names == ["fake_reconstruction", "fake_segmentation"]


@pytest.mark.unit
def test_model_strategies_leaves_out_the_ones_that_did_not_load() -> None:
    factory = factory_with_segmentation(failing_builder(FileNotFoundError("x")))
    factory.preload()

    assert [s.model_name for s in factory.model_strategies()] == ["fake_reconstruction"]
