"""Pruebas del repositorio de estudios (FR-030, FR-031, FR-032, FR-034)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from radvol3d.domain.entities import Model, Patient
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidStudyIdError,
    PersistenceError,
    StudyNotFoundError,
    UnknownOrganError,
)
from radvol3d.persistence.repositories.study_repository import StudyRepository, find_study_id
from tests.fixtures.fake_database import (
    FakeCheckViolation,
    FakeConnection,
    FakeCursor,
    FakeUniqueViolation,
)

CREATED_AT = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def study_row(**overrides) -> dict:
    row = {
        "study_code": "it_a",
        "status": "pending",
        "grid_size": None,
        "total_time_sec": None,
        "created_at": CREATED_AT,
        "organ_name": "lung",
        "patient_code": "PAC000001",
        "first_name": None,
        "last_name": None,
        "national_id": None,
        "model_name": None,
        "version": None,
        "trained_on": None,
        "description": None,
    }
    row.update(overrides)
    return row


@pytest.mark.unit
def test_create_leaves_the_study_pending_and_returns_it_with_its_patient() -> None:
    connection = FakeConnection([[{"study_id": 5}], [study_row()]])

    study = StudyRepository(connection).create("it_a", OrganName.LUNG, "PAC000001")

    assert study.study_code == "it_a"
    assert study.status is StudyStatus.PENDING
    assert study.organ is OrganName.LUNG
    assert study.patient == Patient("PAC000001")
    assert connection.params_of("insert into study") == [("it_a", "PAC000001", "lung")]
    statements = connection.statements()
    assert "insert into study" in statements[0]
    assert "from study s" in statements[1]


@pytest.mark.unit
def test_create_accepts_the_organ_as_text() -> None:
    connection = FakeConnection([[{"study_id": 5}], [study_row(organ_name="liver")]])

    study = StudyRepository(connection).create("it_a", "liver", "PAC000001")

    assert study.organ is OrganName.LIVER


@pytest.mark.unit
def test_create_rejects_a_duplicate_code() -> None:
    leaky = "DETAIL:  Key (study_code)=(it_a) already exists."
    connection = FakeConnection([FakeUniqueViolation("study_study_code_key", leaky)])

    with pytest.raises(DuplicateStudyError) as raised:
        StudyRepository(connection).create("it_a", OrganName.LUNG, "PAC000001")

    assert "DETAIL" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.unit
def test_create_translates_the_code_format_constraint() -> None:
    connection = FakeConnection([FakeCheckViolation("study_code_format")])

    with pytest.raises(InvalidStudyIdError):
        StudyRepository(connection).create("it_a", OrganName.LUNG, "PAC000001")


@pytest.mark.unit
@pytest.mark.parametrize("code", ["", "a b", "a/b", "..", "x" * 65])
def test_create_rejects_an_invalid_code_before_touching_the_database(code: str) -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        StudyRepository(connection).create(code, OrganName.LUNG, "PAC000001")

    assert connection.calls == []


@pytest.mark.unit
def test_create_rejects_an_organ_outside_the_scope_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(UnknownOrganError):
        StudyRepository(connection).create("it_a", "heart", "PAC000001")

    assert connection.calls == []


@pytest.mark.unit
def test_create_fails_when_the_insert_returns_no_row() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(PersistenceError):
        StudyRepository(connection).create("it_a", OrganName.LUNG, "PAC999999")


@pytest.mark.unit
def test_get_by_code_builds_the_study_with_organ_patient_and_model() -> None:
    row = study_row(
        status="completed",
        grid_size=128,
        total_time_sec=Decimal("12.500"),
        first_name="Rosa",
        national_id="12345678",
        model_name="reconstruction_en1",
        version="1.0.0",
    )
    connection = FakeConnection([[row]])

    study = StudyRepository(connection).get_by_code("it_a")

    assert study.status is StudyStatus.COMPLETED
    assert study.grid_size == 128
    assert study.total_time_sec == 12.5
    assert isinstance(study.total_time_sec, float)
    assert study.created_at == CREATED_AT
    assert study.patient == Patient("PAC000001", "Rosa", None, "12345678")
    assert study.model == Model("reconstruction_en1", "1.0.0")
    assert (study.projections, study.stages, study.lesions) == ([], [], [])
    assert connection.params_of("where s.study_code = %s") == [("it_a",)]


@pytest.mark.unit
def test_get_by_code_leaves_the_model_empty_when_none_was_used() -> None:
    connection = FakeConnection([[study_row()]])

    study = StudyRepository(connection).get_by_code("it_a")

    assert study.model is None
    assert study.grid_size is None
    assert study.total_time_sec is None


@pytest.mark.unit
def test_get_by_code_raises_not_found_for_an_unknown_code() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(StudyNotFoundError):
        StudyRepository(connection).get_by_code("it_no_existe")


@pytest.mark.unit
def test_get_by_code_rejects_an_invalid_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        StudyRepository(connection).get_by_code("../otro")

    assert connection.calls == []


@pytest.mark.unit
def test_list_recent_orders_from_newest_to_oldest_without_nested_data() -> None:
    connection = FakeConnection(
        [[study_row(study_code="it_nuevo"), study_row(study_code="it_viejo", organ_name="liver")]]
    )

    studies = StudyRepository(connection).list_recent()

    assert [study.study_code for study in studies] == ["it_nuevo", "it_viejo"]
    assert studies[1].organ is OrganName.LIVER
    assert all((s.projections, s.stages, s.lesions) == ([], [], []) for s in studies)
    assert "order by s.created_at desc" in connection.statements()[0]


@pytest.mark.unit
def test_list_recent_returns_an_empty_list_when_there_are_no_studies() -> None:
    assert StudyRepository(FakeConnection([[]])).list_recent() == []


@pytest.mark.unit
def test_find_study_id_returns_the_internal_id() -> None:
    connection = FakeConnection([[{"study_id": 42}]])

    assert find_study_id(connection, "it_a") == 42
    assert connection.params_of("from study where study_code") == [("it_a",)]


@pytest.mark.unit
def test_find_study_id_raises_not_found_when_the_study_does_not_exist() -> None:
    with pytest.raises(StudyNotFoundError):
        find_study_id(FakeConnection([[]]), "it_a")


@pytest.mark.unit
def test_find_study_id_rejects_an_invalid_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        find_study_id(connection, "a b")

    assert connection.calls == []


# --- Historia 2: estado del estudio y cierre del procesamiento (FR-033) ---


@pytest.mark.unit
@pytest.mark.parametrize("status", list(StudyStatus))
def test_update_status_accepts_the_four_states(status: StudyStatus) -> None:
    connection = FakeConnection([FakeCursor([], rowcount=1)])

    StudyRepository(connection).update_status("it_a", status)

    assert connection.params_of("update study") == [(status.value, "it_a")]


@pytest.mark.unit
def test_update_status_accepts_the_state_as_text() -> None:
    connection = FakeConnection([FakeCursor([], rowcount=1)])

    StudyRepository(connection).update_status("it_a", "processing")

    assert connection.params_of("update study") == [("processing", "it_a")]


@pytest.mark.unit
def test_update_status_rejects_an_unknown_state_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(PersistenceError):
        StudyRepository(connection).update_status("it_a", "terminado")

    assert connection.calls == []


@pytest.mark.unit
def test_update_status_raises_not_found_when_no_row_changes() -> None:
    connection = FakeConnection([FakeCursor([], rowcount=0)])

    with pytest.raises(StudyNotFoundError):
        StudyRepository(connection).update_status("it_no_existe", StudyStatus.FAILED)


@pytest.mark.unit
def test_update_status_rejects_an_invalid_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        StudyRepository(connection).update_status("a b", StudyStatus.FAILED)

    assert connection.calls == []


@pytest.mark.unit
def test_mark_completed_records_model_grid_size_and_time_together() -> None:
    connection = FakeConnection([FakeCursor([], rowcount=1)])
    model = Model("reconstruction_en1", "1.0.0")

    StudyRepository(connection).mark_completed("it_a", model, 128, 12.5)

    assert len(connection.calls) == 1
    statement = connection.statements()[0]
    assert "update study" in statement
    assert "model_id = m.model_id" in statement
    assert "grid_size = %s" in statement
    assert "total_time_sec = %s" in statement
    assert connection.params_of("update study") == [
        ("completed", 128, 12.5, "it_a", "reconstruction_en1", "1.0.0")
    ]


@pytest.mark.unit
def test_mark_completed_raises_not_found_for_an_unknown_study() -> None:
    connection = FakeConnection([FakeCursor([], rowcount=0), []])

    with pytest.raises(StudyNotFoundError):
        StudyRepository(connection).mark_completed(
            "it_no_existe", Model("reconstruction_en1", "1.0.0"), 128, 1.0
        )


@pytest.mark.unit
def test_mark_completed_with_an_unregistered_model_is_an_error_and_never_leaves_it_empty() -> None:
    connection = FakeConnection([FakeCursor([], rowcount=0), [{"study_id": 3}]])

    with pytest.raises(PersistenceError) as raised:
        StudyRepository(connection).mark_completed("it_a", Model("sin_registrar", "0.0.1"), 128, 1.0)

    assert type(raised.value) is PersistenceError


@pytest.mark.unit
def test_a_negative_total_time_ends_as_a_persistence_error() -> None:
    connection = FakeConnection([FakeCheckViolation("study_total_time_positive")])

    with pytest.raises(PersistenceError) as raised:
        StudyRepository(connection).mark_completed(
            "it_a", Model("reconstruction_en1", "1.0.0"), 128, -1.0
        )

    assert raised.value.__cause__ is None


@pytest.mark.unit
def test_mark_completed_rejects_an_invalid_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        StudyRepository(connection).mark_completed(
            "../x", Model("reconstruction_en1", "1.0.0"), 128, 1.0
        )

    assert connection.calls == []
