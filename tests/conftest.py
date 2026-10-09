"""Fixtures compartidas por todas las pruebas."""

import pytest
from fastapi.testclient import TestClient

from radvol3d.main import create_app
from tests.fixtures.fake_container import FakeServiceContainer


@pytest.fixture
def app():
    """Una aplicacion nueva por prueba, sin estado compartido.

    Usa un contenedor de servicios falso: el lifespan no abre la base ni baja pesos,
    asi que estas pruebas no necesitan .env.
    """
    return create_app(container_builder=FakeServiceContainer)


@pytest.fixture
def client(app):
    """Cliente HTTP contra la aplicacion en memoria, sin levantar servidor."""
    with TestClient(app) as test_client:
        yield test_client
