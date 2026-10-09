"""Pruebas del repositorio de etapas de procesamiento (FR-038, FR-040)."""

from datetime import UTC, datetime

import pytest

from radvol3d.domain.entities import Model, ProcessingStage
from radvol3d.domain.enums import StageNumber, StageStatus
from radvol3d.domain.exceptions import (
    InvalidStudyIdError,
    PersistenceError,
    StudyNotFoundError,
)
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from tests.fixtures.fake_database import FakeConnection

STUDY_LOOKUP = [{"study_id": 7}]
STARTED = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
FINISHED = datetime(2026, 10, 9, 12, 5, tzinfo=UTC)


def stage_row(number: int, status: str = "waiting", **overrides) -> dict:
    row = {
        "stage_number": number,
        "stage_status": status,
        "started_at": None,
        "finished_at": None,
        "model_name": None,
        "version": None,
        "trained_on": None,
        "description": None,
    }
    row.update(overrides)
    return row


@pytest.mark.unit
def test_prepare_stages_creates_the_four_stages_in_waiting() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    ProcessingStageRepository(connection).prepare_stages("it_a")

    assert connection.params_of("insert into processing_stage") == [
        (7, 1, "preprocessing"),
        (7, 2, "reconstruction"),
        (7, 3, "segmentation"),
        (7, 4, "meshing"),
    ]


@pytest.mark.unit
def test_prepare_stages_never_duplicates_rows() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    ProcessingStageRepository(connection).prepare_stages("it_a")

    inserts = [sql for sql in connection.statements() if "insert into processing_stage" in sql]
    assert len(inserts) == 4
    assert all("on conflict (study_id, stage_number) do nothing" in sql for sql in inserts)
    # El estado inicial lo pone el valor por defecto de la columna: waiting.
    assert all("stage_status" not in sql for sql in inserts)


@pytest.mark.unit
def test_prepare_stages_raises_not_found_for_an_unknown_study() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(StudyNotFoundError):
        ProcessingStageRepository(connection).prepare_stages("it_a")

    assert not [s for s in connection.statements() if "insert into" in s]


@pytest.mark.unit
def test_prepare_stages_rejects_an_invalid_study_code() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        ProcessingStageRepository(connection).prepare_stages("a b")

    assert connection.calls == []


@pytest.mark.unit
def test_list_by_study_returns_the_stages_ordered_by_number() -> None:
    connection = FakeConnection(
        [
            [
                stage_row(1, "completed", started_at=STARTED, finished_at=FINISHED),
                stage_row(2, "completed", model_name="reconstruction_en1", version="1.0.0"),
                stage_row(3, "running", started_at=STARTED),
                stage_row(4),
            ]
        ]
    )

    stages = ProcessingStageRepository(connection).list_by_study("it_a")

    assert [stage.stage_number for stage in stages] == [
        StageNumber.PREPROCESSING,
        StageNumber.RECONSTRUCTION,
        StageNumber.SEGMENTATION,
        StageNumber.MESHING,
    ]
    assert stages[0] == ProcessingStage(
        StageNumber.PREPROCESSING, StageStatus.COMPLETED, STARTED, FINISHED
    )
    assert stages[1].model == Model("reconstruction_en1", "1.0.0")
    assert stages[2].status is StageStatus.RUNNING
    assert stages[3].status is StageStatus.WAITING
    assert stages[3].started_at is None
    assert "order by ps.stage_number" in connection.statements()[0]
    assert connection.params_of("from processing_stage ps") == [("it_a",)]


@pytest.mark.unit
def test_list_by_study_returns_an_empty_list_when_there_are_no_stages() -> None:
    assert ProcessingStageRepository(FakeConnection([[]])).list_by_study("it_a") == []


@pytest.mark.unit
def test_list_by_study_rejects_an_invalid_study_code() -> None:
    with pytest.raises(InvalidStudyIdError):
        ProcessingStageRepository(FakeConnection()).list_by_study("..")


# --- Historia 2: avance de cada etapa (FR-039, research.md R9) ---

STARTED_ONLY = [{"started_at": STARTED, "finished_at": None}]
STARTED_AND_FINISHED = [{"started_at": STARTED, "finished_at": FINISHED}]


def assignments(statement: str) -> str:
    """La parte del update que asigna columnas, sin el returning."""
    return statement.split(" returning ")[0]


@pytest.mark.unit
def test_running_records_the_start_time_and_nothing_else() -> None:
    connection = FakeConnection([STARTED_ONLY])

    ProcessingStageRepository(connection).set_status(
        "it_a", StageNumber.RECONSTRUCTION, StageStatus.RUNNING
    )

    statement = assignments(connection.statements()[0])
    assert "stage_status = %s" in statement
    assert "started_at = now()" in statement
    assert "finished_at" not in statement
    assert connection.params_of("update processing_stage") == [("running", "it_a", 2)]


@pytest.mark.unit
@pytest.mark.parametrize("status", [StageStatus.COMPLETED, StageStatus.SKIPPED, StageStatus.FAILED])
def test_final_states_record_the_finish_time_and_never_the_start(status: StageStatus) -> None:
    connection = FakeConnection([STARTED_AND_FINISHED])

    ProcessingStageRepository(connection).set_status("it_a", StageNumber.SEGMENTATION, status)

    statement = assignments(connection.statements()[0])
    assert "finished_at = now()" in statement
    assert "started_at" not in statement
    assert connection.params_of("update processing_stage") == [(status.value, "it_a", 3)]


@pytest.mark.unit
def test_waiting_records_no_time_at_all() -> None:
    connection = FakeConnection([[{"started_at": None, "finished_at": None}]])

    ProcessingStageRepository(connection).set_status(
        "it_a", StageNumber.MESHING, StageStatus.WAITING
    )

    statement = assignments(connection.statements()[0])
    assert "started_at" not in statement
    assert "finished_at" not in statement


@pytest.mark.unit
def test_a_stage_skipped_without_starting_keeps_the_start_time_empty() -> None:
    connection = FakeConnection([[{"started_at": None, "finished_at": FINISHED}]])

    ProcessingStageRepository(connection).set_status(
        "it_a", StageNumber.MESHING, StageStatus.SKIPPED
    )

    assert "started_at" not in assignments(connection.statements()[0])


@pytest.mark.unit
def test_the_model_that_ran_the_stage_is_recorded_when_given() -> None:
    connection = FakeConnection([STARTED_AND_FINISHED])
    model = Model("segmentation_lung", "1.0.0")

    ProcessingStageRepository(connection).set_status(
        "it_a", StageNumber.SEGMENTATION, StageStatus.COMPLETED, model=model
    )

    assert "model_id = m.model_id" in connection.statements()[0]
    assert connection.params_of("update processing_stage") == [
        ("completed", "it_a", 3, "segmentation_lung", "1.0.0")
    ]


@pytest.mark.unit
def test_without_a_model_the_statement_never_mentions_one() -> None:
    connection = FakeConnection([STARTED_AND_FINISHED])

    ProcessingStageRepository(connection).set_status(
        "it_a", StageNumber.PREPROCESSING, StageStatus.COMPLETED
    )

    assert "model" not in connection.statements()[0]


@pytest.mark.unit
def test_number_and_status_are_accepted_as_plain_values() -> None:
    connection = FakeConnection([STARTED_AND_FINISHED])

    ProcessingStageRepository(connection).set_status("it_a", 4, "completed")

    assert connection.params_of("update processing_stage") == [("completed", "it_a", 4)]


@pytest.mark.unit
def test_set_status_raises_not_found_for_an_unknown_study() -> None:
    connection = FakeConnection([[], []])

    with pytest.raises(StudyNotFoundError):
        ProcessingStageRepository(connection).set_status(
            "it_no_existe", StageNumber.PREPROCESSING, StageStatus.RUNNING
        )


@pytest.mark.unit
def test_set_status_on_a_study_without_that_stage_or_model_is_a_persistence_error() -> None:
    connection = FakeConnection([[], [{"study_id": 3}]])

    with pytest.raises(PersistenceError) as raised:
        ProcessingStageRepository(connection).set_status(
            "it_a",
            StageNumber.SEGMENTATION,
            StageStatus.COMPLETED,
            model=Model("sin_registrar", "0.0.1"),
        )

    assert type(raised.value) is PersistenceError


@pytest.mark.unit
def test_a_finish_time_before_the_start_time_is_rejected() -> None:
    earlier = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)
    connection = FakeConnection([[{"started_at": STARTED, "finished_at": earlier}]])

    with pytest.raises(PersistenceError):
        ProcessingStageRepository(connection).set_status(
            "it_a", StageNumber.RECONSTRUCTION, StageStatus.COMPLETED
        )


@pytest.mark.unit
def test_set_status_rejects_invalid_input_before_touching_the_database() -> None:
    connection = FakeConnection()
    repository = ProcessingStageRepository(connection)

    with pytest.raises(InvalidStudyIdError):
        repository.set_status("a b", StageNumber.PREPROCESSING, StageStatus.RUNNING)
    with pytest.raises(PersistenceError):
        repository.set_status("it_a", 5, StageStatus.RUNNING)
    with pytest.raises(PersistenceError):
        repository.set_status("it_a", StageNumber.PREPROCESSING, "terminado")

    assert connection.calls == []
