"""Piezas de EN-2 que no son la red: ventanas, limpieza y resumen por region. Solo numpy y scipy.

Migrado sin cambios de logica desde models/en2_inferencia.py (research.md R14): mismas
operaciones, mismo orden y mismos valores por omision. Solo cambian los nombres, al
ingles y snake_case. Las claves del resumen (has_lesion, location, ...) ya estaban en
ingles y no cambian. Los textos para el usuario siguen en espanol.

La igualdad con el original la verifica el caso 4 de la referencia de regresion
(tests/unit/services/test_lung_region_summary.py).
"""

import numpy as np
from scipy import ndimage

# Cuando se confirme la orientacion anatomica de los ejes, se rellena aqui y la
# descripcion de cada lesion pasa a ser anatomica. Mientras tanto es geometrica.
AXIS_NAMES = {
    0: ("inicio del eje 0", "medio del eje 0", "final del eje 0"),
    1: ("inicio del eje 1", "medio del eje 1", "final del eje 1"),
    2: ("inicio del eje 2", "medio del eje 2", "final del eje 2"),
}


class InvalidVolumeError(ValueError):
    """El volumen recibido no cumple el contrato de entrada del segmentador."""


def gaussian_weight_map(side, sigma_rel=0.125):
    """Peso gaussiano de un parche cubico, con maximo 1 en el centro."""
    axis = np.arange(side, dtype=np.float32) - (side - 1) / 2.0
    g = np.exp(-(axis**2) / (2.0 * (sigma_rel * side) ** 2))
    m = g[:, None, None] * g[None, :, None] * g[None, None, :]
    return (m / m.max()).astype(np.float32)


def patch_positions(size, patch, overlap):
    """Inicio de cada parche a lo largo de un eje, con el solape pedido."""
    if size <= patch:
        return [0]
    step = max(int(patch * (1.0 - overlap)), 1)
    count = int(np.ceil((size - patch) / step)) + 1
    return [int(round(i * (size - patch) / (count - 1))) for i in range(count)]


def clean_mask(binary, min_voxels):
    """Quita las regiones conexas con menos de min_voxels voxeles. Devuelve uint8."""
    if min_voxels <= 1 or not binary.any():
        return binary.astype(np.uint8)
    labels, count = ndimage.label(binary)
    if count == 0:
        return binary.astype(np.uint8)
    sizes = ndimage.sum(binary, labels, range(1, count + 1))
    alive = [i + 1 for i, size in enumerate(sizes) if size >= min_voxels]
    return np.isin(labels, alive).astype(np.uint8) if alive else np.zeros_like(binary, np.uint8)


def describe_position(centroid, shape):
    """Posicion geometrica en tercios por eje. No es una identificacion de lobulo."""
    parts = []
    for axis, (c, n) in enumerate(zip(centroid, shape, strict=False)):
        third = min(int(3 * c / n), 2)
        parts.append(AXIS_NAMES[axis][third])
    return " · ".join(parts)


def max_diameter_mm(region_mask, mm_per_voxel, max_points=2000):
    """Mayor distancia entre dos voxeles de la superficie de la region."""
    border = region_mask & ~ndimage.binary_erosion(region_mask)
    points = np.argwhere(border if border.any() else region_mask).astype(np.float32)
    if len(points) < 2:
        return float(mm_per_voxel)
    if len(points) > max_points:
        step = int(np.ceil(len(points) / max_points))
        points = points[::step]
    largest = 0.0
    for i in range(0, len(points), 256):
        block = points[i : i + 256]
        d = np.sqrt(((block[:, None, :] - points[None, :, :]) ** 2).sum(-1)).max()
        largest = max(largest, float(d))
    return round(largest * mm_per_voxel, 2)


def summarize_regions(mask, probability, mm_per_voxel, min_voxels=0):
    """Agrega la segmentacion por region conexa. Es la estructura del criterio C4."""
    voxel_volume = float(mm_per_voxel) ** 3
    labels, count = ndimage.label(mask > 0)
    regions = []
    for i in range(1, count + 1):
        region = labels == i
        voxels = int(region.sum())
        if voxels < max(min_voxels, 1):
            continue
        confidence = float(probability[region].mean())
        centroid = ndimage.center_of_mass(region)
        regions.append(
            {
                "has_lesion": True,
                "location": describe_position(centroid, mask.shape),
                "volume_mm3": round(voxels * voxel_volume, 2),
                "max_diameter_mm": max_diameter_mm(region, mm_per_voxel),
                "confidence": round(confidence, 4),
                "voxels": voxels,
                "centroid_voxel": [int(round(c)) for c in centroid],
                "confidence_min": round(float(probability[region].min()), 4),
                "confidence_max": round(float(probability[region].max()), 4),
            }
        )
    regions.sort(key=lambda r: r["volume_mm3"], reverse=True)
    for k, region in enumerate(regions, 1):
        region["region_id"] = k
    return regions
