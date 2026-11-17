"""Pruebas de la eleccion del motor del modo de una radiografia (RADIOGRAPH_ENGINE)."""

from pathlib import Path

import pytest

from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.persistence.settings import (
    ModelSettings,
    RadiographEngineSettings,
    ReconstructionServiceSettings,
)
from radvol3d.services.reconstruction.remote_axon_strategy import RemoteAxonStrategy
from radvol3d.services.reconstruction.x2ct_strategy import (
    X2CT_WEIGHTS_OBJECT,
    X2CT_WEIGHTS_SHA256_PREFIX,
    X2ctStrategy,
)
from radvol3d.services.service_container import (
    MODEL_DESCRIPTIONS,
    default_strategy_builders,
    radiograph_engine_builder,
)

AXON = ReconstructionServiceSettings(
    _env_file=None, axon_url="https://axon.example", axon_api_key="clave"
)


def engine(**values) -> RadiographEngineSettings:
    return RadiographEngineSettings(_env_file=None, **values)


class RecordingSplitStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch(self, object_path: str, prefix: str) -> Path:
        self.calls.append((object_path, prefix))
        return Path("pesos.pth")


@pytest.mark.unit
def test_by_default_the_engine_is_x2ct() -> None:
    settings = engine()

    assert settings.radiograph_engine == "x2ct"
    assert settings.x2ct_weights_object is None


@pytest.mark.unit
def test_the_engine_and_the_weights_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("RADIOGRAPH_ENGINE", "axon")
    monkeypatch.setenv("X2CT_WEIGHTS_OBJECT", X2CT_WEIGHTS_OBJECT)

    settings = RadiographEngineSettings(_env_file=None)

    assert settings.radiograph_engine == "axon"
    assert settings.x2ct_weights_object == X2CT_WEIGHTS_OBJECT


@pytest.mark.unit
def test_an_unknown_engine_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("RADIOGRAPH_ENGINE", "colab")

    with pytest.raises(ValueError):
        RadiographEngineSettings(_env_file=None)


@pytest.mark.unit
def test_with_x2ct_the_weights_are_fetched_verified_and_loaded(monkeypatch) -> None:
    loaded: list[Path] = []
    monkeypatch.setattr(
        X2ctStrategy, "from_weights", classmethod(lambda cls, path: loaded.append(path) or "x2ct")
    )
    store = RecordingSplitStore()

    builder = radiograph_engine_builder(
        engine(x2ct_weights_object=X2CT_WEIGHTS_OBJECT), None, store
    )

    assert builder() == "x2ct"
    assert store.calls == [(X2CT_WEIGHTS_OBJECT, X2CT_WEIGHTS_SHA256_PREFIX)]
    assert loaded == [Path("pesos.pth")]


@pytest.mark.unit
def test_with_x2ct_the_mode_does_not_need_axon_settings(monkeypatch) -> None:
    monkeypatch.setattr(X2ctStrategy, "from_weights", classmethod(lambda cls, path: "x2ct"))

    builder = radiograph_engine_builder(
        engine(x2ct_weights_object=X2CT_WEIGHTS_OBJECT), None, RecordingSplitStore()
    )

    assert builder is not None and builder() == "x2ct"


@pytest.mark.unit
def test_with_x2ct_and_without_weights_the_mode_is_not_available() -> None:
    builder = radiograph_engine_builder(engine(), AXON, RecordingSplitStore())

    with pytest.raises(ModelNotAvailableError):
        builder()


@pytest.mark.unit
def test_with_axon_the_previous_builder_is_used() -> None:
    builder = radiograph_engine_builder(engine(radiograph_engine="axon"), AXON, None)

    assert isinstance(builder(), RemoteAxonStrategy)


@pytest.mark.unit
def test_with_axon_and_without_its_settings_the_mode_is_not_configured() -> None:
    assert radiograph_engine_builder(engine(radiograph_engine="axon"), None, None) is None


@pytest.mark.unit
def test_without_engine_settings_the_builders_are_the_ones_of_before() -> None:
    builders = default_strategy_builders(None, ModelSettings(_env_file=None))

    assert builders.radiograph_reconstruction is None


@pytest.mark.unit
def test_x2ct_is_registered_with_a_description() -> None:
    assert "X2CT-GAN" in MODEL_DESCRIPTIONS["reconstruction_x2ct"]
