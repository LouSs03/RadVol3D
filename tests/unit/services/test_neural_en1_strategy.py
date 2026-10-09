"""Pruebas del envoltorio de EN-1 con un motor falso: sin torch ni pesos."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from radvol3d.services.reconstruction.neural_en1_strategy import NeuralEn1Strategy


class FakeEngine:
    """Imita a En1Reconstructor y detecta si dos llamadas se solaparon."""

    def __init__(self, shape: tuple[int, ...] = (128, 128, 128)) -> None:
        self.shape = shape
        self.calls: list[np.ndarray] = []
        self.active = 0
        self.max_active = 0
        self._counter = threading.Lock()

    def reconstruct(self, projections: np.ndarray) -> np.ndarray:
        with self._counter:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.005)
        with self._counter:
            self.active -= 1
        self.calls.append(projections)
        return np.full(self.shape, 0.5, dtype=np.float32)


@pytest.mark.unit
def test_reconstruct_delegates_to_the_engine() -> None:
    engine = FakeEngine()
    projections = np.zeros((4, 128, 128), dtype=np.float32)

    volume = NeuralEn1Strategy(engine).reconstruct(projections)

    assert engine.calls == [projections]
    assert volume.shape == (128, 128, 128)
    assert volume.dtype == np.float32


@pytest.mark.unit
def test_an_output_with_the_wrong_shape_is_rejected() -> None:
    strategy = NeuralEn1Strategy(FakeEngine(shape=(64, 64, 64)))

    with pytest.raises(RuntimeError):
        strategy.reconstruct(np.zeros((4, 128, 128), dtype=np.float32))


@pytest.mark.unit
def test_the_model_name_and_version_are_the_registered_ones() -> None:
    strategy = NeuralEn1Strategy(FakeEngine())

    assert strategy.model_name == "reconstruction_en1"
    assert strategy.model_version == "1.0.0"


@pytest.mark.unit
def test_two_threads_never_run_the_engine_at_the_same_time() -> None:
    engine = FakeEngine()
    strategy = NeuralEn1Strategy(engine)
    projections = np.zeros((4, 128, 128), dtype=np.float32)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: strategy.reconstruct(projections), range(8)))

    assert engine.max_active == 1
    assert len(engine.calls) == 8


@pytest.mark.unit
def test_importing_the_strategy_does_not_import_torch() -> None:
    import importlib

    already = "torch" in sys.modules
    importlib.reload(sys.modules[NeuralEn1Strategy.__module__])

    assert already or "torch" not in sys.modules
