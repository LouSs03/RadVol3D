"""Reconstruccion con el modelo EN-1: retroproyector de TA-2 mas U-Net 3D residual.

Los pesos no estan en el repositorio. Se descargan de Supabase Storage desde
modelos/reconstruccion_v1.pth. Detalle en docs/models/reconstruction_en1.md.
"""

from typing import Any

from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy


class NeuralEn1Strategy(ReconstructionStrategy):
    """Reconstruye con la red EN-1 a 128 voxeles por lado."""

    def __init__(self, weights_path: str) -> None:
        self._weights_path = weights_path
        # TODO: cargar los pesos una sola vez, no en cada llamada

    def reconstruct(self, projections: Any) -> Any:
        raise NotImplementedError("TODO: envolver el modulo de inferencia de EN-1")

    @property
    def model_name(self) -> str:
        return "reconstruction_en1"

    @property
    def model_version(self) -> str:
        return "1.0.0"
