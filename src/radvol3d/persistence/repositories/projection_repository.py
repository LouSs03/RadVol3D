"""Acceso a la tabla projection.

Cada fila guarda el angulo, la ruta del .npy dentro del bucket y el nombre
original del archivo. Nunca guarda la imagen.
"""

from typing import Any

from radvol3d.domain.entities import Projection
from radvol3d.domain.exceptions import InvalidProjectionError
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.study_repository import find_study_id
from radvol3d.persistence.storage_layout import validate_projection_angle, validate_study_code


class ProjectionRepository:
    """Guarda y consulta las proyecciones dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def add_many(self, study_code: str, projections: list[Projection]) -> None:
        """Guarda las proyecciones de un estudio.

        Valida los angulos (0, 45, 90 o 135, sin repetir) antes de tocar la base.
        """
        validate_study_code(study_code)
        angles = [validate_projection_angle(p.angle_degrees) for p in projections]
        if len(set(angles)) != len(angles):
            raise InvalidProjectionError("Un angulo de proyeccion no puede repetirse.")
        if not projections:
            return

        study_id = find_study_id(self._connection, study_code)
        for projection in projections:
            execute_translated(
                self._connection,
                "insert into projection (study_id, angle_degrees, file_path, original_name) "
                "values (%s, %s, %s, %s)",
                (
                    study_id,
                    projection.angle_degrees,
                    projection.file_path,
                    projection.original_name,
                ),
            )

    def list_by_study(self, study_code: str) -> list[Projection]:
        """Devuelve las proyecciones del estudio ordenadas por angulo."""
        validate_study_code(study_code)
        rows = execute_translated(
            self._connection,
            "select p.angle_degrees, p.file_path, p.original_name "
            "from projection p join study s on s.study_id = p.study_id "
            "where s.study_code = %s order by p.angle_degrees",
            (study_code,),
        ).fetchall()
        return [
            Projection(
                angle_degrees=row["angle_degrees"],
                file_path=row["file_path"],
                original_name=row["original_name"],
            )
            for row in rows
        ]
