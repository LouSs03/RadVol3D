"""Pruebas del lifespan: arma los servicios una vez al arrancar y los cierra al terminar."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from radvol3d.api.dependencies import get_study_service
from radvol3d.main import create_app
from tests.fixtures.fake_container import FakeServiceContainer


@pytest.mark.unit
def test_the_lifespan_builds_the_container_once_and_closes_it() -> None:
    built: list[FakeServiceContainer] = []

    def builder() -> FakeServiceContainer:
        built.append(FakeServiceContainer())
        return built[-1]

    app = create_app(container_builder=builder)

    with TestClient(app):
        assert len(built) == 1
        assert app.state.services is built[0]
        assert built[0].closed == 0

    assert built[0].closed == 1


@pytest.mark.unit
def test_the_container_is_not_built_before_the_app_starts() -> None:
    built: list[FakeServiceContainer] = []

    create_app(container_builder=lambda: built.append(FakeServiceContainer()))

    assert built == []


@pytest.mark.unit
def test_the_study_service_comes_from_the_app_state() -> None:
    container = FakeServiceContainer()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

    assert get_study_service(request) is container.study_service


@pytest.mark.unit
def test_the_lifespan_logs_which_models_are_available(caplog) -> None:
    app = create_app(container_builder=FakeServiceContainer)

    with caplog.at_level("INFO"), TestClient(app):
        pass

    assert "segmentation:lung" in caplog.text
