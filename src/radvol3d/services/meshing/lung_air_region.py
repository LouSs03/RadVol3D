"""Region del pulmon: el aire que encierra el cuerpo, con densidad de parenquima.

En la ventana de -1000 a 1000 HU el pulmon es oscuro (~ -850 HU) y lo brillante es el
cuerpo que lo rodea. Por eso la region del organo de LargestComponentRegion, aplicada a
un torax, es el cuerpo entero (un bloque de 7 a 17 L) y no el pulmon.

Pasos, todos con umbrales calculados del propio volumen:

1. Tejido: el umbral de Otsu del volumen. Aire puro: un segundo Otsu, solo sobre lo que
   no es tejido; separa el aire de -1000 HU del parenquima.
2. Cuerpo: la envolvente convexa del tejido, corte axial por corte axial. Asi el pulmon
   cuenta como "dentro" aunque el campo de vision corte el cuerpo.
3. Afuera: el aire puro fuera del cuerpo, solo en los cortes con datos. Un estudio que
   termina en medio del pulmon deja cortes vacios que no son "afuera".
4. Candidatos: lo que no es tejido dentro del cuerpo, con una apertura leve. Incluye las
   zonas del pulmon que la reconstruccion deja casi en aire puro (~16 % del pulmon).
5. Se descartan las componentes de aire puro (bolsas exteriores, gas) por su mediana, y
   las que tocan el afuera en buena parte de su superficie (concavidades del cuerpo).
6. Quedan hasta dos componentes (los dos pulmones), con los vasos rellenos.

Si no queda ninguna (un volumen sin aire encerrado, como el fantoma de la referencia),
se usa la region de tejido de LargestComponentRegion: mejor esa malla que ninguna.

Medicion (docs/models/meshing.md): con los volumenes de lung_001, lung_003 y lung_004
se armaron 24 variantes (tamano, rotacion, desplazamiento, espejo, cortes, ruido) para
ajustar y 15 distintas para validar, proyectadas con TA-2 y reconstruidas con EN-1. En
validacion, Dice medio 0,84 contra el pulmon del volumen original (0,02 con la region de
tejido) y 6,6 mm de distancia media entre superficies.
"""

import logging

import numpy as np
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.morphology import ball, convex_hull_image

from radvol3d.services.meshing.organ_region import LargestComponentRegion, OrganRegionStrategy
from radvol3d.services.reconstruction.en1_geometry import ROTATION_AXES

logger = logging.getLogger(__name__)

# Eje craneocaudal: el eje de giro de TA-2, el que no esta en el plano de rotacion.
AXIAL_AXIS = ({0, 1, 2} - set(ROTATION_AXES)).pop()
# Radio de la apertura de los candidatos, en voxeles: quita ruido y puentes finos.
OPENING_RADIUS = 2
# Margen en voxeles para decidir si una componente toca el afuera.
CONTACT_MARGIN = 2
# Hasta cuantas componentes se conservan (los dos pulmones) y que tamano minimo tienen,
# como fraccion de la mayor.
MAX_COMPONENTS = 2
MIN_FRACTION = 0.10
# Ajustados con las 24 variantes de ajuste y validados con las 15 de validacion:
# - mediana de la componente / umbral de aire puro: lo que no es pulmon midio <= 0.58 y
#   el pulmon >= 1.16; el corte va en el medio del hueco.
# - fraccion de la superficie junto al aire puro de afuera: el pulmon midio <= 0.26; el
#   corte queda holgado por encima.
MIN_MEDIAN_OVER_AIR = 0.85
MAX_OUTSIDE_CONTACT = 0.35
# La superficie del pulmon se suaviza como la de las lesiones: con el suavizado de la
# malla de contexto la distancia al pulmon real no mejora (6,6 frente a 6,4 mm) y la
# forma se redondea de mas.
LUNG_SMOOTHING_SIGMA = 1.5
LUNG_LAPLACIAN_ITERATIONS = 5


class LungAirRegion(OrganRegionStrategy):
    """El pulmon como el aire que encierra el cuerpo (ver el docstring del modulo)."""

    smoothing_sigma = LUNG_SMOOTHING_SIGMA
    laplacian_iterations = LUNG_LAPLACIAN_ITERATIONS

    def __init__(self, fallback: OrganRegionStrategy | None = None) -> None:
        self._fallback = fallback or LargestComponentRegion()

    def region(self, volume: np.ndarray) -> np.ndarray:
        volume = np.asarray(volume, dtype=np.float32)
        lungs = lung_region(volume)
        if lungs.any():
            return lungs
        logger.info("El volumen no tiene aire encerrado: se usa la region de tejido.")
        return self._fallback.region(volume)


def density_thresholds(volume: np.ndarray) -> tuple[float, float]:
    """(aire puro, tejido): Otsu del volumen y Otsu de lo que queda por debajo."""
    tissue = float(threshold_otsu(volume))
    low = volume[volume <= tissue]
    air = float(threshold_otsu(low)) if low.size and low.min() < low.max() else 0.0
    return air, tissue


def lung_region(volume: np.ndarray) -> np.ndarray:
    """Mascara booleana del pulmon; vacia si el volumen no tiene aire encerrado."""
    volume = np.asarray(volume, dtype=np.float32)
    empty = np.zeros(volume.shape, dtype=bool)
    if volume.ndim != 3 or not np.isfinite(volume).all() or volume.min() == volume.max():
        return empty
    air_level, tissue_level = density_thresholds(volume)
    tissue = volume > tissue_level
    body = _axial_convex_hull(tissue)
    with_data = tissue.any(axis=_in_plane_axes())
    outside = ~tissue & ~body & (volume <= air_level) & _along_axial(with_data)
    candidates = ndimage.binary_opening(body & ~tissue, structure=ball(OPENING_RADIUS))
    labels, count = ndimage.label(candidates)
    if count == 0:
        return empty
    index = np.arange(1, count + 1)
    sizes = ndimage.sum(candidates, labels, index).astype(np.float64)
    shell = candidates & ~ndimage.binary_erosion(candidates)
    near_outside = shell & ndimage.binary_dilation(outside, iterations=CONTACT_MARGIN)
    contact = ndimage.sum(near_outside, labels, index) / np.maximum(
        ndimage.sum(shell, labels, index), 1
    )
    medians = np.asarray(ndimage.median(volume, labels, index), dtype=np.float64)
    is_lung = (medians >= MIN_MEDIAN_OVER_AIR * air_level) & (contact <= MAX_OUTSIDE_CONTACT)
    accepted = index[is_lung]
    if accepted.size == 0:
        return empty
    accepted_sizes = sizes[accepted - 1]
    order = np.argsort(accepted_sizes)[::-1][:MAX_COMPONENTS]
    keep = [
        accepted[i] for i in order if accepted_sizes[i] >= MIN_FRACTION * accepted_sizes.max()
    ]
    return _fill_axial_holes(np.isin(labels, keep))


def _in_plane_axes() -> tuple[int, int]:
    return tuple(axis for axis in range(3) if axis != AXIAL_AXIS)


def _along_axial(flags: np.ndarray) -> np.ndarray:
    """Un vector por corte axial, con la forma que se difunde sobre el volumen."""
    shape = [1, 1, 1]
    shape[AXIAL_AXIS] = flags.size
    return flags.reshape(shape)


def _axial_convex_hull(mask: np.ndarray) -> np.ndarray:
    """Envolvente convexa de la mascara en cada corte axial."""
    slices = np.moveaxis(mask, AXIAL_AXIS, 0)
    hull = np.zeros_like(slices)
    for z, axial in enumerate(slices):
        if axial.any():
            hull[z] = convex_hull_image(axial)
    return np.moveaxis(hull, 0, AXIAL_AXIS)


def _fill_axial_holes(mask: np.ndarray) -> np.ndarray:
    """Rellena los huecos de cada corte axial: los vasos dentro del pulmon."""
    slices = np.moveaxis(mask, AXIAL_AXIS, 0)
    filled = np.stack([ndimage.binary_fill_holes(axial) for axial in slices])
    return np.moveaxis(filled, 0, AXIAL_AXIS)
