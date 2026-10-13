"""Strategy para elegir que parte del volumen se convierte en la malla del organo.

La malla del organo sale de una region binaria del volumen reconstruido. Que region es
depende del organo: en el pulmon es el aire que encierra el cuerpo (LungAirRegion); en
un organo denso, el tejido mas brillante (LargestComponentRegion). Cada organo recibe su
estrategia desde la fabrica, asi la generacion de mallas no tiene condicionales por
organo (Principio II).

Cada estrategia trae tambien cuanto se suaviza su superficie: la malla de contexto de un
organo denso se redondea mas que la del pulmon, cuya forma es la que el visor tiene que
mostrar (docs/models/meshing.md).
"""

from abc import ABC, abstractmethod

import numpy as np
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.morphology import ball

# Radio de la esfera de la apertura morfologica de la region, en voxeles. Una esfera y no
# la cruz por defecto de scipy: la cruz deja contornos de diamante y, con las iteraciones
# necesarias para quitar las puntas, deja el organo al 31 %. Con radio 6 (15 mm) las
# puntas pasan a lobulos suaves y queda el 90 % (prueba_real_001).
OPENING_RADIUS = 6
# Suavizado de la malla de contexto: desvio del filtro gaussiano (en voxeles) e
# iteraciones del laplaciano. Los lobulos que deja la apertura se ven mejor redondeados.
SMOOTHING_SIGMA = 2.5
LAPLACIAN_ITERATIONS = 10


class OrganRegionStrategy(ABC):
    """Elige la region del volumen que se convierte en la malla del organo."""

    # Suavizado de la superficie de esta region (ver MarchingCubesStrategy._smooth_mesh).
    smoothing_sigma: float = SMOOTHING_SIGMA
    laplacian_iterations: int = LAPLACIAN_ITERATIONS

    @abstractmethod
    def region(self, volume: np.ndarray) -> np.ndarray:
        """Recibe el volumen (N, N, N) float32 en [0, 1] y devuelve una mascara booleana
        de la misma forma. Vacia si no hay region: nunca lanza por el contenido."""


class LargestComponentRegion(OrganRegionStrategy):
    """El tejido mas brillante: Otsu, la componente conexa mas grande y sus huecos rellenos.

    Sirve para un organo que en el volumen es mas denso que lo que lo rodea. No sirve
    para el pulmon: en la ventana de -1000 a 1000 HU el pulmon es aire, y lo brillante es
    el cuerpo que lo rodea (por eso el pulmon usa LungAirRegion).
    """

    def region(self, volume: np.ndarray) -> np.ndarray:
        volume = np.asarray(volume, dtype=np.float32)
        if not np.isfinite(volume).all() or float(volume.min()) == float(volume.max()):
            return np.zeros(volume.shape, dtype=bool)
        foreground = volume > threshold_otsu(volume)
        # La apertura recorta las puntas en estrella que deja reconstruir con solo cuatro
        # angulos. Va antes de elegir la region: si al recortar se desprende un fragmento,
        # queda como isla y se descarta. Si el organo es mas fino que la esfera y la
        # apertura lo borra entero, se usa la region sin abrir.
        opened = ndimage.binary_opening(foreground, structure=ball(OPENING_RADIUS))
        if opened.any():
            foreground = opened
        labels, count = ndimage.label(foreground)
        if count == 0:
            return foreground
        sizes = ndimage.sum(foreground, labels, range(1, count + 1))
        largest = labels == int(np.argmax(sizes)) + 1
        return ndimage.binary_fill_holes(largest)
