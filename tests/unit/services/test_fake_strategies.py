"""Comprueba que los dobles cumplen la interfaz de las estrategias.

Si esta prueba falla, los dobles dejaron de servir y todas las pruebas de la
tuberia que dependen de ellos quedan sin valor.
"""

import numpy as np
import pytest

from radvol3d import config
from tests.fixtures.fake_strategies import (
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)


@pytest.mark.unit
def test_la_reconstruccion_falsa_devuelve_el_volumen_esperado() -> None:
    estrategia = FakeReconstructionStrategy(grid_size=config.GRID_SIZE)
    proyecciones = np.zeros((4, config.GRID_SIZE, config.GRID_SIZE), dtype=np.float32)

    volumen = estrategia.reconstruct(proyecciones)

    assert volumen.shape == (config.GRID_SIZE,) * 3
    assert volumen.dtype == np.float32
    assert 0.0 <= float(volumen.min()) and float(volumen.max()) <= 1.0


@pytest.mark.unit
def test_la_segmentacion_falsa_entrega_confianza_por_voxel() -> None:
    volumen = np.zeros((config.GRID_SIZE,) * 3, dtype=np.float32)

    resultado = FakeSegmentationStrategy().segment(volumen)

    assert resultado.mask.dtype == np.uint8
    assert set(np.unique(resultado.mask)) <= {0, 1}
    assert resultado.probability.shape == resultado.mask.shape
    assert 0.0 <= float(resultado.probability.min())
    assert float(resultado.probability.max()) <= 1.0
    assert 0.0 <= resultado.global_confidence <= 1.0
