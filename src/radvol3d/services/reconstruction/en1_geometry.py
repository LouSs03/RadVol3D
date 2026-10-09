"""Operadores geometricos y calibracion de EN-1 (TA-1, TA-2 y TA-3). Solo numpy y scipy.

Migrado sin cambios de logica desde models/en1_inferencia_nuevo (1).py (research.md R14):
mismas operaciones, mismo orden, mismos valores por omision y mismas constantes. Solo
cambian los nombres, al ingles y snake_case. La igualdad numerica con el original la
verifica la prueba de regresion "ml".

Cambiar cualquiera de estas piezas invalida las metricas reportadas de EN-1. Por eso
viven aqui y no como parametros sueltos del servicio.

Que espera la reconstruccion en la entrada: un arreglo (4, 128, 128) float32 con las
integrales de linea del volumen normalizado, en el convenio que produce TA-2: cuatro
vistas a 0, 45, 90 y 135 grados, haz paralelo, sin normalizar por el espesor. No son
radiografias clinicas crudas: convertir una radiografia real a este convenio es un paso
de calibracion que el proyecto todavia no aborda.
"""

import numpy as np
from scipy import ndimage

# ---------------------------------------------------------------------------
# Constantes del dominio. Fijadas en TA-1 y TA-2: el modelo se entreno con estos
# valores exactos.
# ---------------------------------------------------------------------------

G = 128  # rejilla del volumen
FOV_MM = 320.0  # campo de vision, 2,50 mm por voxel
HU_MIN, HU_MAX = -1000.0, 1000.0  # ventana Hounsfield mapeada a [0, 1]

ANGLES = (0.0, 45.0, 90.0, 135.0)  # cuatro vistas sobre 180 grados
ROTATION_AXES = (0, 1)  # plano de giro, ejes de numpy
INTEGRATION_AXIS = 1  # el rayo viaja por este eje
DETECTOR_AXIS = 1  # eje a filtrar, dentro del plano de giro

# Valores medidos en TA-3 y usados en el entrenamiento. Si el archivo de pesos los trae
# dentro, los suyos mandan sobre estos.
FILTER_EXPONENT = 0.500
FBP_CALIBRATION = (17.7935, -0.0110)  # canal 0
BP_CALIBRATION = (1.4131, -0.0591)  # canal 1


# ---------------------------------------------------------------------------
# Operadores geometricos (TA-2)
# ---------------------------------------------------------------------------


def project(volume, angles=ANGLES, order=1):
    """Volumen (G, G, G) -> radiografias (4, G, G). Se usa para armar entradas de prueba."""
    volume = np.asarray(volume, dtype=np.float32)
    views = []
    for angle in angles:
        rotated = (
            volume
            if angle == 0.0
            else ndimage.rotate(
                volume,
                angle,
                axes=ROTATION_AXES,
                reshape=False,
                order=order,
                mode="constant",
                cval=0.0,
                prefilter=False,
            )
        )
        views.append(rotated.sum(axis=INTEGRATION_AXIS))
    return np.stack(views).astype(np.float32)


def back_project(projections, angles=ANGLES, order=1):
    """Radiografias (4, G, G) -> volumen sucio (G, G, G)."""
    projections = np.asarray(projections, dtype=np.float32)
    count, grid, _ = projections.shape
    if count != len(angles):
        raise ValueError(f"Se esperaban {len(angles)} proyecciones y llegaron {count}")
    accumulated = np.zeros((grid, grid, grid), dtype=np.float32)
    for projection, angle in zip(projections, angles, strict=False):
        extended = np.repeat(
            np.expand_dims(projection, INTEGRATION_AXIS), grid, axis=INTEGRATION_AXIS
        ) / float(grid)
        if angle != 0.0:
            extended = ndimage.rotate(
                extended,
                -angle,
                axes=ROTATION_AXES,
                reshape=False,
                order=order,
                mode="constant",
                cval=0.0,
                prefilter=False,
            )
        accumulated += extended
    return (accumulated / count).astype(np.float32)


# ---------------------------------------------------------------------------
# Filtro y calibracion (TA-3)
# ---------------------------------------------------------------------------


def ramp_filter(
    projections,
    axis=DETECTOR_AXIS,
    exponent=FILTER_EXPONENT,
    window="hann",
    padding=4,
    mode="reflect",
):
    """Filtro de la retroproyeccion filtrada.

    El relleno antes de la FFT no es opcional: la FFT hace convolucion circular y, sin
    rellenar, el filtro envuelve de un borde al otro de la radiografia y produce bandas
    diagonales. El exponente parcial tampoco: con solo cuatro vistas, la rampa completa
    amplifica frecuencias que apenas se midieron.
    """
    p = np.asarray(projections, dtype=np.float32)
    n = p.shape[axis]
    padded_length = int(2 ** np.ceil(np.log2(max(2, int(padding) * n))))
    width = [(0, 0)] * p.ndim
    width[axis] = (0, padded_length - n)
    try:
        padded = np.pad(p, width, mode=mode)
    except Exception:
        padded = np.pad(p, width, mode="edge")

    frequencies = np.fft.rfftfreq(padded_length).astype(np.float32)
    ramp = (2.0 * frequencies) ** float(exponent)
    if window == "hann":
        ramp = ramp * (0.5 + 0.5 * np.cos(np.pi * frequencies / frequencies[-1]))
    ramp[0] = ramp[1] if exponent > 0 else 1.0

    shape = [1] * p.ndim
    shape[axis] = ramp.size
    filtered = np.fft.irfft(
        np.fft.rfft(padded, axis=axis) * ramp.reshape(shape), n=padded_length, axis=axis
    )
    cut = [slice(None)] * p.ndim
    cut[axis] = slice(0, n)
    return filtered[tuple(cut)].astype(np.float32)


def apply_affine(volume, calibration):
    """y = a*x + b, recortado a [0, 1]."""
    a, b = calibration
    return np.clip(np.asarray(volume, dtype=np.float32) * a + b, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Entrada de prueba
# ---------------------------------------------------------------------------


def ellipsoid_phantom(grid=G, semi_axes=(0.34, 0.26, 0.18), center=(0.0, 0.05, -0.04)):
    """Elipsoide con tres semiejes distintos: delata ejes permutados."""
    c = (np.arange(grid) - (grid - 1) / 2.0) / (grid / 2.0)
    z, y, x = np.meshgrid(c, c, c, indexing="ij")
    r = (
        ((z - center[0]) / semi_axes[0]) ** 2
        + ((y - center[1]) / semi_axes[1]) ** 2
        + ((x - center[2]) / semi_axes[2]) ** 2
    )
    return (r <= 1.0).astype(np.float32) * 0.6
