"""Traduce los errores de psycopg a errores del dominio.

El mensaje de psycopg incluye el valor que causo el error ("Key (national_id)=
(12345678) already exists"). Por eso los errores del dominio llevan mensajes
propios, en espanol, y nunca copian el texto de psycopg. De la causa solo se
registran el sqlstate y el nombre de la restriccion.

La funcion devuelve el error; quien la llama lo lanza con "raise ... from None",
para que la causa original no aparezca encadenada en una traza.
"""

import logging
from typing import Any

import psycopg
from psycopg import errors as pg_errors

from radvol3d.domain.exceptions import (
    DatabaseUnavailableError,
    DuplicateStudyError,
    InvalidLesionError,
    InvalidPatientDataError,
    InvalidProjectionError,
    InvalidStudyIdError,
    PersistenceError,
    RadVol3DError,
)

logger = logging.getLogger(__name__)

# Restriccion del esquema -> (error del dominio, mensaje en espanol).
# Los nombres *_key los genera PostgreSQL por convencion: las pruebas de
# integracion los confirmaron el 2026-10-09 contra el catalogo real (tasks.md, T056).
_CONSTRAINT_ERRORS: dict[str, tuple[type[RadVol3DError], str]] = {
    "study_study_code_key": (DuplicateStudyError, "Ya existe un estudio con ese codigo."),
    "study_code_format": (
        InvalidStudyIdError,
        "El codigo del estudio solo admite letras, digitos, guion y guion bajo (hasta 64).",
    ),
    "patient_national_id_format": (
        InvalidPatientDataError,
        "El DNI debe tener exactamente ocho digitos.",
    ),
    "patient_national_id_key": (
        InvalidPatientDataError,
        "Ya hay un paciente registrado con ese DNI.",
    ),
    "patient_code_format": (
        InvalidPatientDataError,
        "El codigo del paciente no cumple el formato permitido.",
    ),
    "patient_patient_code_key": (
        InvalidPatientDataError,
        "Ya existe un paciente con ese codigo.",
    ),
    "projection_angle_allowed": (
        InvalidProjectionError,
        "El angulo de la proyeccion debe ser 0, 45, 90 o 135 grados.",
    ),
    "projection_study_angle_unique": (
        InvalidProjectionError,
        "El estudio ya tiene una proyeccion con ese angulo.",
    ),
    "lesion_volume_positive": (
        InvalidLesionError,
        "El volumen de una lesion debe ser mayor que cero.",
    ),
    "lesion_confidence_range": (
        InvalidLesionError,
        "La confianza de una lesion debe estar entre 0 y 1.",
    ),
}

_UNAVAILABLE_MESSAGE = "No se pudo conectar con la base de datos."
_INTEGRITY_MESSAGE = "La base de datos rechazo la operacion por una regla de integridad."
_GENERIC_MESSAGE = "La base de datos no pudo completar la operacion."


def translate_database_error(error: psycopg.Error) -> RadVol3DError:
    """Devuelve el error del dominio que corresponde a un error de psycopg."""
    constraint_name = _constraint_name(error)
    logger.warning(
        "Error de base de datos traducido: sqlstate=%s restriccion=%s",
        getattr(error, "sqlstate", None),
        constraint_name,
    )

    if isinstance(error, pg_errors.IntegrityError):
        mapped = _CONSTRAINT_ERRORS.get(constraint_name or "")
        if mapped is not None:
            error_type, message = mapped
            return error_type(message)
        return PersistenceError(_INTEGRITY_MESSAGE)

    if isinstance(error, psycopg.OperationalError):
        # PoolTimeout es una subclase de OperationalError.
        return DatabaseUnavailableError(_UNAVAILABLE_MESSAGE)

    return PersistenceError(_GENERIC_MESSAGE)


def _constraint_name(error: psycopg.Error) -> str | None:
    """Nombre de la restriccion violada, si PostgreSQL lo informo."""
    return getattr(error.diag, "constraint_name", None)


def execute_translated(connection: Any, sql: str, params: Any = None) -> Any:
    """Ejecuta una sentencia y traduce cualquier error de psycopg a uno del dominio.

    Lo usan los repositorios para no repetir el try/except en cada consulta. El
    error del dominio se lanza sin encadenar la causa original.
    """
    try:
        return connection.execute(sql, params)
    except psycopg.Error as error:
        raise translate_database_error(error) from None
