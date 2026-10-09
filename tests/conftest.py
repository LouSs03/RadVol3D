"""Fixtures compartidas por todas las pruebas."""

import pytest
from fastapi.testclient import TestClient

from radvol3d.main import create_app


@pytest.fixture
def app():
    """Una aplicacion nueva por prueba, sin estado compartido."""
    return create_app()


@pytest.fixture
def client(app):
    """Cliente HTTP contra la aplicacion en memoria, sin levantar servidor."""
    with TestClient(app) as test_client:
        yield test_client
