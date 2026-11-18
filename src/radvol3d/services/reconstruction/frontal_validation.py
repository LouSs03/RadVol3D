"""Validacion frontal de un estudio de una radiografia reconstruido con X2CT-GAN.

Responde, en cada estudio, si la reconstruccion corresponde a la radiografia de entrada y
si tiene su tamano: compara la placa que recibio el modelo con una radiografia simulada
obtenida "aplastando" de frente la TC reconstruida. Los algoritmos son los de T1, sin
cambios (x2ct/validacion_frontal.py); este modulo arma lo que guarda y muestra el sistema:

- validacion.json: NCC, escala de mejor ajuste (H / V), desplazamiento, Dice 2D de los
  campos pulmonares y su ancho y alto en placa y reconstruccion (en mm si son reales);
- proyeccion_frontal_128.png: la radiografia simulada;
- validacion_superposicion.png: la placa con los contornos de los pulmones de la placa
  en verde y los de la reconstruccion en rojo.

Si campos_pulmonares no encuentra los dos pulmones en alguna de las dos imagenes, la
parte de pulmones queda como no disponible; NCC y escala se informan igual.

Valida forma, posicion y tamano frontal: no el detalle interno ni la profundidad.
"""

import io
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from radvol3d.services.reconstruction.nifti_volume import read_nifti
from radvol3d.services.reconstruction.x2ct.validacion_frontal import (
    ajuste_escala,
    campos_pulmonares,
    dice,
    medidas,
    ncc,
    proyeccion_frontal,
)

SIMULATED_FILE = "proyeccion_frontal_128.png"
OVERLAY_FILE = "validacion_superposicion.png"
VALIDATION_FILE = "validacion.json"
VALIDATION_FILES = (SIMULATED_FILE, OVERLAY_FILE, VALIDATION_FILE)

FORMAT_VERSION = 1
NOTE = "Valida forma, posición y tamaño frontal. No valida el detalle interno ni la profundidad."
# Lo que dio la validacion fuera del sistema con 4 placas reales de LIDC-IDRI (T1).
T1_REFERENCE = {
    "ncc_mismo_paciente": [0.72, 0.82],
    "ncc_otro_paciente_promedio": 0.42,
}

# La superposicion se dibuja 3 veces mas grande que la rejilla, para que se vean los bordes.
OVERLAY_SCALE = 3
INPUT_CONTOUR = (0, 220, 0)  # verde: pulmones de la placa
RECON_CONTOUR = (235, 40, 40)  # rojo: pulmones de la reconstruccion


@dataclass(frozen=True)
class FrontalValidation:
    """La validacion de un estudio: sus valores y las dos imagenes."""

    values: Mapping[str, Any]
    simulated_png: bytes
    overlay_png: bytes

    def files(self) -> dict[str, bytes]:
        """Los tres archivos que se guardan con el estudio."""
        return {
            SIMULATED_FILE: self.simulated_png,
            OVERLAY_FILE: self.overlay_png,
            VALIDATION_FILE: json.dumps(self.values, ensure_ascii=False, indent=2).encode("utf-8"),
        }


def validate(
    volume_hu: np.ndarray,
    placa_128: np.ndarray,
    mm_por_pixel_128: Mapping[str, float] | None = None,
    placa_source: str = "npy",
) -> FrontalValidation:
    """Compara la placa con la radiografia simulada del volumen.

    volume_hu: el volumen de X2CT en HU y en SU convencion (x, y = AP, z), el del
    volumen.nii.gz: no el del sistema (R, A, S), o la orientacion no coincide con la placa.
    placa_128: la placa que vio el modelo, 128 x 128 en [0, 1].
    mm_por_pixel_128: {"vertical", "horizontal"} si el DICOM traia tamano de pixel.
    """
    started = time.perf_counter()
    x = np.asarray(placa_128, dtype=np.float32)
    p = proyeccion_frontal(np.asarray(volume_hu, dtype=np.float32))
    similarity = ncc(p, x)
    fit = ajuste_escala(x, p)
    mask_input, mask_recon = campos_pulmonares(x), campos_pulmonares(p)
    mm = _real_mm(mm_por_pixel_128)

    values: dict[str, Any] = {
        "version_formato": FORMAT_VERSION,
        "placa_usada": placa_source,
        "ncc": round(similarity, 4),
        "ajuste": _fit_values(fit, mm),
        "pulmones": _lung_values(mask_input, mask_recon, mm),
        "mm_por_pixel_128": mm,
        "medidas_en_mm": mm is not None,
        "referencia_t1": T1_REFERENCE,
        "nota": NOTE,
    }
    values["tiempo_s"] = round(time.perf_counter() - started, 3)
    return FrontalValidation(
        values=values,
        simulated_png=_png(_gray_rgb(p)),
        overlay_png=_png(_overlay(x, mask_input, mask_recon)),
    )


def validate_files(files: Mapping[str, bytes]) -> FrontalValidation:
    """La validacion desde los archivos de X2CT-GAN de un estudio (recien hechos o guardados).

    Usa volumen.nii.gz (HU, convencion de X2CT), la placa (.npy si esta; si no, el PNG) y
    metadatos.json para los mm.
    """
    placa, source = placa_from_files(files)
    metadata = json.loads(files["metadatos.json"]) if "metadatos.json" in files else {}
    return validate(
        read_nifti(files["volumen.nii.gz"]),
        placa,
        mm_from_metadata(metadata),
        placa_source=source,
    )


def placa_from_files(files: Mapping[str, bytes]) -> tuple[np.ndarray, str]:
    """La placa del modelo: el .npy exacto si esta; si no (estudios antiguos), el PNG."""
    if "entrada_modelo_128.npy" in files:
        return np.load(io.BytesIO(files["entrada_modelo_128.npy"])).astype(np.float32), "npy"
    image = Image.open(io.BytesIO(files["entrada_modelo_128.png"])).convert("L")
    return np.asarray(image, dtype=np.float32) / 255.0, "png"


def mm_from_metadata(metadata: Mapping[str, Any]) -> Mapping[str, float] | None:
    """El tamano en mm de un pixel de la rejilla 128, si el DICOM lo traia."""
    return (metadata.get("preprocesamiento", {}) or {}).get("mm_por_pixel_128")


def _real_mm(mm: Mapping[str, float] | None) -> dict[str, float] | None:
    if not mm or not mm.get("vertical") or not mm.get("horizontal"):
        return None
    return {"vertical": float(mm["vertical"]), "horizontal": float(mm["horizontal"])}


def _fit_values(fit: Mapping[str, float], mm: Mapping[str, float] | None) -> dict[str, Any]:
    out = {
        "escala_horizontal": round(fit["escala_horizontal"], 4),
        "escala_vertical": round(fit["escala_vertical"], 4),
        "desplazamiento_horizontal_px": round(fit["desplaz_horizontal_px"], 2),
        "desplazamiento_vertical_px": round(fit["desplaz_vertical_px"], 2),
        "ncc_tras_ajuste": round(fit["NCC_tras_ajuste"], 4),
    }
    if mm:
        horizontal_mm = fit["desplaz_horizontal_px"] * mm["horizontal"]
        out["desplazamiento_horizontal_mm"] = round(horizontal_mm, 1)
        out["desplazamiento_vertical_mm"] = round(fit["desplaz_vertical_px"] * mm["vertical"], 1)
    return out


def _lung_values(
    mask_input: np.ndarray, mask_recon: np.ndarray, mm: Mapping[str, float] | None
) -> dict[str, Any]:
    """Dice y medidas de los campos pulmonares; no disponible sin los dos pulmones."""
    a, b = medidas(mask_input), medidas(mask_recon)
    found = {"placa": int(a.get("n_pulmones", 0)), "reconstruccion": int(b.get("n_pulmones", 0))}
    if found["placa"] < 2 or found["reconstruccion"] < 2:
        return {"disponible": False, "pulmones_encontrados": found}
    return {
        "disponible": True,
        "pulmones_encontrados": found,
        "dice_2d": round(dice(mask_input, mask_recon), 4),
        "placa": _size(a, mm),
        "reconstruccion": _size(b, mm),
    }


def _size(m: Mapping[str, Any], mm: Mapping[str, float] | None) -> dict[str, float]:
    width = int(m["ancho_total"])
    height = int(m["base"] - m["vertice"] + 1)
    out: dict[str, float] = {"ancho_px": width, "alto_px": height}
    if mm:
        out["ancho_mm"] = round(width * mm["horizontal"], 1)
        out["alto_mm"] = round(height * mm["vertical"], 1)
    return out


def _gray_rgb(image: np.ndarray) -> np.ndarray:
    gray = np.clip(np.round(np.asarray(image, dtype=np.float32) * 255), 0, 255).astype(np.uint8)
    return np.stack([gray] * 3, axis=-1)


def _overlay(placa: np.ndarray, mask_input: np.ndarray, mask_recon: np.ndarray) -> np.ndarray:
    """La placa (agrandada) con el contorno de cada mascara: verde la placa, rojo la recon."""
    size = placa.shape[0] * OVERLAY_SCALE, placa.shape[1] * OVERLAY_SCALE
    base = Image.fromarray(_gray_rgb(placa)).resize(size[::-1], Image.Resampling.BILINEAR)
    rgb = np.asarray(base).copy()
    for mask, color in ((mask_input, INPUT_CONTOUR), (mask_recon, RECON_CONTOUR)):
        big = np.kron(mask.astype(np.uint8), np.ones((OVERLAY_SCALE, OVERLAY_SCALE), np.uint8)) > 0
        edge = big & ~ndi.binary_erosion(big, iterations=2)
        rgb[edge] = color
    return rgb


def _png(rgb: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, format="PNG")
    return buffer.getvalue()
