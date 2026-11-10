"""Admision de la radiografia del modo de una radiografia (requisito 9 de la guia).

Se revisa el contenido, no solo la extension: un DICOM valido trae un preambulo de 128
bytes y despues las letras DICM (bytes 128 a 131). Asi un PDF o un ejecutable con la
extension cambiada no llega al bucket ni al servicio externo.

La extension se revisa solo si llega el nombre del archivo: .dcm, .dicom o ninguna,
como los archivos que exportan muchos equipos. El nombre original no se guarda: podria
traer datos del paciente.

Lo que no se puede comprobar aqui: que sea una radiografia de torax frontal (PA). El
modelo solo vio esas, y el servicio tampoco lo revisa. Lo advierte la interfaz.
"""

from pathlib import PurePath

from radvol3d import config
from radvol3d.domain.exceptions import InvalidRadiographError, RadiographTooLargeError


def limit_text() -> str:
    """El limite en MB, como lo lee una persona."""
    return f"{config.MAX_RADIOGRAPH_BYTES / 1_000_000:g} MB"


def is_dicom(content: bytes) -> bool:
    """True si el contenido tiene la marca DICM despues del preambulo de 128 bytes."""
    start = config.DICOM_PREAMBLE_BYTES
    return content[start : start + len(config.DICOM_MAGIC)] == config.DICOM_MAGIC


def validate_radiograph(content: bytes, filename: str | None = None) -> bytes:
    """Devuelve el contenido si es un DICOM aceptable. Si no, lanza un error claro.

    - RadiographTooLargeError si supera config.MAX_RADIOGRAPH_BYTES.
    - InvalidRadiographError si esta vacio, si la extension no es .dcm, .dicom o
      ninguna, o si no tiene la marca DICM.
    """
    if not content:
        raise InvalidRadiographError("La radiografía está vacía.")
    if len(content) > config.MAX_RADIOGRAPH_BYTES:
        raise RadiographTooLargeError(f"La radiografía supera el tamaño máximo de {limit_text()}.")
    if filename is not None:
        extension = PurePath(filename).suffix.lower()
        if extension not in config.RADIOGRAPH_EXTENSIONS:
            raise InvalidRadiographError(
                "La radiografía debe ser un archivo DICOM (.dcm, .dicom o sin extensión)."
            )
    if not is_dicom(content):
        raise InvalidRadiographError(
            "El archivo no es un DICOM válido: falta la marca DICM. Sube la radiografía "
            "tal como la entrega el equipo."
        )
    return content
