"""Reconstruccion desde una radiografia con X2CT-GAN (1 vista), en la CPU del servidor.

Reemplaza al servicio AXON (Colab + ngrok) en el modo de una radiografia cuando
RADIOGRAPH_ENGINE=x2ct (el valor por omision). El modelo esta en x2ct/ (sin cambios de
logica; especificacion en docs/x2ct/README_X2CT.md) y se usa por su contrato:

    rec = ReconstructorX2CT(ruta_pesos, dispositivo="cpu")   # una vez, al arrancar
    meta = rec.reconstruir(dicom, carpeta)                    # por estudio

Que hace esta estrategia alrededor de ese contrato:

1. Escribe el DICOM en una carpeta temporal, llama a reconstruir y lee el paquete de
   salida (volumen.nii.gz, entrada_modelo_128.png y metadatos.json).
2. Lleva el volumen al convenio del sistema (static/js/volume_orientation.js): eje 0
   hacia la derecha del paciente (R), eje 1 hacia adelante (A), eje 2 hacia la cabeza
   (S), valores en [0, 1] con la ventana config.HU_WINDOW. X2CT entrega x = izquierda a
   derecha de la placa tal como se ve (en una placa frontal, de la derecha a la
   izquierda del paciente), y = de adelante hacia atras, z = de los pies a la cabeza, en
   HU de -1000 a 1000. Por eso se invierten los ejes 0 y 1 y el 2 queda igual; la
   ventana HU es la misma del sistema.
3. Calcula el tamano de voxel con que se muestra (display_voxel_mm). Con mm reales, el
   de metadatos.json. Sin mm, X2CT usa [1, 1, 1], que deforma una placa no cuadrada
   (el modelo la estira a 128 x 128): aqui se usa un voxel relativo que conserva la
   proporcion original (horizontal = columnas / 128, vertical = filas / 128,
   profundidad = horizontal) y se marca relative_measurements.

Una sola inferencia a la vez (un candado): acota la memoria del servidor. El trabajo
corre en la tarea en segundo plano del estudio, nunca dentro de una peticion.
"""

import json
import logging
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from radvol3d import config
from radvol3d.domain.exceptions import RemoteReconstructionError
from radvol3d.services.reconstruction.nifti_volume import read_nifti
from radvol3d.services.reconstruction.radiograph_reconstruction_strategy import (
    RadiographReconstructionStrategy,
    StateReporter,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "reconstruction_x2ct"
MODEL_VERSION = "1.0.0"

# Pesos de 1 vista (30_net_G.pth) en el bucket de modelos, partidos en .part00, ...
X2CT_WEIGHTS_OBJECT = f"{MODEL_NAME}/{MODEL_VERSION}/weights.pth"
# Primeros 12 caracteres del SHA-256 de 30_net_G.pth (docs/x2ct/README_X2CT.md).
X2CT_WEIGHTS_SHA256_PREFIX = "9d9241a5062f"

NIFTI_FILE = "volumen.nii.gz"
INPUT_IMAGE_FILE = "entrada_modelo_128.png"
# La placa exacta (float32 en [0, 1]): la validacion frontal la prefiere al PNG redondeado.
INPUT_ARRAY_FILE = "entrada_modelo_128.npy"
METADATA_FILE = "metadatos.json"
# Lo que se guarda de cada estudio, ademas del volumen del sistema y la malla.
OUTPUT_FILES = (NIFTI_FILE, INPUT_IMAGE_FILE, INPUT_ARRAY_FILE, METADATA_FILE)

# Ejes de X2CT (x, y, z) que se invierten para quedar en (R, A, S).
FLIPPED_AXES = (0, 1)
MODEL_GRID = 128

RELATIVE_WARNING = "medidas relativas (sin tamaño de píxel)"
# Como empiezan los avisos de x2ct_sistema cuando la entrada no trae tamano de pixel.
X2CT_NO_PIXEL_WARNINGS = (
    "El DICOM no trae tamano de pixel",
    "Entrada en formato imagen: no trae tamano de pixel",
)


@dataclass(frozen=True)
class X2ctReconstruction:
    """Lo que produce X2CT-GAN para un estudio, listo para guardar y mostrar."""

    volume: np.ndarray
    voxel_mm: tuple[float, float, float]
    relative_measurements: bool
    warnings: tuple[str, ...]
    files: Mapping[str, bytes]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def view(self) -> dict[str, Any]:
        """Lo que necesita el visor del modo de una radiografia (visor.json)."""
        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "voxel_mm": [round(value, 4) for value in self.voxel_mm],
            "relative_measurements": self.relative_measurements,
            "warnings": list(self.warnings),
            "input_size_px": _input_size(self.metadata),
            "timings_s": dict(self.metadata.get("tiempos_s", {})),
        }


class X2ctStrategy(RadiographReconstructionStrategy):
    """Reconstruye con un ReconstructorX2CT ya cargado (uno solo para todo el servicio)."""

    def __init__(self, reconstructor: Any) -> None:
        self._reconstructor = reconstructor
        self._lock = threading.Lock()

    @classmethod
    def from_weights(cls, weights_path: str | Path) -> "X2ctStrategy":
        """Carga el modelo una sola vez, en CPU. Importa torch solo aqui."""
        from radvol3d.services.reconstruction.x2ct.x2ct_sistema import ReconstructorX2CT

        reconstructor = ReconstructorX2CT(weights_path, dispositivo="cpu")
        logger.info(
            "X2CT-GAN cargado en %.1f s (pesos %s)", reconstructor.t_carga, reconstructor.huella
        )
        return cls(reconstructor)

    @property
    def model_name(self) -> str:
        return MODEL_NAME

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def is_available(self) -> bool:
        """Si la estrategia existe, el modelo ya esta cargado: no depende de Colab."""
        return True

    def reconstruct(self, radiograph: bytes, report: StateReporter | None = None) -> Any:
        return self.reconstruct_study(radiograph).volume

    def reconstruct_study(self, radiograph: bytes) -> X2ctReconstruction:
        """Reconstruye el DICOM y devuelve el volumen del sistema con su paquete de salida."""
        with self._lock, tempfile.TemporaryDirectory(prefix="radvol3d_x2ct_") as folder:
            entrada = Path(folder) / "radiografia.dcm"
            entrada.write_bytes(radiograph)
            salida = Path(folder) / "salida"
            metadata = self._reconstructor.reconstruir(entrada, salida)
            files = {name: (salida / name).read_bytes() for name in OUTPUT_FILES}
        if not isinstance(metadata, Mapping):
            metadata = json.loads(files[METADATA_FILE])
        voxel_mm, relative = display_voxel_mm(metadata)
        warnings = list(metadata.get("avisos", []))
        if relative:
            # Un solo aviso de "sin tamano de pixel": el de X2CT se reemplaza por el del
            # sistema, que dice como se muestran las medidas.
            warnings = [w for w in warnings if not w.startswith(X2CT_NO_PIXEL_WARNINGS)]
            warnings.append(f"Sin tamaño de píxel en el DICOM: {RELATIVE_WARNING}.")
        return X2ctReconstruction(
            volume=to_system_volume(read_nifti(files[NIFTI_FILE])),
            voxel_mm=voxel_mm,
            relative_measurements=relative,
            warnings=tuple(warnings),
            files=files,
            metadata=metadata,
        )


def to_system_volume(volume_hu: np.ndarray) -> np.ndarray:
    """Volumen de X2CT (x, y, z en HU) al convenio del sistema: (R, A, S) en [0, 1]."""
    volume = np.asarray(volume_hu, dtype=np.float32)
    expected = (MODEL_GRID,) * 3
    if volume.shape != expected:
        raise RemoteReconstructionError(
            f"X2CT-GAN devolvio un volumen de {volume.shape} y se esperaba {expected}."
        )
    if not np.isfinite(volume).all():
        raise RemoteReconstructionError("X2CT-GAN devolvio valores no numericos.")
    low, high = config.HU_WINDOW
    reoriented = np.flip(volume, axis=FLIPPED_AXES)
    return np.ascontiguousarray(np.clip((reoriented - low) / (high - low), 0.0, 1.0), np.float32)


def display_voxel_mm(metadata: Mapping[str, Any]) -> tuple[tuple[float, float, float], bool]:
    """Tamano de voxel (R, A, S) con que se muestra el volumen y si las medidas son relativas.

    El orden es el mismo de X2CT (x, y, z): invertir un eje no cambia su tamano.
    """
    geometry = metadata.get("preprocesamiento", {}) or {}
    if geometry.get("mm_por_pixel_128"):
        x, y, z = (float(value) for value in metadata["volumen"]["voxel_mm"])
        return (x, y, z), False
    rows, columns = _input_size(metadata)
    horizontal = columns / MODEL_GRID
    vertical = rows / MODEL_GRID
    return (horizontal, horizontal, vertical), True


def _input_size(metadata: Mapping[str, Any]) -> tuple[int, int]:
    """(filas, columnas) de la placa original; sin dato, una placa cuadrada."""
    entrada = metadata.get("entrada", {}) or {}
    rows = int(entrada.get("filas") or MODEL_GRID)
    columns = int(entrada.get("columnas") or MODEL_GRID)
    return rows, columns
