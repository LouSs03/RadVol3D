"""Lee las proyecciones subidas y las entrega a la tuberia sin reescalarlas.

Las proyecciones son .npy en el convenio de TA-2: integrales de linea del volumen
normalizado, sin normalizar ellas mismas. Asi se entreno y se midio EN-1, y por eso
aqui no se toca su escala (research.md R4).

La lectura tiene dos pasos (research.md R5):

- parse: la admision. Exige las cuatro proyecciones, valida cada archivo y lo
  convierte a float32. Corre ANTES de registrar el estudio: una entrada invalida no
  crea nada, y register_study ya necesita los arreglos.
- stack: el filtro de la etapa 1. Apila las cuatro en el orden de
  config.PROJECTION_ANGLES.
"""

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from radvol3d import config
from radvol3d.domain.exceptions import InvalidProjectionError

# Los seis primeros bytes de todo archivo .npy.
NPY_MAGIC = b"\x93NUMPY"


@dataclass(frozen=True)
class ProjectionFile:
    """Un archivo de proyeccion tal como llega: su angulo, sus bytes y su nombre.

    content son los bytes de un .npy en el convenio de TA-2 (integrales de linea sin
    normalizar). La presentacion arma uno por cada archivo subido.
    """

    angle_degrees: int
    content: bytes
    original_name: str | None = None


class ProjectionLoader:
    """Lee las cuatro proyecciones de entrada, sin reescalarlas."""

    def parse(self, files: Sequence[ProjectionFile]) -> dict[int, np.ndarray]:
        """Devuelve un arreglo (N, N) float32 por angulo, o lanza InvalidProjectionError.

        Los mensajes nombran solo el angulo: nunca el contenido del archivo.
        """
        self._check_angles([projection.angle_degrees for projection in files])
        return {
            projection.angle_degrees: self._read(projection.angle_degrees, projection.content)
            for projection in files
        }

    def stack(self, by_angle: Mapping[int, np.ndarray]) -> np.ndarray:
        """Apila las proyecciones en (4, N, N) float32, en el orden de los angulos."""
        return np.stack(
            [by_angle[angle] for angle in config.PROJECTION_ANGLES]
        ).astype(np.float32, copy=False)

    @staticmethod
    def _check_angles(angles: list[int]) -> None:
        """Exige una proyeccion por cada angulo de config, sin repetidos ni sobrantes."""
        expected = config.PROJECTION_ANGLES
        unknown = sorted({a for a in angles if a not in expected}, key=str)
        if unknown:
            raise InvalidProjectionError(
                f"El angulo {unknown[0]} no es valido: deben ser 0, 45, 90 y 135 grados."
            )
        repeated = sorted({a for a in angles if angles.count(a) > 1})
        if repeated:
            raise InvalidProjectionError(f"El angulo {repeated[0]} llego repetido.")
        missing = [a for a in expected if a not in angles]
        if missing:
            listed = ", ".join(str(a) for a in missing)
            raise InvalidProjectionError(
                f"Falta la proyeccion de {listed} grados: se necesitan las cuatro."
            )

    @staticmethod
    def _read(angle: int, content: bytes) -> np.ndarray:
        """Lee un .npy numerico, del tamano de la rejilla y sin NaN ni infinitos."""
        if not content.startswith(NPY_MAGIC):
            raise InvalidProjectionError(
                f"La proyeccion de {angle} grados no es un .npy: "
                "solo se acepta .npy en el convenio de TA-2."
            )
        try:
            array = np.load(io.BytesIO(content), allow_pickle=False)
        except (ValueError, OSError, EOFError):
            # allow_pickle=False rechaza los arreglos con objetos sin deserializarlos.
            raise InvalidProjectionError(
                f"La proyeccion de {angle} grados no se puede leer como un .npy numerico."
            ) from None
        if not np.issubdtype(array.dtype, np.number) or np.issubdtype(
            array.dtype, np.complexfloating
        ):
            raise InvalidProjectionError(
                f"La proyeccion de {angle} grados debe contener numeros reales."
            )
        expected_shape = (config.GRID_SIZE, config.GRID_SIZE)
        if array.shape != expected_shape:
            raise InvalidProjectionError(
                f"La proyeccion de {angle} grados debe medir {expected_shape}."
            )
        if not np.isfinite(array).all():
            raise InvalidProjectionError(
                f"La proyeccion de {angle} grados tiene valores NaN o infinitos."
            )
        return np.asarray(array, dtype=np.float32)
