"""Pruebas del armado de los servicios al arrancar (research.md R11 y R12).

La base, el almacenamiento y los constructores de estrategias son dobles: ninguna
prueba abre una conexion ni baja pesos.
"""

from pathlib import Path

import pytest
from pydantic import SecretStr

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.settings import ModelSettings, Settings
from radvol3d.services.service_container import (
    ServiceContainer,
    StrategyBuilders,
    build_service_container,
)
from radvol3d.services.study_service import StudyRequest, StudyService
from tests.fixtures.fake_database import FakeDatabase
from tests.fixtures.fake_object_storage import InMemoryBucket
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files

SETTINGS = Settings(
    _env_file=None,
    database_url=SecretStr("postgresql://user:pass@host/db"),
    supabase_url="https://project.example",
    supabase_service_key=SecretStr("service-key-value-1"),
    storage_bucket="bucket-de-prueba",
)


class OpenableDatabase(FakeDatabase):
    """FakeDatabase con open y close, como Database."""

    def __init__(self) -> None:
        super().__init__()
        self.opened = 0
        self.closed = 0
        self.connection.when(
            "insert into model",
            [{"model_name": "m", "version": "0.0.0", "trained_on": None, "description": None}],
        )

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1


class CountingBuilder:
    def __init__(self, strategy_type: type, error: Exception | None = None) -> None:
        self.strategy_type = strategy_type
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.strategy_type()


class World:
    def __init__(self, segmentation_error: Exception | None = None) -> None:
        self.database = OpenableDatabase()
        self.buckets: list[str | None] = []
        self.builders = {
            "reconstruction": CountingBuilder(FakeReconstructionStrategy),
            "segmentation": CountingBuilder(FakeSegmentationStrategy, segmentation_error),
            "meshing": CountingBuilder(FakeMeshingStrategy),
        }

    def storage_factory(self, settings: Settings, bucket: str | None = None) -> ObjectStorage:
        self.buckets.append(bucket)
        return ObjectStorage(InMemoryBucket())

    def build(self, model_settings: ModelSettings | None = None) -> ServiceContainer:
        return build_service_container(
            SETTINGS,
            model_settings or ModelSettings(_env_file=None),
            database_factory=lambda settings: self.database,
            storage_factory=self.storage_factory,
            strategy_builders=StrategyBuilders(
                reconstruction={"en1": self.builders["reconstruction"]},
                segmentation={OrganName.LUNG: self.builders["segmentation"]},
                meshing=self.builders["meshing"],
            ),
        )


@pytest.fixture(autouse=True)
def no_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MODEL_BUCKET",
        "EN1_WEIGHTS_OBJECT",
        "EN2_WEIGHTS_OBJECT",
        "MODEL_CACHE_DIR",
        "RECONSTRUCTION_STRATEGY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_the_container_opens_the_database_once_and_builds_the_study_service() -> None:
    world = World()

    container = world.build()

    assert world.database.opened == 1
    assert isinstance(container.study_service, StudyService)


@pytest.mark.unit
def test_each_strategy_is_built_once_however_many_times_it_is_asked_for() -> None:
    world = World()
    container = world.build()

    for _ in range(3):
        container.factory.strategies_for(OrganName.LUNG)

    assert [b.calls for b in world.builders.values()] == [1, 1, 1]


@pytest.mark.unit
def test_loaded_models_are_registered_without_a_training_date() -> None:
    world = World()

    world.build()

    registered = world.database.connection.params_of("insert into model")
    assert ("fake_reconstruction", "0.0.0", None, None) in registered
    assert ("fake_segmentation", "0.0.0", None, None) in registered
    assert all(params[2] is None for params in registered)  # trained_on


@pytest.mark.unit
def test_a_model_that_does_not_load_does_not_stop_the_container() -> None:
    world = World(segmentation_error=FileNotFoundError("weights.pth"))

    container = world.build()

    assert container.model_status()["segmentation:lung"] is False
    assert container.model_status()["reconstruction:en1"] is True
    registered = world.database.connection.params_of("insert into model")
    assert all(params[0] != "fake_segmentation" for params in registered)
    request = StudyRequest("it_a", OrganName.LUNG, four_valid_files())
    with pytest.raises(ModelNotAvailableError):
        container.study_service.process_study(request)


@pytest.mark.unit
def test_close_closes_the_database_only_once() -> None:
    world = World()
    container = world.build()

    container.close()
    container.close()

    assert world.database.closed == 1


@pytest.mark.unit
def test_without_a_model_bucket_only_the_data_bucket_is_opened() -> None:
    world = World()

    world.build()

    assert world.buckets == [None]


@pytest.mark.unit
def test_with_a_model_bucket_both_buckets_are_opened() -> None:
    world = World()

    world.build(ModelSettings(_env_file=None, model_bucket="modelos-x"))

    assert world.buckets == [None, "modelos-x"]


@pytest.mark.unit
def test_default_builders_without_weights_leave_the_models_unavailable(tmp_path: Path) -> None:
    world = World()

    container = build_service_container(
        SETTINGS,
        ModelSettings(_env_file=None, model_cache_dir=tmp_path),
        database_factory=lambda settings: world.database,
        storage_factory=world.storage_factory,
    )

    status = container.model_status()
    assert status["reconstruction:en1"] is False
    assert status["segmentation:lung"] is False
