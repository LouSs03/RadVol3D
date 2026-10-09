"""Convierte los archivos subidos en el arreglo (4, N, N) que espera la tuberia."""

from typing import Any


class ProjectionLoader:
    """Carga, valida y normaliza las cuatro proyecciones de entrada."""

    def load(self, files: list[bytes]) -> Any:
        """Devuelve (4, N, N) float32 en [0,1], ordenado por angulo."""
        raise NotImplementedError("TODO: leer PNG y NPY, validar tamano y normalizar")
