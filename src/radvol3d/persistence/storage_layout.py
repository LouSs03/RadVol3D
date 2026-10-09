"""Rutas de los archivos dentro del bucket.

Este modulo es el unico lugar que decide la ruta de cada archivo. Son funciones
puras: solo calculan texto, no acceden a la base ni al bucket. Todas las rutas
cuelgan del codigo del estudio:

    <study_code>/projections/angle_000.npy   (y 045, 090, 135)
    <study_code>/volume.npy
    <study_code>/segmentation/mask.npy
    <study_code>/segmentation/probability.npy
    <study_code>/segmentation/summary.json
    <study_code>/meshes/organ.glb
    <study_code>/meshes/tumor.glb

La ruta <study_code>/meshes/lesion_<region_id>.glb esta reservada para una malla
por lesion. No se genera ni se registra todavia.
"""

import re

from radvol3d import config
from radvol3d.domain.exceptions import InvalidProjectionError, InvalidStudyIdError

# fullmatch y no "$": un codigo terminado en salto de linea no debe pasar.
STUDY_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_study_code(study_code: str) -> str:
    """Devuelve el codigo si es valido. Si no, lanza InvalidStudyIdError.

    El formato permitido ya excluye '..', la barra invertida, las barras y la
    cadena vacia, que podrian sacar una ruta fuera de la carpeta del estudio.
    """
    if not isinstance(study_code, str) or STUDY_CODE_PATTERN.fullmatch(study_code) is None:
        raise InvalidStudyIdError(
            "El codigo del estudio solo admite letras, digitos, guion y guion bajo (hasta 64)."
        )
    return study_code


def validate_projection_angle(angle_degrees: int) -> int:
    """Devuelve el angulo si es 0, 45, 90 o 135. Si no, lanza InvalidProjectionError."""
    if (
        isinstance(angle_degrees, bool)
        or not isinstance(angle_degrees, int)
        or angle_degrees not in config.PROJECTION_ANGLES
    ):
        raise InvalidProjectionError("El angulo de la proyeccion debe ser 0, 45, 90 o 135 grados.")
    return angle_degrees


def projection_path(study_code: str, angle_degrees: int) -> str:
    """Ruta de la proyeccion de un angulo: angle_000.npy, angle_045.npy, etc."""
    validate_study_code(study_code)
    validate_projection_angle(angle_degrees)
    return f"{study_code}/projections/angle_{angle_degrees:03d}.npy"


def volume_path(study_code: str) -> str:
    """Ruta del volumen reconstruido."""
    return f"{validate_study_code(study_code)}/volume.npy"


def mask_path(study_code: str) -> str:
    """Ruta de la mascara de segmentacion."""
    return f"{validate_study_code(study_code)}/segmentation/mask.npy"


def probability_path(study_code: str) -> str:
    """Ruta de la probabilidad de segmentacion."""
    return f"{validate_study_code(study_code)}/segmentation/probability.npy"


def summary_path(study_code: str) -> str:
    """Ruta del resumen por region."""
    return f"{validate_study_code(study_code)}/segmentation/summary.json"


def organ_mesh_path(study_code: str) -> str:
    """Ruta de la malla del organo."""
    return f"{validate_study_code(study_code)}/meshes/organ.glb"


def tumor_mesh_path(study_code: str) -> str:
    """Ruta de la malla del tumor, que contiene todas las lesiones del estudio."""
    return f"{validate_study_code(study_code)}/meshes/tumor.glb"
