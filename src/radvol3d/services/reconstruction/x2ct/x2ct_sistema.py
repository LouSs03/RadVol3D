"""x2ct_sistema.py - Adaptador de X2CT-GAN (1 vista) para el sistema RadVol3D.

Tarea C1. Convierte una radiografia (DICOM o imagen) en un paquete de salida
estandar que el sistema puede consumir sin conocer el modelo:

    <carpeta_salida>/
        volumen.nii.gz          volumen 128x128x128 en HU (int16), con mm por voxel
        entrada_modelo_128.png  la imagen EXACTA que vio el modelo (para validar)
        entrada_modelo_128.npy  la misma imagen en float32 [0, 1]
        metadatos.json          tamano original, mm, ejes, tiempos y avisos

No cambia el modelo ni sus pesos: solo lee bien la entrada, guarda los datos
fisicos que el script original descartaba y fija la orientacion de los ejes.

Requisitos (Colab ya trae torch, numpy, pillow y matplotlib):
    pip install pydicom nibabel
    pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg   # solo si el DICOM esta comprimido

Uso:
    # 1) Prueba sin datos (verifica que todo carga y se guarda)
    python x2ct_sistema.py --pesos 30_net_G.pth --autoprueba --salida prueba/

    # 2) Verificar la orientacion con radiografias reales (paso obligatorio una vez)
    python x2ct_sistema.py --pesos 30_net_G.pth --entrada caso1.dcm --salida out1/ --verificar-orientacion

    # 3) Uso normal (lo que llamara el sistema)
    python x2ct_sistema.py --pesos 30_net_G.pth --entrada caso1.dcm --salida out1/

Desde Python (asi lo integrara el backend):
    from x2ct_sistema import ReconstructorX2CT
    rec = ReconstructorX2CT("30_net_G.pth")          # carga una sola vez
    info = rec.reconstruir("caso1.dcm", "out1/")     # devuelve el dict de metadatos
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

VERSION_FORMATO = "1.0"
LADO = 128  # resolucion de entrada y salida del modelo

# ---------------------------------------------------------------------------
# ORIENTACION DEL VOLUMEN CRUDO DEL MODELO
# ---------------------------------------------------------------------------
# El modelo devuelve un arreglo (a0, a1, a2). Por la arquitectura (las capas
# "linker" copian la imagen a lo largo de un eje nuevo insertado en la posicion
# 0) se ESPERA que:
#   a0 = profundidad antero-posterior (AP)
#   a1 = filas de la radiografia (de arriba/cabeza hacia abajo/pies)
#   a2 = columnas de la radiografia (de izquierda a derecha, tal como se ve)
# Esto es una HIPOTESIS. Se confirma con --verificar-orientacion (paso 2) y,
# si el resultado es otro, se corrigen estas constantes. Luego se pone
# ORIENTACION_VERIFICADA = True.
EJE_AP = 0
EJE_FILAS = 1
EJE_COLUMNAS = 2
INVERTIR_FILAS = False      # True si en el volumen crudo la cabeza queda abajo
INVERTIR_COLUMNAS = False   # True si izquierda/derecha salen espejadas respecto a la placa
ANTERIOR_EN_INDICE_0 = True  # False si la columna vertebral aparece al inicio del eje AP
ORIENTACION_VERIFICADA = True

# Conversion de la salida [0, 1] a HU (la misma del script original del modelo)
HU_MIN, HU_MAX = -1000.0, 1000.0


# ---------------------------------------------------------------------------
# 1. Lectura de la radiografia
# ---------------------------------------------------------------------------
def _es_dicom(ruta: Path) -> bool:
    if ruta.suffix.lower() in (".dcm", ".dicom"):
        return True
    try:
        with open(ruta, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def _luts_pydicom():
    """apply_modality_lut / apply_voi_lut en pydicom 3.x o 2.x."""
    try:
        from pydicom.pixels import apply_modality_lut, apply_voi_lut  # pydicom >= 3
    except ImportError:
        from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut  # pydicom 2.x
    return apply_modality_lut, apply_voi_lut


def leer_radiografia(ruta: str | Path, aplicar_voi: bool = True) -> tuple[np.ndarray, dict]:
    """Devuelve (imagen float32 2D, info).

    La imagen queda con la convencion habitual de visualizacion: hueso claro,
    aire oscuro (MONOCHROME2). Si el DICOM es MONOCHROME1 se invierte.
    """
    ruta = Path(ruta)
    avisos: list[str] = []
    info: dict = {"archivo": ruta.name, "avisos": avisos}

    if _es_dicom(ruta):
        import pydicom

        ds = pydicom.dcmread(str(ruta))
        try:
            arr = ds.pixel_array
        except Exception as e:  # DICOM comprimido sin decodificador
            raise RuntimeError(
                f"No se pudo decodificar el DICOM ({e}). Si esta comprimido, instale: "
                "pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg"
            ) from e
        if arr.ndim != 2:
            raise ValueError(f"Se esperaba una radiografia 2D en escala de grises; forma recibida {arr.shape}")

        apply_modality_lut, apply_voi_lut = _luts_pydicom()
        img = apply_modality_lut(arr, ds).astype(np.float32)
        if aplicar_voi and ("WindowCenter" in ds or "VOILUTSequence" in ds):
            try:
                img_voi = apply_voi_lut(img, ds).astype(np.float32)
                # Algunas placas (p. ej. GE DX de LIDC) traen una ventana que no corresponde a sus
                # valores y deja la imagen casi toda blanca o negra. En ese caso se descarta.
                rango = float(img_voi.max() - img_voi.min())
                saturado = float(np.mean((img_voi <= img_voi.min()) | (img_voi >= img_voi.max())))
                if rango <= 0 or saturado > 0.5:
                    info["voi_lut_aplicado"] = False
                    avisos.append(f"Ventana (VOI LUT) del DICOM descartada: saturaba el {saturado:.0%} de la imagen.")
                else:
                    img = img_voi
                    info["voi_lut_aplicado"] = True
            except Exception as e:
                avisos.append(f"No se pudo aplicar VOI LUT ({e}); se usa la imagen sin ventana.")
                info["voi_lut_aplicado"] = False
        else:
            info["voi_lut_aplicado"] = False

        fotometria = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).upper()
        info["photometric"] = fotometria
        info["invertida"] = fotometria == "MONOCHROME1"
        if info["invertida"]:
            img = img.max() - img

        # Tamano del pixel en mm: [fila, columna]
        espaciado, fuente = None, "ninguno"
        if "PixelSpacing" in ds:
            espaciado, fuente = [float(v) for v in ds.PixelSpacing], "PixelSpacing"
        elif "ImagerPixelSpacing" in ds:
            espaciado, fuente = [float(v) for v in ds.ImagerPixelSpacing], "ImagerPixelSpacing"
            emf = getattr(ds, "EstimatedRadiographicMagnificationFactor", None)
            if emf:
                espaciado = [v / float(emf) for v in espaciado]
                fuente = "ImagerPixelSpacing / EstimatedRadiographicMagnificationFactor"
            else:
                avisos.append(
                    "Solo hay ImagerPixelSpacing (plano del detector): las medidas incluyen "
                    "la magnificacion de la placa (~10 %)."
                )
        else:
            avisos.append("El DICOM no trae tamano de pixel: no se pueden dar medidas en mm.")

        info.update(
            tipo="dicom",
            filas=int(arr.shape[0]),
            columnas=int(arr.shape[1]),
            pixel_mm=espaciado,  # [fila, columna] o None
            fuente_pixel_mm=fuente,
            view_position=str(getattr(ds, "ViewPosition", "")) or None,
            modalidad=str(getattr(ds, "Modality", "")) or None,
        )
        if info["view_position"] and info["view_position"].upper() not in ("PA", "AP"):
            avisos.append(f"ViewPosition = {info['view_position']}: el modelo espera una vista frontal (PA/AP).")
    else:
        img = np.asarray(Image.open(ruta).convert("L"), dtype=np.float32)
        info.update(
            tipo="imagen",
            filas=int(img.shape[0]),
            columnas=int(img.shape[1]),
            pixel_mm=None,
            fuente_pixel_mm="ninguno",
            photometric="desconocido (imagen)",
            invertida=False,
            view_position=None,
            modalidad=None,
        )
        avisos.append("Entrada en formato imagen: no trae tamano de pixel, no hay medidas en mm.")

    return img, info


# ---------------------------------------------------------------------------
# 2. Preprocesamiento (identico al script original en el modo 'estirar')
# ---------------------------------------------------------------------------
def preprocesar(img: np.ndarray, info: dict, modo_aspecto: str = "estirar") -> tuple[np.ndarray, dict]:
    """Lleva la placa a 128x128 en [0, 1] y calcula los mm de cada pixel resultante.

    estirar  : reescala directo a 128x128 (lo que hace hoy el modelo). Deforma la
               proporcion, pero se compensa con mm distintos por eje.
    cuadrado : rellena el lado corto con el valor minimo hasta hacerla cuadrada y
               luego reescala. No deforma, pero es un cambio de preprocesamiento:
               usar solo si se comprueba que no empeora las metricas.
    """
    H, W = img.shape
    relleno = {"arriba": 0, "abajo": 0, "izquierda": 0, "derecha": 0}
    if modo_aspecto == "cuadrado":
        lado = max(H, W)
        dy, dx = lado - H, lado - W
        relleno = {"arriba": dy // 2, "abajo": dy - dy // 2, "izquierda": dx // 2, "derecha": dx - dx // 2}
        img = np.pad(img, ((relleno["arriba"], relleno["abajo"]), (relleno["izquierda"], relleno["derecha"])),
                     mode="constant", constant_values=float(img.min()))
    elif modo_aspecto != "estirar":
        raise ValueError("modo_aspecto debe ser 'estirar' o 'cuadrado'")

    Hp, Wp = img.shape
    # Igual que el original: reescalado bilineal y luego normalizacion min-max
    red = np.asarray(Image.fromarray(img.astype(np.float32)).resize((LADO, LADO), Image.Resampling.BILINEAR),
                     dtype=np.float32)
    rango = float(red.max() - red.min())
    red = (red - red.min()) / (rango if rango > 1e-6 else 1.0)

    mm = info.get("pixel_mm")
    geo = {"modo_aspecto": modo_aspecto, "relleno_px": relleno,
           "mm_por_pixel_128": None, "campo_mm": None}
    if mm:
        mm_fila, mm_col = mm
        alto_mm, ancho_mm = Hp * mm_fila, Wp * mm_col
        geo["campo_mm"] = {"alto": round(alto_mm, 2), "ancho": round(ancho_mm, 2)}
        geo["mm_por_pixel_128"] = {"vertical": alto_mm / LADO, "horizontal": ancho_mm / LADO}
    return red.astype(np.float32), geo


# ---------------------------------------------------------------------------
# 3. Modelo
# ---------------------------------------------------------------------------
def _sha256_corto(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()[:12]


def cargar_modelo(ruta_pesos: str | Path, dispositivo: str | None = None):
    """Carga X2CT-GAN de 1 vista (30_net_G.pth) igual que reconstruir_x2ct.py."""
    import torch
    from radvol3d.services.reconstruction.x2ct.x2ct_network import build_x2ct_generator

    if dispositivo is None:
        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    modelo = build_x2ct_generator(input_shape=LADO)
    ck = torch.load(str(ruta_pesos), map_location="cpu", weights_only=True)
    estado = ck["state_dict"] if isinstance(ck, dict) and "state_dict" in ck else ck
    claves = set(modelo.state_dict().keys())
    limpio = {}
    for k, v in estado.items():
        k2 = k[7:] if k.startswith("module.") else k
        if k2 in claves:
            limpio[k2] = v
    modelo.load_state_dict(limpio, strict=True)  # falla si los pesos no son de 1 vista
    modelo.eval().to(dispositivo)
    return modelo, dispositivo


def inferir(modelo, dispositivo: str, x128: np.ndarray) -> np.ndarray:
    import torch

    t = torch.from_numpy(x128).float()[None, None].to(dispositivo)
    with torch.no_grad():
        out = modelo(t)
        out = out[0] if isinstance(out, (list, tuple)) else out
    vol = out.squeeze().float().cpu().numpy()
    if vol.shape != (LADO, LADO, LADO):
        raise RuntimeError(f"Salida inesperada del modelo: {vol.shape}")
    return np.clip(vol, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 4. Orientacion: crudo -> convencion del sistema
# ---------------------------------------------------------------------------
# Convencion de salida (volumen estandar), indices [x, y, z]:
#   x (eje 0) = horizontal de la placa, en el mismo sentido en que se ve la placa
#               (izquierda -> derecha de la imagen)
#   y (eje 1) = profundidad, de anterior (indice 0) a posterior
#   z (eje 2) = vertical, de pies (indice 0) a cabeza  -> los cortes axiales son vol[:, :, k]
def a_estandar(vol_crudo: np.ndarray) -> np.ndarray:
    v = np.transpose(vol_crudo, (EJE_COLUMNAS, EJE_AP, EJE_FILAS))  # -> (columnas, AP, filas)
    if INVERTIR_COLUMNAS:
        v = v[::-1, :, :]
    if not ANTERIOR_EN_INDICE_0:
        v = v[:, ::-1, :]
    # filas van de cabeza (0) a pies; z debe ir de pies a cabeza
    v = v[:, :, ::-1] if not INVERTIR_FILAS else v
    return np.ascontiguousarray(v)


def proyeccion_frontal(vol_std: np.ndarray) -> np.ndarray:
    """Radiografia simulada desde el volumen estandar, en la misma orientacion que la placa
    (filas = cabeza->pies, columnas = izquierda->derecha de la imagen)."""
    p = vol_std.mean(axis=1)          # (x, z)
    return p.T[::-1, :].astype(np.float32)  # (filas, columnas)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = (a - a.mean()) / (a.std() + 1e-8)
    b = (b - b.mean()) / (b.std() + 1e-8)
    return float((a * b).mean())


def verificar_orientacion(vol_crudo: np.ndarray, x128: np.ndarray, carpeta: Path) -> dict:
    """Prueba los 3 ejes (y sus giros) como eje de proyeccion y dice cual reproduce la placa."""
    filas = []
    for eje in range(3):
        p = vol_crudo.mean(axis=eje)
        variantes = {
            "tal cual": p, "transpuesta": p.T,
            "invertir filas": p[::-1], "invertir columnas": p[:, ::-1],
            "transpuesta + invertir filas": p.T[::-1], "transpuesta + invertir columnas": p.T[:, ::-1],
        }
        mejor = max(variantes.items(), key=lambda kv: ncc(kv[1], x128))
        filas.append({"eje": eje, "ncc": round(ncc(mejor[1], x128), 4), "variante": mejor[0]})
    filas.sort(key=lambda r: -r["ncc"])

    print("\nNCC entre la placa de entrada y la proyeccion del volumen crudo a lo largo de cada eje:")
    for r in filas:
        print(f"  eje {r['eje']}: NCC = {r['ncc']:.3f}  ({r['variante']})")
    print(f"Hipotesis actual: EJE_AP = {EJE_AP}. Mejor eje medido: {filas[0]['eje']} "
          f"({'coincide' if filas[0]['eje'] == EJE_AP else 'NO coincide: revisar constantes'})")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        std = a_estandar(vol_crudo)
        fig, ax = plt.subplots(2, 3, figsize=(13, 8.5))
        ax[0, 0].imshow(x128, cmap="gray"); ax[0, 0].set_title("Entrada del modelo (128x128)")
        ax[0, 1].imshow(proyeccion_frontal(std), cmap="gray")
        ax[0, 1].set_title(f"Proyeccion frontal con las constantes\nNCC = {ncc(proyeccion_frontal(std), x128):.3f}")
        ax[0, 2].imshow(x128, cmap="gray"); ax[0, 2].imshow(proyeccion_frontal(std), cmap="magma", alpha=0.45)
        ax[0, 2].set_title("Superposicion")
        zc = std.shape[2] // 2
        ax[1, 0].imshow(std[:, :, zc].T, cmap="gray")  # filas = y (AP), columnas = x
        ax[1, 0].set_title("Corte axial (centro)\narriba = indice 0 de AP (debe ser ANTERIOR)\n"
                           "la columna vertebral debe quedar ABAJO")
        ax[1, 1].imshow(std[:, std.shape[1] // 2, :].T[::-1], cmap="gray")
        ax[1, 1].set_title("Corte coronal (centro)\ncabeza arriba, como la placa")
        ax[1, 2].imshow(std[std.shape[0] // 2, :, :].T[::-1], cmap="gray")
        ax[1, 2].set_title("Corte sagital (centro)\ncabeza arriba")
        for a in ax.ravel():
            a.axis("off")
        fig.tight_layout()
        fig.savefig(carpeta / "orientacion.png", dpi=110)
        plt.close(fig)
        print(f"Figura guardada: {carpeta / 'orientacion.png'}")
    except Exception as e:  # matplotlib es opcional
        print(f"(No se pudo dibujar la figura: {e})")
    return {"ranking_ejes": filas}


# ---------------------------------------------------------------------------
# 5. Guardado
# ---------------------------------------------------------------------------
def guardar_nifti(vol_hu: np.ndarray, voxel_mm: tuple[float, float, float], ruta: Path) -> None:
    import nibabel as nib

    afin = np.diag([voxel_mm[0], voxel_mm[1], voxel_mm[2], 1.0])
    img = nib.Nifti1Image(vol_hu, afin)
    img.header.set_xyzt_units("mm")
    img.header["descrip"] = b"RadVol3D X2CT-GAN 1 vista; ejes x,y,z ver metadatos.json"
    nib.save(img, str(ruta))


# ---------------------------------------------------------------------------
# 6. API para el sistema
# ---------------------------------------------------------------------------
class ReconstructorX2CT:
    """Carga el modelo una sola vez y reconstruye tantas radiografias como se pidan."""

    def __init__(self, ruta_pesos: str | Path, dispositivo: str | None = None):
        self.ruta_pesos = Path(ruta_pesos)
        t0 = time.time()
        self.modelo, self.dispositivo = cargar_modelo(self.ruta_pesos, dispositivo)
        self.t_carga = time.time() - t0
        self.huella = _sha256_corto(self.ruta_pesos)

    def reconstruir(self, entrada: str | Path | None, carpeta_salida: str | Path,
                    modo_aspecto: str = "estirar", verificar: bool = False) -> dict:
        carpeta = Path(carpeta_salida)
        carpeta.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        if entrada is None:  # autoprueba: torax sintetico
            img, info = _placa_sintetica()
        else:
            img, info = leer_radiografia(entrada)
        x128, geo = preprocesar(img, info, modo_aspecto)
        t_pre = time.time() - t0

        t0 = time.time()
        vol_crudo = inferir(self.modelo, self.dispositivo, x128)
        t_inf = time.time() - t0

        extra = verificar_orientacion(vol_crudo, x128, carpeta) if verificar else {}

        vol_std = a_estandar(vol_crudo)
        vol_hu = np.round(vol_std * (HU_MAX - HU_MIN) + HU_MIN).astype(np.int16)

        avisos = list(info.get("avisos", []))
        mmp = geo["mm_por_pixel_128"]
        if mmp:
            # x = horizontal, z = vertical; la profundidad no se puede medir con una vista
            voxel = (mmp["horizontal"], mmp["horizontal"], mmp["vertical"])
            supuesto = "profundidad (y) = tamano horizontal (x); una sola vista no permite medirla"
        else:
            voxel = (1.0, 1.0, 1.0)
            supuesto = "sin tamano de pixel: voxel nominal de 1 mm, las medidas NO son reales"
        if not ORIENTACION_VERIFICADA:
            avisos.append("Orientacion de ejes NO verificada (ORIENTACION_VERIFICADA = False).")

        guardar_nifti(vol_hu, voxel, carpeta / "volumen.nii.gz")
        Image.fromarray((x128 * 255).round().astype(np.uint8)).save(carpeta / "entrada_modelo_128.png")
        np.save(carpeta / "entrada_modelo_128.npy", x128)

        proy = proyeccion_frontal(vol_std)
        meta = {
            "version_formato": VERSION_FORMATO,
            "modelo": {"nombre": "X2CT-GAN", "modo": "1 vista", "pesos": self.ruta_pesos.name,
                       "sha256_12": self.huella},
            "entrada": {k: v for k, v in info.items() if k != "avisos"},
            "preprocesamiento": {"tamano_modelo": [LADO, LADO], "normalizacion": "min-max a [0,1]",
                                 "reescalado": "bilineal", **geo},
            "volumen": {
                "archivo": "volumen.nii.gz", "forma": list(vol_hu.shape), "tipo": "int16",
                "unidades": "HU", "conversion": "HU = v * 2000 - 1000 (v = salida del modelo en [0,1])",
                "rango_hu_real": [int(vol_hu.min()), int(vol_hu.max())],
                "orden_ejes": {
                    "x (eje 0)": "horizontal de la placa, izquierda -> derecha de la imagen tal como se ve",
                    "y (eje 1)": "profundidad, anterior (0) -> posterior",
                    "z (eje 2)": "vertical, pies (0) -> cabeza; cortes axiales = vol[:, :, k]",
                },
                "voxel_mm": [round(v, 4) for v in voxel],
                "supuesto": supuesto,
            },
            "orientacion": {
                "verificada": ORIENTACION_VERIFICADA,
                "constantes": {"EJE_AP": EJE_AP, "EJE_FILAS": EJE_FILAS, "EJE_COLUMNAS": EJE_COLUMNAS,
                               "INVERTIR_FILAS": INVERTIR_FILAS, "INVERTIR_COLUMNAS": INVERTIR_COLUMNAS,
                               "ANTERIOR_EN_INDICE_0": ANTERIOR_EN_INDICE_0},
                "ncc_proyeccion_frontal_vs_entrada": round(ncc(proy, x128), 4),
                **extra,
            },
            "validacion": {"entrada_modelo": "entrada_modelo_128.png / .npy",
                           "proyeccion_frontal": "vol.mean(axis=1).T[::-1] (en v o en HU+1000)"},
            "tiempos_s": {"carga_modelo": round(self.t_carga, 2), "preprocesamiento": round(t_pre, 3),
                          "inferencia": round(t_inf, 3)},
            "dispositivo": self.dispositivo,
            "avisos": avisos,
        }
        with open(carpeta / "metadatos.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta


def _placa_sintetica() -> tuple[np.ndarray, dict]:
    """Torax sintetico asimetrico (para comprobar que el flujo corre; no es una prueba clinica)."""
    H, W = 2000, 1600
    y, x = np.mgrid[:H, :W].astype(np.float32)
    img = np.zeros((H, W), np.float32)
    img[((x - 800) / 650) ** 2 + ((y - 1050) / 850) ** 2 <= 1] = 0.7          # cuerpo
    img[((x - 560) / 220) ** 2 + ((y - 950) / 520) ** 2 <= 1] = 0.25          # pulmon derecho (mas grande)
    img[((x - 1050) / 190) ** 2 + ((y - 1000) / 470) ** 2 <= 1] = 0.25        # pulmon izquierdo
    img[(abs(x - 800) < 60) & (y > 200)] = 0.95                               # columna
    info = {"archivo": "sintetico", "tipo": "sintetico", "filas": H, "columnas": W,
            "pixel_mm": [0.2, 0.2], "fuente_pixel_mm": "sintetico", "photometric": "MONOCHROME2",
            "invertida": False, "view_position": "PA", "modalidad": None,
            "avisos": ["Placa sintetica: solo comprueba el flujo, no la calidad."]}
    return img, info


def main() -> None:
    ap = argparse.ArgumentParser(description="X2CT-GAN 1 vista -> paquete estandar para RadVol3D")
    ap.add_argument("--pesos", default="30_net_G.pth")
    ap.add_argument("--entrada", help="Radiografia frontal (.dcm o imagen)")
    ap.add_argument("--salida", required=True, help="Carpeta de salida")
    ap.add_argument("--modo-aspecto", choices=["estirar", "cuadrado"], default="estirar")
    ap.add_argument("--verificar-orientacion", action="store_true")
    ap.add_argument("--autoprueba", action="store_true", help="Usa una placa sintetica")
    ap.add_argument("--dispositivo", choices=["cpu", "cuda"], default=None)
    a = ap.parse_args()
    if not a.autoprueba and not a.entrada:
        ap.error("indique --entrada o use --autoprueba")

    rec = ReconstructorX2CT(a.pesos, a.dispositivo)
    print(f"Modelo cargado en {rec.dispositivo} en {rec.t_carga:.1f} s (pesos {rec.huella})")
    meta = rec.reconstruir(None if a.autoprueba else a.entrada, a.salida, a.modo_aspecto,
                           verificar=a.verificar_orientacion or a.autoprueba)
    v = meta["volumen"]
    print(f"\nListo en {meta['tiempos_s']['inferencia']:.2f} s de inferencia ({meta['dispositivo']}).")
    print(f"  volumen   : {v['forma']} HU {v['rango_hu_real']}  voxel_mm = {v['voxel_mm']}")
    print(f"  NCC frontal vs entrada: {meta['orientacion']['ncc_proyeccion_frontal_vs_entrada']}")
    for av in meta["avisos"]:
        print(f"  AVISO: {av}")
    print(f"  salida    : {Path(a.salida).resolve()}")


if __name__ == "__main__":
    main()
