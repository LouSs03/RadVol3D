"""Separa la mascara en una region por lesion, en el orden del resumen (research.md R9).

El resumen de la segmentacion trae, por cada region, cuantos voxeles tiene (voxels) y
su centroide redondeado (centroid_voxel). Aqui se etiqueta la mascara con la misma
conectividad que usa summarize_regions (la de scipy.ndimage.label por omision) y cada
region se empareja con la componente que tiene esos mismos dos valores.

En EN-2 la mascara ya esta limpia (clean_mask) y el resumen se calcula sobre esa misma
mascara, asi que cada componente tiene exactamente una region. Si una region no
encuentra su componente, es un error de programa: se lanza ValueError y la etapa de
mallas falla, porque mezclar lesiones seria peor que fallar.

Solo numpy y scipy.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy import ndimage


def split_lesion_masks(mask: Any, regions: Sequence[Mapping[str, Any]]) -> list[np.ndarray]:
    """Una mascara booleana por region, en el mismo orden que regions."""
    if not regions:
        return []
    labels, count = ndimage.label(np.asarray(mask) > 0)
    components = {}
    for label in range(1, count + 1):
        component = labels == label
        centroid = ndimage.center_of_mass(component)
        key = (int(component.sum()), tuple(int(round(c)) for c in centroid))
        components.setdefault(key, []).append(component)

    masks = []
    for position, region in enumerate(regions, 1):
        try:
            key = (int(region["voxels"]), tuple(int(c) for c in region["centroid_voxel"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                f"La region {position} del resumen no trae voxels y centroid_voxel."
            ) from None
        candidates = components.get(key)
        if not candidates:
            raise ValueError(
                f"La region {position} del resumen no coincide con ninguna componente "
                "de la mascara."
            )
        masks.append(candidates.pop(0))
    return masks
