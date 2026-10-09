"""Acceso a la tabla patient.

Busca o registra al paciente de un estudio (research.md R5):

- Con DNI: si ya esta registrado, devuelve esa fila sin modificarla. Si no, crea un
  paciente con los datos recibidos.
- Con nombre o apellido pero sin DNI: no hay con que identificar a la persona, asi
  que crea un paciente nuevo. No se busca por nombre.
- Sin ningun dato personal: devuelve el paciente de referencia PAC000000.

El DNI, el nombre y el apellido nunca aparecen en los mensajes de error.
"""

import re
from typing import Any

from radvol3d.domain.entities import Patient, PatientDetails
from radvol3d.domain.exceptions import (
    InvalidPatientDataError,
    PatientCodeExhaustedError,
    PersistenceError,
)
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.row_mapping import patient_from_row

REFERENCE_PATIENT_CODE = "PAC000000"

# El DNI debe tener exactamente ocho digitos y ser unico cuando se registra.
NATIONAL_ID_PATTERN = re.compile(r"[0-9]{8}")
# Formato del codigo de los pacientes nuevos: PAC mas seis digitos.
PATIENT_CODE_PATTERN = re.compile(r"PAC[0-9]{6}")
MAX_PATIENT_NUMBER = 999_999

# Identificador arbitrario del candado de PostgreSQL que serializa las altas de
# pacientes. Solo importa que sea siempre el mismo.
PATIENT_CODE_LOCK_ID = 7_302_001

_PATIENT_COLUMNS = "patient_code, first_name, last_name, national_id"


class PatientRepository:
    """Identifica o registra pacientes dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def find_or_create(self, details: PatientDetails | None) -> Patient:
        """Devuelve el paciente que corresponde a los datos, creandolo si hace falta."""
        first_name, last_name, national_id = self._clean(details)
        if national_id is not None and NATIONAL_ID_PATTERN.fullmatch(national_id) is None:
            raise InvalidPatientDataError("El DNI debe tener exactamente ocho digitos.")

        if first_name is None and last_name is None and national_id is None:
            return self._reference_patient()

        # El candado se libera solo al confirmar o revertir la transaccion.
        execute_translated(
            self._connection, "select pg_advisory_xact_lock(%s)", (PATIENT_CODE_LOCK_ID,)
        )
        if national_id is not None:
            existing = self._find_by_national_id(national_id)
            if existing is not None:
                return existing
        return self._insert(self._next_code(), first_name, last_name, national_id)

    def get_by_code(self, patient_code: str) -> Patient | None:
        """Devuelve el paciente con ese codigo, o None si no existe."""
        row = execute_translated(
            self._connection,
            f"select {_PATIENT_COLUMNS} from patient where patient_code = %s",
            (patient_code,),
        ).fetchone()
        return patient_from_row(row) if row is not None else None

    @staticmethod
    def _clean(details: PatientDetails | None) -> tuple[str | None, str | None, str | None]:
        """Quita espacios de los tres campos. Un campo en blanco cuenta como ausente."""
        if details is None:
            return None, None, None

        def clean(value: str | None) -> str | None:
            return value.strip() or None if value is not None else None

        return clean(details.first_name), clean(details.last_name), clean(details.national_id)

    def _reference_patient(self) -> Patient:
        patient = self.get_by_code(REFERENCE_PATIENT_CODE)
        if patient is None:
            raise PersistenceError(
                f"Falta el paciente de referencia {REFERENCE_PATIENT_CODE}. "
                "Aplica docs/database/schema/001_create_tables.sql."
            )
        return patient

    def _find_by_national_id(self, national_id: str) -> Patient | None:
        row = execute_translated(
            self._connection,
            f"select {_PATIENT_COLUMNS} from patient where national_id = %s",
            (national_id,),
        ).fetchone()
        return patient_from_row(row) if row is not None else None

    def _next_code(self) -> str:
        """Siguiente codigo consecutivo. Con ancho fijo, el maximo textual es el numerico."""
        row = execute_translated(
            self._connection,
            "select max(patient_code) as last_code from patient "
            "where patient_code ~ '^PAC[0-9]{6}$'",
        ).fetchone()
        last_code = row["last_code"] if row is not None else None
        number = int(last_code[3:]) + 1 if last_code else 1
        if number > MAX_PATIENT_NUMBER:
            raise PatientCodeExhaustedError(
                "Ya no quedan codigos de paciente disponibles (de PAC000000 a PAC999999)."
            )
        code = f"PAC{number:06d}"
        if PATIENT_CODE_PATTERN.fullmatch(code) is None:
            raise PatientCodeExhaustedError("No se pudo generar un codigo de paciente valido.")
        return code

    def _insert(
        self,
        patient_code: str,
        first_name: str | None,
        last_name: str | None,
        national_id: str | None,
    ) -> Patient:
        row = execute_translated(
            self._connection,
            "insert into patient (patient_code, first_name, last_name, national_id) "
            f"values (%s, %s, %s, %s) returning {_PATIENT_COLUMNS}",
            (patient_code, first_name, last_name, national_id),
        ).fetchone()
        if row is None:
            raise PersistenceError("No se pudo registrar al paciente.")
        return patient_from_row(row)
