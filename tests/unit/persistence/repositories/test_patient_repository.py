"""Pruebas del repositorio de pacientes (FR-022 a FR-025, SC-007).

Usan una conexion guionada: verifican los parametros, la conversion de filas en
entidades y la traduccion de errores. El SQL real lo verifican las pruebas de
integracion.
"""

import pytest

from radvol3d.domain.entities import Patient, PatientDetails
from radvol3d.domain.exceptions import (
    InvalidPatientDataError,
    PatientCodeExhaustedError,
    PersistenceError,
)
from radvol3d.persistence.repositories.patient_repository import (
    REFERENCE_PATIENT_CODE,
    PatientRepository,
)
from tests.fixtures.fake_database import FakeConnection, FakeUniqueViolation

FIRST_NAME = "Rosa"
LAST_NAME = "Quispe"
NATIONAL_ID = "12345678"


def patient_row(
    code: str, first: str | None = None, last: str | None = None, dni: str | None = None
) -> dict[str, str | None]:
    return {"patient_code": code, "first_name": first, "last_name": last, "national_id": dni}


def statement_starting(connection: FakeConnection, fragment: str) -> list[str]:
    return [sql for sql in connection.statements() if fragment in sql]


@pytest.mark.unit
def test_a_known_national_id_reuses_the_patient_without_changing_it() -> None:
    existing = patient_row("PAC000004", "Otro", "Nombre", NATIONAL_ID)
    connection = FakeConnection([[], [existing]])  # candado, busqueda por DNI

    patient = PatientRepository(connection).find_or_create(
        PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID)
    )

    assert patient == Patient("PAC000004", "Otro", "Nombre", NATIONAL_ID)
    assert not statement_starting(connection, "insert into patient")


@pytest.mark.unit
def test_a_new_national_id_creates_the_next_consecutive_code() -> None:
    connection = FakeConnection(
        [
            [],  # candado
            [],  # busqueda por DNI: no existe
            [{"last_code": "PAC000007"}],  # maximo actual
            [patient_row("PAC000008", FIRST_NAME, LAST_NAME, NATIONAL_ID)],  # insert returning
        ]
    )

    patient = PatientRepository(connection).find_or_create(
        PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID)
    )

    assert patient == Patient("PAC000008", FIRST_NAME, LAST_NAME, NATIONAL_ID)
    assert connection.params_of("insert into patient") == [
        ("PAC000008", FIRST_NAME, LAST_NAME, NATIONAL_ID)
    ]


@pytest.mark.unit
def test_the_first_code_after_the_reference_patient_is_pac000001() -> None:
    connection = FakeConnection(
        [[], [], [{"last_code": "PAC000000"}], [patient_row("PAC000001", dni=NATIONAL_ID)]]
    )

    PatientRepository(connection).find_or_create(PatientDetails(national_id=NATIONAL_ID))

    assert connection.params_of("insert into patient")[0][0] == "PAC000001"


@pytest.mark.unit
def test_the_lock_is_requested_before_any_read() -> None:
    connection = FakeConnection(
        [[], [], [{"last_code": "PAC000000"}], [patient_row("PAC000001", dni=NATIONAL_ID)]]
    )

    PatientRepository(connection).find_or_create(PatientDetails(national_id=NATIONAL_ID))

    assert "pg_advisory_xact_lock" in connection.statements()[0]


@pytest.mark.unit
def test_names_without_national_id_create_a_new_patient_without_searching_by_name() -> None:
    connection = FakeConnection(
        [[], [{"last_code": "PAC000002"}], [patient_row("PAC000003", FIRST_NAME, LAST_NAME)]]
    )

    patient = PatientRepository(connection).find_or_create(
        PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME)
    )

    assert patient.patient_code == "PAC000003"
    assert patient.national_id is None
    assert not statement_starting(connection, "where national_id")
    assert not statement_starting(connection, "where first_name")


@pytest.mark.unit
@pytest.mark.parametrize("details", [None, PatientDetails(), PatientDetails(first_name="   ")])
def test_without_personal_data_the_reference_patient_is_returned(
    details: PatientDetails | None,
) -> None:
    connection = FakeConnection([[patient_row(REFERENCE_PATIENT_CODE)]])

    patient = PatientRepository(connection).find_or_create(details)

    assert patient == Patient(REFERENCE_PATIENT_CODE)
    assert connection.params_of("from patient") == [(REFERENCE_PATIENT_CODE,)]
    assert not statement_starting(connection, "insert into patient")
    assert not statement_starting(connection, "pg_advisory_xact_lock")


@pytest.mark.unit
def test_blank_names_are_stored_as_absent() -> None:
    connection = FakeConnection(
        [[], [], [{"last_code": "PAC000001"}], [patient_row("PAC000002", dni=NATIONAL_ID)]]
    )

    PatientRepository(connection).find_or_create(
        PatientDetails(first_name="   ", last_name="", national_id=f" {NATIONAL_ID} ")
    )

    assert connection.params_of("insert into patient") == [("PAC000002", None, None, NATIONAL_ID)]


@pytest.mark.unit
@pytest.mark.parametrize(
    "national_id", ["1234567", "123456789", "1234567a", "abcdefgh", "1234 678", "-1234567"]
)
def test_a_national_id_that_is_not_eight_digits_is_rejected_before_touching_the_database(
    national_id: str,
) -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidPatientDataError) as raised:
        PatientRepository(connection).find_or_create(
            PatientDetails(first_name=FIRST_NAME, national_id=national_id)
        )

    assert connection.calls == []
    assert national_id not in str(raised.value)
    assert FIRST_NAME not in str(raised.value)


@pytest.mark.unit
def test_running_out_of_codes_is_an_error_and_nothing_is_inserted() -> None:
    connection = FakeConnection([[], [], [{"last_code": "PAC999999"}]])

    with pytest.raises(PatientCodeExhaustedError) as raised:
        PatientRepository(connection).find_or_create(
            PatientDetails(first_name=FIRST_NAME, national_id=NATIONAL_ID)
        )

    assert not statement_starting(connection, "insert into patient")
    assert FIRST_NAME not in str(raised.value)
    assert NATIONAL_ID not in str(raised.value)


@pytest.mark.unit
def test_a_missing_reference_patient_asks_to_apply_the_schema() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(PersistenceError) as raised:
        PatientRepository(connection).find_or_create(None)

    assert "001_create_tables.sql" in str(raised.value)


@pytest.mark.unit
def test_a_unique_violation_on_insert_is_translated_without_leaking_the_value() -> None:
    leaky = "DETAIL:  Key (national_id)=(12345678) already exists."
    connection = FakeConnection(
        [[], [], [{"last_code": "PAC000001"}], FakeUniqueViolation("patient_national_id_key", leaky)]
    )

    with pytest.raises(InvalidPatientDataError) as raised:
        PatientRepository(connection).find_or_create(PatientDetails(national_id=NATIONAL_ID))

    assert NATIONAL_ID not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.unit
def test_get_by_code_returns_the_patient_or_none() -> None:
    connection = FakeConnection([[patient_row("PAC000005", FIRST_NAME)], []])
    repository = PatientRepository(connection)

    found = repository.get_by_code("PAC000005")
    missing = repository.get_by_code("PAC000099")

    assert found == Patient("PAC000005", FIRST_NAME)
    assert missing is None
    assert connection.params_of("from patient") == [("PAC000005",), ("PAC000099",)]
