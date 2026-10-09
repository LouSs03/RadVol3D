"""Pruebas de la traduccion de errores de psycopg a errores del dominio."""

import logging

import pytest
from psycopg_pool import PoolTimeout

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
from radvol3d.persistence.database_errors import execute_translated, translate_database_error
from tests.fixtures.fake_database import (
    FakeCheckViolation,
    FakeConnection,
    FakeForeignKeyViolation,
    FakeIntegrityError,
    FakeOperationalError,
    FakeUniqueViolation,
)

# Cada fila de la tabla "Restricciones y errores del dominio" de data-model.md.
CONSTRAINT_CASES = [
    (FakeUniqueViolation, "study_study_code_key", DuplicateStudyError),
    (FakeCheckViolation, "study_code_format", InvalidStudyIdError),
    (FakeCheckViolation, "patient_national_id_format", InvalidPatientDataError),
    (FakeUniqueViolation, "patient_national_id_key", InvalidPatientDataError),
    (FakeCheckViolation, "patient_code_format", InvalidPatientDataError),
    (FakeUniqueViolation, "patient_patient_code_key", InvalidPatientDataError),
    (FakeCheckViolation, "projection_angle_allowed", InvalidProjectionError),
    (FakeUniqueViolation, "projection_study_angle_unique", InvalidProjectionError),
    (FakeCheckViolation, "lesion_volume_positive", InvalidLesionError),
    (FakeCheckViolation, "lesion_confidence_range", InvalidLesionError),
]

LEAKY_MESSAGE = (
    'duplicate key value violates unique constraint "patient_national_id_key"\n'
    "DETAIL:  Key (national_id)=(12345678) already exists."
)


@pytest.mark.unit
@pytest.mark.parametrize(("error_class", "constraint", "expected"), CONSTRAINT_CASES)
def test_each_constraint_maps_to_its_domain_error(
    error_class: type, constraint: str, expected: type[RadVol3DError]
) -> None:
    translated = translate_database_error(error_class(constraint))

    assert type(translated) is expected


@pytest.mark.unit
def test_an_unknown_integrity_error_becomes_a_persistence_error() -> None:
    translated = translate_database_error(FakeForeignKeyViolation("study_patient_id_fkey"))

    assert type(translated) is PersistenceError


@pytest.mark.unit
def test_the_model_unique_constraint_is_not_mapped_to_a_specific_error() -> None:
    translated = translate_database_error(FakeUniqueViolation("model_name_version_unique"))

    assert type(translated) is PersistenceError


@pytest.mark.unit
def test_an_integrity_error_without_constraint_name_becomes_a_persistence_error() -> None:
    translated = translate_database_error(FakeIntegrityError(None))

    assert type(translated) is PersistenceError


@pytest.mark.unit
def test_operational_errors_mean_the_database_is_unavailable() -> None:
    translated = translate_database_error(FakeOperationalError("connection refused"))

    assert type(translated) is DatabaseUnavailableError


@pytest.mark.unit
def test_a_pool_timeout_means_the_database_is_unavailable() -> None:
    translated = translate_database_error(PoolTimeout("couldn't get a connection after 10 sec"))

    assert type(translated) is DatabaseUnavailableError


@pytest.mark.unit
@pytest.mark.parametrize(("error_class", "constraint", "expected"), CONSTRAINT_CASES)
def test_the_message_never_copies_the_psycopg_text(
    error_class: type, constraint: str, expected: type[RadVol3DError]
) -> None:
    translated = translate_database_error(error_class(constraint, LEAKY_MESSAGE))

    message = str(translated)
    assert message
    assert "12345678" not in message
    assert "DETAIL" not in message
    assert "national_id" not in message


@pytest.mark.unit
def test_the_translated_error_has_no_cause() -> None:
    original = FakeUniqueViolation("patient_national_id_key", LEAKY_MESSAGE)

    try:
        raise original
    except FakeUniqueViolation as error:
        translated = translate_database_error(error)

    assert translated.__cause__ is None
    assert translated.__context__ is None


@pytest.mark.unit
def test_only_the_sqlstate_and_the_constraint_name_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        translate_database_error(FakeUniqueViolation("patient_national_id_key", LEAKY_MESSAGE))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "patient_national_id_key" in logged
    assert "23505" in logged
    assert "12345678" not in logged
    assert "DETAIL" not in logged


@pytest.mark.unit
def test_execute_translated_returns_the_cursor_when_nothing_fails() -> None:
    connection = FakeConnection([[{"study_id": 7}]])

    cursor = execute_translated(connection, "select study_id from study where study_code = %s", ("it_a",))

    assert cursor.fetchone() == {"study_id": 7}
    assert connection.calls == [("select study_id from study where study_code = %s", ("it_a",))]


@pytest.mark.unit
def test_execute_translated_raises_the_domain_error_without_the_psycopg_cause() -> None:
    connection = FakeConnection([FakeUniqueViolation("patient_national_id_key", LEAKY_MESSAGE)])

    with pytest.raises(InvalidPatientDataError) as raised:
        execute_translated(connection, "insert into patient values (%s)", ("12345678",))

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert "12345678" not in str(raised.value)


@pytest.mark.unit
def test_execute_translated_lets_other_exceptions_through() -> None:
    connection = FakeConnection([ValueError("no es de la base")])

    with pytest.raises(ValueError, match="no es de la base"):
        execute_translated(connection, "select 1")
