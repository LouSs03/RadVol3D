"""Archivos de prueba del modo de una radiografia: DICOM minimos y volumenes NIfTI.

No son radiografias reales (esas son de LIDC-IDRI y no van al repositorio): solo tienen
la forma que revisan las validaciones y el lector de NIfTI.
"""

import gzip
import struct

import numpy as np


def fake_dicom(size: int = 1024) -> bytes:
    """Bytes con el preambulo de 128 bytes y la marca DICM, como un DICOM."""
    body = b"\x00" * max(0, size - 132)
    return b"\x00" * 128 + b"DICM" + body


def nifti_bytes(
    volume: np.ndarray,
    *,
    compress: bool = True,
    slope: float = 1.0,
    intercept: float = 0.0,
    datatype: int = 16,
    big_endian: bool = False,
) -> bytes:
    """Un NIfTI-1 de un solo archivo (.nii o .nii.gz) con el volumen en orden Fortran."""
    endian = ">" if big_endian else "<"
    dtypes = {2: "u1", 4: "i2", 16: "f4", 64: "f8"}
    data = np.asarray(volume).astype(np.dtype(dtypes[datatype]).newbyteorder(endian))
    header = bytearray(348)
    struct.pack_into(endian + "i", header, 0, 348)
    dims = (data.ndim, *data.shape) + (1,) * (7 - data.ndim)
    struct.pack_into(endian + "8h", header, 40, *dims)
    struct.pack_into(endian + "hh", header, 70, datatype, data.dtype.itemsize * 8)
    struct.pack_into(endian + "8f", header, 76, 1, 2.5, 2.5, 2.5, 1, 1, 1, 1)
    struct.pack_into(endian + "f", header, 108, 352.0)
    struct.pack_into(endian + "2f", header, 112, slope, intercept)
    header[344:348] = b"n+1\x00"
    raw = bytes(header) + b"\x00" * 4 + data.tobytes(order="F")
    return gzip.compress(raw) if compress else raw
