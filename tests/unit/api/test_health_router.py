"""Prueba unitaria del endpoint de estado.

Es la primera prueba del repositorio y sirve de ejemplo del formato: una
funcionalidad, una prueba, sin servicios externos.
"""

import pytest

from radvol3d import config


@pytest.mark.unit
def test_health_devuelve_los_parametros_del_sistema(client) -> None:
    respuesta = client.get("/health")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["grid_size"] == config.GRID_SIZE
    assert cuerpo["projection_angles"] == list(config.PROJECTION_ANGLES)
