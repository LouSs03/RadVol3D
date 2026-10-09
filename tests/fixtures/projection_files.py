"""Archivos de proyeccion armados en memoria, validos e invalidos.

Los validos imitan el convenio de TA-2: integrales de linea positivas, sin
normalizar a [0, 1]. Ninguno contiene datos de pacientes.
"""

import io

import numpy as np

from radvol3d import config
from radvol3d.services.pipeline.projection_loader import ProjectionFile

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _npy_bytes(array: np.ndarray, allow_pickle: bool = False) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=allow_pickle)
    return buffer.getvalue()


def valid_array(angle: int, seed: int = 0) -> np.ndarray:
    """Proyeccion (128, 128) float32, finita y distinta por angulo y semilla."""
    rng = np.random.default_rng(seed * 1000 + angle)
    size = config.GRID_SIZE
    return (rng.random((size, size)) * 40.0).astype(np.float32)


def valid_npy(angle: int, seed: int = 0) -> bytes:
    return _npy_bytes(valid_array(angle, seed))


def png_bytes() -> bytes:
    return PNG_SIGNATURE + bytes(32)


def pickled_npy() -> bytes:
    return _npy_bytes(np.array([{"clave": 1}], dtype=object), allow_pickle=True)


def npy_with_nan() -> bytes:
    array = valid_array(0)
    array[3, 4] = np.nan
    return _npy_bytes(array)


def npy_with_inf() -> bytes:
    array = valid_array(0)
    array[5, 6] = np.inf
    return _npy_bytes(array)


def npy_wrong_shape() -> bytes:
    return _npy_bytes(np.zeros((64, 64), dtype=np.float32))


def npy_text_dtype() -> bytes:
    size = config.GRID_SIZE
    return _npy_bytes(np.full((size, size), "a", dtype="<U1"))


def four_valid_files(seed: int = 0) -> list[ProjectionFile]:
    """Las cuatro proyecciones validas, una por angulo, en el orden de config."""
    return [
        ProjectionFile(angle, valid_npy(angle, seed), f"angle_{angle:03d}.npy")
        for angle in config.PROJECTION_ANGLES
    ]
