"""Acceso a la tabla organ.

Es de solo lectura: los dos organos del alcance vigente (lung y liver) vienen
precargados por el esquema.
"""

from typing import Any

from radvol3d.domain.entities import Organ
from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import UnknownOrganError
from radvol3d.persistence.database_errors import execute_translated


def parse_organ_name(name: OrganName | str) -> OrganName:
    """Convierte el texto en OrganName. Un organo fuera del alcance lanza UnknownOrganError."""
    try:
        return OrganName(name)
    except ValueError:
        raise UnknownOrganError(
            "El organo no esta dentro del alcance del sistema (lung o liver)."
        ) from None


class OrganRepository:
    """Consulta los organos dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def list_all(self) -> list[Organ]:
        """Devuelve todos los organos registrados."""
        rows = execute_translated(
            self._connection,
            "select organ_id, name, anatomical_region from organ order by organ_id",
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def get_by_name(self, name: OrganName | str) -> Organ:
        """Devuelve el organo con ese nombre, o lanza UnknownOrganError."""
        organ_name = parse_organ_name(name)
        row = execute_translated(
            self._connection,
            "select organ_id, name, anatomical_region from organ where name = %s",
            (organ_name.value,),
        ).fetchone()
        if row is None:
            raise UnknownOrganError("El organo pedido no esta registrado en la base de datos.")
        return self._to_entity(row)

    @staticmethod
    def _to_entity(row: Any) -> Organ:
        return Organ(
            organ_id=row["organ_id"],
            name=OrganName(row["name"]),
            anatomical_region=row["anatomical_region"],
        )
