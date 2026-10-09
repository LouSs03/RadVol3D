"""Prueba unitaria del endpoint de estado.

Es la primera prueba del repositorio y sirve de ejemplo del formato: una
funcionalidad, una prueba, sin servicios externos.
"""

import pytest

from radvol3d import config


@pytest.mark.unit
def test_health_returns_the_system_parameters(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["grid_size"] == config.GRID_SIZE
    assert body["projection_angles"] == list(config.PROJECTION_ANGLES)
