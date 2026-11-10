"""Lee el volumen .nii.gz del servicio AXON y lo lleva al convenio del sistema.

Dos pasos, los dos medidos con los cuatro volumenes de ejemplo que entrego Lourdes
(LIDC-IDRI-0001, 0002, 0010 y 0031):

1. Leer el NIfTI-1 con numpy (sin nibabel: el formato es simple y asi el proyecto no
   suma una dependencia). Los datos de un NIfTI estan en orden Fortran: el primer eje
   es el que varia mas rapido.

2. Llevarlo al convenio del sistema (static/js/volume_orientation.js y
   services/meshing/lung_air_region.py): eje 0 hacia la derecha del paciente (R), eje
   1 hacia adelante (A), eje 2 hacia la cabeza (S), y valores en [0, 1] con la ventana
   config.HU_WINDOW (-1000 a 1000 HU).

   La matriz afin del archivo no sirve para orientarlo: es la de la plantilla MNI de
   1 mm (diagonal -1, 1, 1 con origen 90, -126, -72), no la de una rejilla de 128 a
   2,5 mm. La orientacion se decidio mirando los volumenes:

   - eje 0 del archivo: cortes axiales; el indice 0 es el lado de la cabeza;
   - eje 1: izquierda-derecha; el indice 0 es la derecha del paciente (ahi esta el
     higado, en los cuatro casos);
   - eje 2: adelante-atras; el indice 0 es adelante (la columna queda en los indices
     altos, en los cuatro casos).

   Por eso: nuevo[i, j, k] = archivo[127 - k, 127 - i, 127 - j].

   Los valores del servicio estan en [0, 1] con la ventana -100 a 900 HU
   (HU = -100 + 1000 x valor). En la ventana del sistema quedan en 0,45 + 0,5 x valor.
   Con esa conversion, la region del pulmon de las mallas encuentra entre 5,4 y 6,1 L
   de pulmon en los cuatro ejemplos; sin ella, casi nada (menos de 1000 voxeles).

Si Lourdes cambia el modelo y la orientacion cambia, solo hay que tocar AXIS_ORDER y
FLIPPED_AXES. Lo confirma la prueba con los volumenes de ejemplo, si estan disponibles.
"""

import gzip
import io
import struct

import numpy as np

from radvol3d import config
from radvol3d.domain.exceptions import RemoteReconstructionError

NIFTI1_HEADER_BYTES = 348
NIFTI1_MAGICS = (b"n+1\x00", b"ni1\x00")

# Tipos de dato de NIfTI-1 que se aceptan: codigo -> tipo de numpy (little endian).
NIFTI_DATATYPES: dict[int, str] = {
    2: "u1",  # uint8
    4: "i2",  # int16
    8: "i4",  # int32
    16: "f4",  # float32
    64: "f8",  # float64
    256: "i1",  # int8
    512: "u2",  # uint16
}

# Que eje del archivo va a cada eje del sistema (R, A, S) y cuales se invierten despues.
AXIS_ORDER: tuple[int, int, int] = (1, 2, 0)
FLIPPED_AXES: tuple[int, ...] = (0, 1, 2)

# Tope del volumen descomprimido: 128^3 en float64 son 16 MiB; con margen.
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


def read_nifti(content: bytes) -> np.ndarray:
    """Devuelve el arreglo de un NIfTI-1 (.nii o .nii.gz), en float32 y con su escala.

    Lanza RemoteReconstructionError si el archivo no es un NIfTI-1 de tres dimensiones.
    """
    raw = _decompress(content)
    if len(raw) < NIFTI1_HEADER_BYTES + 4:
        raise RemoteReconstructionError("El volumen recibido no es un NIfTI valido.")
    endian = _endianness(raw)
    header = raw[:NIFTI1_HEADER_BYTES]
    if header[344:348] not in NIFTI1_MAGICS:
        raise RemoteReconstructionError("El volumen recibido no es un NIfTI-1.")
    dims = struct.unpack(endian + "8h", header[40:56])
    rank = dims[0]
    shape = tuple(int(n) for n in dims[1 : 1 + rank])
    while len(shape) > 3 and shape[-1] == 1:
        shape = shape[:-1]
    if len(shape) != 3 or min(shape) < 1:
        raise RemoteReconstructionError("El volumen recibido no tiene tres dimensiones.")
    datatype = struct.unpack(endian + "h", header[70:72])[0]
    if datatype not in NIFTI_DATATYPES:
        raise RemoteReconstructionError("El volumen recibido usa un tipo de dato no admitido.")
    vox_offset = int(struct.unpack(endian + "f", header[108:112])[0])
    slope, intercept = struct.unpack(endian + "2f", header[112:120])

    dtype = np.dtype(NIFTI_DATATYPES[datatype]).newbyteorder(endian)
    count = int(np.prod(shape))
    start = max(vox_offset, NIFTI1_HEADER_BYTES)
    if len(raw) < start + count * dtype.itemsize:
        raise RemoteReconstructionError("El volumen recibido esta incompleto.")
    data = np.frombuffer(raw, dtype=dtype, count=count, offset=start)
    volume = data.reshape(shape, order="F").astype(np.float32)
    # NIfTI: con scl_slope 0 no se escala; si no, valor = scl_slope x dato + scl_inter.
    if np.isfinite(slope) and slope != 0.0 and (slope != 1.0 or intercept != 0.0):
        volume = volume * np.float32(slope) + np.float32(intercept)
    return np.ascontiguousarray(volume)


def to_system_volume(remote_volume: np.ndarray) -> np.ndarray:
    """Reordena los ejes y cambia la ventana: el volumen queda como uno de EN-1.

    Devuelve (128, 128, 128) float32 en [0, 1] con la ventana config.HU_WINDOW.
    """
    volume = np.asarray(remote_volume, dtype=np.float32)
    if volume.ndim != 3:
        raise RemoteReconstructionError("El volumen recibido no tiene tres dimensiones.")
    if not np.isfinite(volume).all():
        raise RemoteReconstructionError("El volumen recibido trae valores no numericos.")
    reoriented = np.flip(np.transpose(volume, AXIS_ORDER), axis=FLIPPED_AXES)
    converted = rescale_window(
        np.clip(reoriented, 0.0, 1.0), config.REMOTE_VOLUME_HU_WINDOW, config.HU_WINDOW
    )
    grid = config.GRID_SIZE
    if converted.shape != (grid, grid, grid):
        raise RemoteReconstructionError(
            f"El volumen recibido mide {converted.shape} y el sistema espera {(grid, grid, grid)}."
        )
    return np.ascontiguousarray(converted, dtype=np.float32)


def rescale_window(
    values: np.ndarray,
    source: tuple[float, float],
    target: tuple[float, float],
) -> np.ndarray:
    """Valores en [0, 1] con la ventana HU source -> valores en [0, 1] con target."""
    source_low, source_high = source
    target_low, target_high = target
    hounsfield = source_low + (source_high - source_low) * values
    rescaled = (hounsfield - target_low) / (target_high - target_low)
    return np.clip(rescaled, 0.0, 1.0).astype(np.float32)


def _decompress(content: bytes) -> bytes:
    if content[:2] != b"\x1f\x8b":
        return content
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
            raw = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
    except (OSError, EOFError):
        raise RemoteReconstructionError("El volumen recibido esta danado.") from None
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise RemoteReconstructionError("El volumen recibido es demasiado grande.")
    return raw


def _endianness(raw: bytes) -> str:
    """'<' o '>' segun sizeof_hdr (348) en los primeros cuatro bytes."""
    if struct.unpack("<i", raw[:4])[0] == NIFTI1_HEADER_BYTES:
        return "<"
    if struct.unpack(">i", raw[:4])[0] == NIFTI1_HEADER_BYTES:
        return ">"
    raise RemoteReconstructionError("El volumen recibido no es un NIfTI-1.")
