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
def test_fake_reconstruction_returns_the_expected_volume() -> None:
    strategy = FakeReconstructionStrategy(grid_size=config.GRID_SIZE)
    projections = np.zeros((4, config.GRID_SIZE, config.GRID_SIZE), dtype=np.float32)

    volume = strategy.reconstruct(projections)

    assert volume.shape == (config.GRID_SIZE,) * 3
    assert volume.dtype == np.float32
    assert float(volume.min()) >= 0.0
    assert float(volume.max()) <= 1.0


@pytest.mark.unit
def test_fake_segmentation_delivers_confidence_per_voxel() -> None:
    volume = np.zeros((config.GRID_SIZE,) * 3, dtype=np.float32)

    result = FakeSegmentationStrategy().segment(volume)

    assert result.mask.dtype == np.uint8
    assert set(np.unique(result.mask)) <= {0, 1}
    assert result.probability.shape == result.mask.shape
    assert float(result.probability.min()) >= 0.0
    assert float(result.probability.max()) <= 1.0
    assert 0.0 <= result.global_confidence <= 1.0
