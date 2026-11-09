"""Adapt the experimental LUNA16 model to the reconstruction pipeline."""

import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
from numpy import ndarray

from radvol3d import config
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy


class Luna16Strategy(ReconstructionStrategy):
    model_name = "reconstruction_en1_luna16"
    model_version = "2.0.0"

    def __init__(self, predict: Callable[[ndarray], ndarray]) -> None:
        self._predict = predict
        self._lock = threading.Lock()

    @classmethod
    def from_weights(cls, path: str | Path) -> "Luna16Strategy":
        import torch

        from radvol3d.services.reconstruction.luna16_reconstructor import Luna16Reconstructor

        model = Luna16Reconstructor.from_weights(path)

        def predict(views: ndarray) -> ndarray:
            with torch.inference_mode():
                return model(torch.from_numpy(views).unsqueeze(0))[0, 0].numpy()

        return cls(predict)

    def reconstruct(self, projections: ndarray) -> ndarray:
        expected = (len(config.PROJECTION_ANGLES), config.GRID_SIZE, config.GRID_SIZE)
        if np.shape(projections) != expected or np.iscomplexobj(projections):
            raise ValueError(f"LUNA16 requires four real projections of shape {expected}.")
        views = np.ascontiguousarray(projections, dtype=np.float32)
        if not np.isfinite(views).all() or views.min() < 0 or views.max() > 1:
            raise ValueError("LUNA16 requires finite mean projections in [0, 1].")
        with self._lock:
            volume = self._predict(views)
        if (
            volume.shape != (config.GRID_SIZE,) * 3
            or not np.isfinite(volume).all()
            or volume.min() < 0
            or volume.max() > 1
        ):
            raise RuntimeError("LUNA16 returned an invalid normalized volume.")
        # Reorder array indices only; the cropped sample has no physical affine.
        return np.ascontiguousarray(volume.transpose(2, 1, 0), dtype=np.float32)
