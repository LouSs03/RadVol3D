"""Reconstruccion con el modelo EN-1: retroproyector de TA-2 mas U-Net 3D residual.

Los pesos no estan en el repositorio: viven en el bucket de modelos y los baja
service_container al arrancar. Detalle en docs/models/reconstruction_en1.md.

Este modulo no importa torch en su nivel superior: from_weights lo importa recien al
construir el motor. Asi api/ y las pruebas unitarias importan la estrategia sin torch.
"""

import threading
from pathlib import Path
from typing import Any

import numpy as np

from radvol3d import config
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy


class NeuralEn1Strategy(ReconstructionStrategy):
    """Reconstruye con la red EN-1 a 128 voxeles por lado.

    Recibe el motor ya construido (En1Reconstructor, o un doble en las pruebas). Un
    candado serializa la inferencia: dos estudios a la vez comparten el mismo modelo,
    uno despues del otro, sin cargar una copia por estudio (research.md R13).
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    @classmethod
    def from_weights(cls, weights_path: str | Path) -> "NeuralEn1Strategy":
        """Carga los pesos una sola vez. Importa torch solo aqui."""
        from radvol3d.services.reconstruction.en1_reconstructor import En1Reconstructor

        return cls(En1Reconstructor(str(weights_path), device="cpu"))

    def reconstruct(self, projections: Any) -> Any:
        with self._lock:
            volume = self._engine.reconstruct(projections)
        expected = (config.GRID_SIZE,) * 3
        if np.shape(volume) != expected:
            raise RuntimeError(f"EN-1 devolvio un volumen de forma {np.shape(volume)}.")
        return volume

    @property
    def model_name(self) -> str:
        return "reconstruction_en1"

    @property
    def model_version(self) -> str:
        return "1.0.0"
