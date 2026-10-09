"""Convierte los archivos subidos en el arreglo (4, N, N) que espera la tuberia."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectionFile:
    """Un archivo de proyeccion tal como llega: su angulo, sus bytes y su nombre.

    content son los bytes de un .npy en el convenio de TA-2 (integrales de linea sin
    normalizar). La presentacion arma uno por cada archivo subido.
    """

    angle_degrees: int
    content: bytes
    original_name: str | None = None


class ProjectionLoader:
    """Lee y valida las cuatro proyecciones de entrada, sin reescalarlas."""

    def load(self, files: list[bytes]) -> Any:
        """Devuelve (4, N, N) float32 ordenado por angulo."""
        raise NotImplementedError("TODO: leer .npy y validar (T034 y T047)")
