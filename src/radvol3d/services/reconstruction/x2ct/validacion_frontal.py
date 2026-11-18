"""Validacion frontal de X2CT-GAN: algoritmos del script T1 (docs/x2ct, ya validado).

Compara la placa que recibio el modelo con una radiografia simulada obtenida
"aplastando" de frente la TC reconstruida. Las funciones son copia de T1 sin cambios
de logica (proyeccion_frontal, ncc, otsu, _disco, campos_pulmonares, ajuste_escala,
medidas y dice); quien arma el resultado para el sistema es
services/reconstruction/frontal_validation.py.

El volumen se recibe en HU y en la convencion de X2CT (x = horizontal de la placa,
y = AP, z = pies -> cabeza), la del volumen.nii.gz. proyeccion_frontal lo devuelve en la
orientacion de la placa (filas cabeza -> pies, columnas izquierda -> derecha).
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi


def proyeccion_frontal(vol_hu: np.ndarray) -> np.ndarray:
    """Radiografia simulada: promedio de la atenuacion (HU+1000) a lo largo de y (AP),
    en la orientacion de la placa (filas cabeza->pies, columnas izquierda->derecha)."""
    v = np.clip(vol_hu, -1000, 1000) + 1000.0
    p = v.mean(axis=1).T[::-1, :]
    return ((p - p.min()) / (p.max() - p.min() + 1e-8)).astype(np.float32)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = (a - a.mean()) / (a.std() + 1e-8)
    b = (b - b.mean()) / (b.std() + 1e-8)
    return float((a * b).mean())


def otsu(valores: np.ndarray) -> float:
    h, bordes = np.histogram(valores, bins=256, range=(0, 1))
    c = (bordes[:-1] + bordes[1:]) / 2
    w0 = np.cumsum(h); w1 = w0[-1] - w0
    m0 = np.cumsum(h * c) / np.maximum(w0, 1)
    m1 = (np.sum(h * c) - np.cumsum(h * c)) / np.maximum(w1, 1)
    return float(c[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def _disco(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def campos_pulmonares(img: np.ndarray, radio: int = 4, banda: int = 8) -> np.ndarray:
    """Mascara 2D de los dos campos pulmonares (zonas oscuras dentro del torax).
    Se aplica el MISMO metodo a la placa y a la simulada, para que la comparacion sea justa.
    1) quita el fondo negro conectado al borde, 2) umbral de Otsu dentro del cuerpo,
    3) ignora una banda en el borde y separa puentes finos (apertura),
    4) se queda con el componente mas grande de cada mitad que cruce la zona media."""
    s = ndi.gaussian_filter(img, 1.0)
    s = (s - s.min()) / (s.max() - s.min() + 1e-8)
    H, W = s.shape
    fondo = s < 0.08
    etiq, _ = ndi.label(fondo)
    borde = set(np.unique(np.concatenate([etiq[0], etiq[-1], etiq[:, 0], etiq[:, -1]]))) - {0}
    fondo = ndi.binary_dilation(np.isin(etiq, list(borde)), iterations=3)
    cuerpo = ~fondo
    oscuro = (s < otsu(s[cuerpo])) & cuerpo
    oscuro[:banda] = oscuro[-banda:] = False
    oscuro[:, :banda] = oscuro[:, -banda:] = False
    oscuro = ndi.binary_opening(oscuro, structure=_disco(radio))
    etiq, n = ndi.label(oscuro)
    elegidos = []
    for lado in (0, 1):
        mejor = None
        for i in range(1, n + 1):
            f, c = np.nonzero(etiq == i)
            if len(f) < 0.01 * s.size or (c.mean() < W / 2) != (lado == 0):
                continue
            if not ((f >= 0.3 * H) & (f <= 0.6 * H)).any():
                continue
            if mejor is None or len(f) > mejor[0]:
                mejor = (len(f), i)
        if mejor:
            elegidos.append(mejor[1])
    m = ndi.binary_closing(np.isin(etiq, elegidos), structure=_disco(2))
    return ndi.binary_fill_holes(m)


def ajuste_escala(x: np.ndarray, p: np.ndarray) -> dict:
    """Busca la escala (horizontal, vertical) y el desplazamiento que mejor alinean la simulada
    con la placa. Escala 1,00 y desplazamiento 0 = la reconstruccion tiene el mismo tamano
    y la misma posicion que la radiografia de entrada."""
    from scipy.optimize import minimize

    c = (np.array(x.shape) - 1) / 2.0

    def deformar(par):
        sy, sx, dy, dx = par
        mat = np.diag([1.0 / sy, 1.0 / sx])
        off = c - mat @ (c + np.array([dy, dx]))
        return ndi.affine_transform(p, mat, offset=off, order=1, mode="nearest")

    r = minimize(lambda q: -ncc(deformar(q), x), x0=[1.0, 1.0, 0.0, 0.0], method="Powell",
                 bounds=[(0.7, 1.3), (0.7, 1.3), (-15, 15), (-15, 15)], options={"xtol": 1e-3, "ftol": 1e-5})
    sy, sx, dy, dx = r.x
    return {"escala_vertical": float(sy), "escala_horizontal": float(sx),
            "desplaz_vertical_px": float(dy), "desplaz_horizontal_px": float(dx),
            "NCC_tras_ajuste": float(-r.fun)}


def medidas(m: np.ndarray) -> dict:
    """Medidas en pixeles de la rejilla 128 (filas = vertical, columnas = horizontal)."""
    if m.sum() == 0:
        return {}
    filas, cols = np.nonzero(m)
    etiq, n = ndi.label(m)
    pulmones = []
    for i in range(1, n + 1):
        f, c = np.nonzero(etiq == i)
        pulmones.append({"col_media": c.mean(), "alto": f.max() - f.min() + 1, "area": len(f),
                         "vertice": f.min(), "base": f.max()})
    pulmones.sort(key=lambda d: d["col_media"])  # izquierda de la imagen primero
    out = {"ancho_total": cols.max() - cols.min() + 1, "area_total": int(m.sum()),
           "vertice": filas.min(), "base": filas.max(), "n_pulmones": n}
    for nombre, d in zip(["izq_imagen", "der_imagen"], pulmones[:2]):
        out[f"alto_{nombre}"] = d["alto"]
        out[f"area_{nombre}"] = d["area"]
    return out


def dice(a: np.ndarray, b: np.ndarray) -> float:
    s = a.sum() + b.sum()
    return float(2 * (a & b).sum() / s) if s else float("nan")
