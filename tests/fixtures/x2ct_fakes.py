"""Dobles de X2CT-GAN para las pruebas: sin torch, sin pesos y sin DICOM reales.

FakeX2ctReconstructor tiene el contrato de ReconstructorX2CT (reconstruir(entrada,
carpeta) -> metadatos) y escribe un paquete de salida de verdad: un NIfTI-1 armado a
mano (sin nibabel, que el CI no instala), una imagen PNG y metadatos.json.
"""

import gzip
import io
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

GRID = 128


def nifti_bytes(volume_hu: np.ndarray, voxel_mm: tuple[float, float, float]) -> bytes:
    """Un .nii.gz (NIfTI-1, int16, orden Fortran) como el que escribe X2CT-GAN."""
    data = np.asarray(volume_hu, dtype="<i2")
    header = bytearray(348)
    struct.pack_into("<i", header, 0, 348)
    struct.pack_into("<8h", header, 40, 3, *data.shape, 1, 1, 1, 1)
    struct.pack_into("<2h", header, 70, 4, 16)  # datatype int16, bitpix 16
    struct.pack_into("<8f", header, 76, 1.0, *voxel_mm, 1.0, 1.0, 1.0, 1.0)
    struct.pack_into("<f", header, 108, 352.0)  # vox_offset
    struct.pack_into("<2f", header, 112, 1.0, 0.0)  # scl_slope, scl_inter
    header[344:348] = b"n+1\x00"
    raw = bytes(header) + b"\x00" * 4 + data.tobytes(order="F")
    return gzip.compress(raw)


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(np.zeros((GRID, GRID), np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def metadata(
    rows: int = 2000,
    columns: int = 1600,
    pixel_mm: list[float] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """metadatos.json como lo escribe x2ct_sistema (solo las claves que se usan)."""
    if pixel_mm:
        vertical = rows * pixel_mm[0] / GRID
        horizontal = columns * pixel_mm[1] / GRID
        geometry = {"vertical": vertical, "horizontal": horizontal}
        voxel = [horizontal, horizontal, vertical]
    else:
        geometry = None
        voxel = [1.0, 1.0, 1.0]
    return {
        "entrada": {"filas": rows, "columnas": columns, "pixel_mm": pixel_mm},
        "preprocesamiento": {"mm_por_pixel_128": geometry},
        "volumen": {"voxel_mm": voxel},
        "tiempos_s": {"carga_modelo": 1.0, "preprocesamiento": 0.1, "inferencia": 3.2},
        "avisos": list(warnings or []),
    }


class FakeX2ctReconstructor:
    """Tiene el contrato de ReconstructorX2CT. Anota la entrada que recibe."""

    t_carga = 0.5
    huella = "9d9241a5062f"

    def __init__(
        self,
        volume_hu: np.ndarray | None = None,
        meta: dict | None = None,
        placa: np.ndarray | None = None,
    ) -> None:
        self.volume_hu = volume_hu if volume_hu is not None else np.full((GRID,) * 3, -1000, np.int16)
        self.placa = placa if placa is not None else np.zeros((GRID, GRID), np.float32)
        self.meta = meta or metadata(pixel_mm=[0.2, 0.2])
        self.inputs: list[bytes] = []

    def reconstruir(self, entrada: Path, carpeta_salida: Path) -> dict:
        self.inputs.append(Path(entrada).read_bytes())
        carpeta = Path(carpeta_salida)
        carpeta.mkdir(parents=True, exist_ok=True)
        voxel = tuple(self.meta["volumen"]["voxel_mm"])
        (carpeta / "volumen.nii.gz").write_bytes(nifti_bytes(self.volume_hu, voxel))
        (carpeta / "entrada_modelo_128.png").write_bytes(png_bytes())
        np.save(carpeta / "entrada_modelo_128.npy", self.placa)
        (carpeta / "metadatos.json").write_text(json.dumps(self.meta), encoding="utf-8")
        return self.meta
