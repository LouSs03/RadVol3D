"""Regresion numerica de EN-1: la salida migrada es la de los scripts originales (FR-034)."""

import numpy as np
import pytest

from radvol3d.services.reconstruction.neural_en1_strategy import NeuralEn1Strategy
from tests.ml.conftest import EN1_WEIGHTS

pytestmark = pytest.mark.ml

TOLERANCE = 1e-5


def test_en1_on_the_phantom_matches_the_reference(model_artifacts) -> None:
    strategy = NeuralEn1Strategy.from_weights(model_artifacts.path(EN1_WEIGHTS))
    projections = np.load(
        model_artifacts.path("regression/en1_phantom_projections.npy"), allow_pickle=False
    )
    expected = np.load(
        model_artifacts.path("regression/en1_phantom_volume.npy"), allow_pickle=False
    )

    volume = strategy.reconstruct(projections)

    assert volume.shape == expected.shape == (128, 128, 128)
    assert volume.dtype == np.float32
    difference = float(np.abs(volume - expected).max())
    assert difference <= TOLERANCE, (
        f"EN-1 difiere de la referencia en {difference:.3e} (tolerancia {TOLERANCE}); "
        + model_artifacts.environment_note()
    )
