"""Acceso a la tabla lesion.

Una fila por region marcada como lesion por el segmentador. El lote de lesiones de
un estudio se valida completo ANTES de insertar nada: si una no cumple las reglas,
se rechaza el lote entero y no se guarda ninguna.

Reglas (las mismas del esquema, que sigue activo como ultima defensa):
volume_mm3 > 0 (numeric(12, 2)); 0 <= confidence <= 1 (numeric(5, 4)); location
no vacia (varchar(128)); max_diameter_mm opcional (numeric(8, 2)).

La columna organ (migracion 002) no se recibe: el insert la toma del organo del
estudio, asi no puede quedar desalineada. Lesion.organ se ignora al guardar y se
llena al leer.
"""

from collections.abc import Iterable
from typing import Any

from radvol3d.domain.entities import Lesion
from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import InvalidLesionError
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.study_repository import find_study_id
from radvol3d.persistence.storage_layout import validate_study_code

MAX_LOCATION_LENGTH = 128


def _is_number(value: object) -> bool:
    """True para int y float. Un bool no cuenta aunque Python lo trate como int."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def validate_lesion(lesion: Lesion) -> None:
    """Lanza InvalidLesionError si la lesion no cumple las reglas de los datos."""
    location = lesion.location
    if not isinstance(location, str) or not location.strip():
        raise InvalidLesionError("La ubicacion de una lesion es obligatoria.")
    if len(location) > MAX_LOCATION_LENGTH:
        raise InvalidLesionError(
            f"La ubicacion de una lesion admite hasta {MAX_LOCATION_LENGTH} caracteres."
        )
    for name, value in (("volumen", lesion.volume_mm3), ("confianza", lesion.confidence)):
        if not _is_number(value):
            raise InvalidLesionError(f"El {name} de una lesion debe ser un numero.")
    if lesion.max_diameter_mm is not None and not _is_number(lesion.max_diameter_mm):
        raise InvalidLesionError("El diametro maximo de una lesion debe ser un numero.")
    # "not (x > 0)" y no "x <= 0": asi un NaN tambien se rechaza.
    if not lesion.volume_mm3 > 0:
        raise InvalidLesionError("El volumen de una lesion debe ser mayor que cero.")
    if not 0 <= lesion.confidence <= 1:
        raise InvalidLesionError("La confianza de una lesion debe estar entre 0 y 1.")


def validate_lesions(lesions: Iterable[Lesion]) -> None:
    """Valida todo el lote. Si una lesion no cumple, lanza el error y nada se guarda."""
    for lesion in lesions:
        validate_lesion(lesion)


class LesionRepository:
    """Guarda y consulta lesiones dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def add_many(self, study_code: str, lesions: list[Lesion]) -> None:
        """Guarda el lote de lesiones del estudio.

        Valida el lote completo antes de tocar la base. Las filas se insertan dentro
        de la unidad de trabajo del llamador, asi que se confirman o se revierten juntas.
        """
        validate_study_code(study_code)
        validate_lesions(lesions)
        if not lesions:
            return

        study_id = find_study_id(self._connection, study_code)
        for lesion in lesions:
            execute_translated(
                self._connection,
                "insert into lesion "
                "(study_id, location, volume_mm3, max_diameter_mm, confidence, mesh_path, organ) "
                "select %s, %s, %s, %s, %s, %s, o.name "
                "from study s join organ o on o.organ_id = s.organ_id where s.study_id = %s",
                (
                    study_id,
                    lesion.location,
                    lesion.volume_mm3,
                    lesion.max_diameter_mm,
                    lesion.confidence,
                    lesion.mesh_path,
                    study_id,
                ),
            )

    def list_by_study(self, study_code: str) -> list[Lesion]:
        """Devuelve las lesiones del estudio en el orden en que se guardaron."""
        validate_study_code(study_code)
        rows = execute_translated(
            self._connection,
            "select l.location, l.volume_mm3, l.max_diameter_mm, l.confidence, l.mesh_path, "
            "l.organ "
            "from lesion l join study s on s.study_id = l.study_id "
            "where s.study_code = %s order by l.lesion_id",
            (study_code,),
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: Any) -> Lesion:
        diameter = row["max_diameter_mm"]
        organ = row["organ"]
        return Lesion(
            location=row["location"],
            volume_mm3=float(row["volume_mm3"]),
            confidence=float(row["confidence"]),
            max_diameter_mm=float(diameter) if diameter is not None else None,
            mesh_path=row["mesh_path"],
            organ=OrganName(organ) if organ is not None else None,
        )
