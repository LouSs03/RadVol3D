"""Linea base: retroproyeccion simple, sin red neuronal.

Sirve de referencia contra la cual se compara el modelo EN-1, y permite que el
sistema funcione de punta a punta antes de que el modelo este integrado.
"""

from typing import Any

from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy


class BackprojectionStrategy(ReconstructionStrategy):
    """Reconstruye por retroproyeccion filtrada."""

    def reconstruct(self, projections: Any) -> Any:
        raise NotImplementedError("TODO: implementar la retroproyeccion")

    @property
    def model_name(self) -> str:
        return "backprojection"

    @property
    def model_version(self) -> str:
        return "1.0.0"
