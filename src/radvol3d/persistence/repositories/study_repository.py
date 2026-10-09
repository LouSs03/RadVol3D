"""Acceso a la tabla study.

Trabaja con claves naturales: el codigo del estudio, el codigo del paciente y el
nombre del organo. Los ids seriales se resuelven aqui dentro y no salen de la capa.
Las proyecciones, etapas y lesiones las cargan sus propios repositorios: un Study
que sale de aqui trae esas tres listas vacias.
"""

from typing import Any

from radvol3d.domain.entities import Model, Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import PersistenceError, StudyNotFoundError
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.organ_repository import parse_organ_name
from radvol3d.persistence.repositories.row_mapping import model_from_row, patient_from_row
from radvol3d.persistence.storage_layout import validate_study_code

# Un estudio con su organo, su paciente y, si ya se uso, su modelo de reconstruccion.
_SELECT_STUDY = """
    select s.study_code, s.status, s.grid_size, s.total_time_sec, s.created_at,
           o.name as organ_name,
           p.patient_code, p.first_name, p.last_name, p.national_id,
           m.model_name, m.version, m.trained_on, m.description
    from study s
    join organ o on o.organ_id = s.organ_id
    join patient p on p.patient_id = s.patient_id
    left join model m on m.model_id = s.model_id
"""


def find_study_id(connection: Any, study_code: str) -> int:
    """Id interno del estudio. Lo usan los otros repositorios, nunca sale de la capa."""
    validate_study_code(study_code)
    row = execute_translated(
        connection, "select study_id from study where study_code = %s", (study_code,)
    ).fetchone()
    if row is None:
        raise StudyNotFoundError(f"No existe el estudio '{study_code}'.")
    return row["study_id"]


class StudyRepository:
    """Crea y consulta estudios dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def create(self, study_code: str, organ: OrganName | str, patient_code: str) -> Study:
        """Registra un estudio nuevo en estado pending y lo devuelve con su paciente."""
        validate_study_code(study_code)
        organ_name = parse_organ_name(organ)
        row = execute_translated(
            self._connection,
            "insert into study (study_code, patient_id, organ_id) "
            "select %s, p.patient_id, o.organ_id "
            "from patient p cross join organ o "
            "where p.patient_code = %s and o.name = %s "
            "returning study_id",
            (study_code, patient_code, organ_name.value),
        ).fetchone()
        if row is None:
            raise PersistenceError("El paciente o el organo del estudio no estan registrados.")
        return self.get_by_code(study_code)

    def get_by_code(self, study_code: str) -> Study:
        """Devuelve el estudio con ese codigo, o lanza StudyNotFoundError."""
        validate_study_code(study_code)
        row = execute_translated(
            self._connection, _SELECT_STUDY + " where s.study_code = %s", (study_code,)
        ).fetchone()
        if row is None:
            raise StudyNotFoundError(f"No existe el estudio '{study_code}'.")
        return self._to_entity(row)

    def list_recent(self) -> list[Study]:
        """Devuelve los estudios del mas reciente al mas antiguo, sin datos anidados."""
        rows = execute_translated(
            self._connection, _SELECT_STUDY + " order by s.created_at desc, s.study_id desc"
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def lock_status(self, study_code: str) -> StudyStatus:
        """Bloquea la fila del estudio hasta el fin de la transaccion y devuelve su estado.

        Con el bloqueo, nadie puede pasar el estudio a processing entre la comprobacion
        y el borrado.
        """
        validate_study_code(study_code)
        row = execute_translated(
            self._connection,
            "select status from study where study_code = %s for update",
            (study_code,),
        ).fetchone()
        if row is None:
            raise StudyNotFoundError(f"No existe el estudio '{study_code}'.")
        return StudyStatus(row["status"])

    def delete(self, study_code: str) -> None:
        """Borra el estudio. Sus proyecciones, etapas y lesiones caen en cascada."""
        validate_study_code(study_code)
        cursor = execute_translated(
            self._connection, "delete from study where study_code = %s", (study_code,)
        )
        if cursor.rowcount == 0:
            raise StudyNotFoundError(f"No existe el estudio '{study_code}'.")

    def update_status(self, study_code: str, status: StudyStatus | str) -> None:
        """Cambia el estado del estudio.

        La capa no impone el orden de las transiciones (eso lo decide la tuberia):
        solo acepta los cuatro valores de StudyStatus.
        """
        validate_study_code(study_code)
        try:
            study_status = StudyStatus(status)
        except ValueError:
            raise PersistenceError(
                "El estado del estudio debe ser pending, processing, completed o failed."
            ) from None
        cursor = execute_translated(
            self._connection,
            "update study set status = %s where study_code = %s",
            (study_status.value, study_code),
        )
        if cursor.rowcount == 0:
            raise StudyNotFoundError(f"No existe el estudio '{study_code}'.")

    def mark_completed(
        self,
        study_code: str,
        model: Model,
        grid_size: int,
        total_time_sec: float,
    ) -> None:
        """Cierra el estudio: lo deja en completed con su modelo, rejilla y tiempo total.

        Los cuatro datos se escriben en una sola sentencia. Si el modelo no esta
        registrado en el catalogo no se escribe nada: el estudio nunca queda
        completado con el modelo vacio.
        """
        validate_study_code(study_code)
        cursor = execute_translated(
            self._connection,
            "update study set status = %s, model_id = m.model_id, grid_size = %s, "
            "total_time_sec = %s "
            "from model m "
            "where study.study_code = %s and m.model_name = %s and m.version = %s",
            (
                StudyStatus.COMPLETED.value,
                grid_size,
                total_time_sec,
                study_code,
                model.model_name,
                model.version,
            ),
        )
        if cursor.rowcount == 0:
            # Si el estudio no existe, find_study_id lanza StudyNotFoundError.
            find_study_id(self._connection, study_code)
            raise PersistenceError("El modelo no esta registrado en el catalogo de modelos.")

    @staticmethod
    def _to_entity(row: Any) -> Study:
        total_time = row["total_time_sec"]
        return Study(
            study_code=row["study_code"],
            organ=OrganName(row["organ_name"]),
            status=StudyStatus(row["status"]),
            created_at=row["created_at"],
            total_time_sec=float(total_time) if total_time is not None else None,
            patient=patient_from_row(row),
            model=model_from_row(row),
            grid_size=row["grid_size"],
        )
