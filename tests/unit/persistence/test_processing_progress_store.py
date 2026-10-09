"""Pruebas del almacen de avance del procesamiento (research.md R9).

Cada metodo es una unidad de trabajo completa: abre una sola transaccion y combina
los repositorios que ya existen. Los servicios no manejan conexiones.
"""

from datetime import UTC, datetime

import pytest

from radvol3d.domain.entities import Model
from radvol3d.domain.enums import StageNumber
from radvol3d.domain.exceptions import InvalidStudyIdError, PersistenceError, StudyNotFoundError
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from tests.fixtures.fake_database import FakeCursor, FakeDatabase, index_of

CODE = "it_a"
STARTED = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
FINISHED = datetime(2026, 10, 9, 12, 5, tzinfo=UTC)


def model_row(name: str = "segmentation_lung", version: str = "1.0.0") -> dict:
    return {"model_name": name, "version": version, "trained_on": None, "description": None}


@pytest.fixture
def database() -> FakeDatabase:
    database = FakeDatabase()
    connection = database.connection
    connection.when("insert into model", [model_row()])
    connection.when(
        "update processing_stage", [{"started_at": STARTED, "finished_at": FINISHED}]
    )
    connection.when("select study_id from study where study_code", [{"study_id": 7}])
    return database


@pytest.fixture
def store(database: FakeDatabase) -> ProcessingProgressStore:
    return ProcessingProgressStore(database)


@pytest.mark.unit
def test_start_processing_puts_the_study_in_processing(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.start_processing(CODE)

    assert database.connection.params_of("update study set status") == [("processing", CODE)]
    assert database.committed == 1


@pytest.mark.unit
def test_start_processing_of_an_unknown_study_raises_not_found(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    database.connection.rules.insert(0, ("update study", FakeCursor([], rowcount=0), False))

    with pytest.raises(StudyNotFoundError):
        store.start_processing("it_no_existe")

    assert database.rolled_back == 1


@pytest.mark.unit
def test_start_stage_puts_the_stage_in_running(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.start_stage(CODE, StageNumber.RECONSTRUCTION)

    assert database.connection.params_of("update processing_stage") == [("running", CODE, 2)]
    statement = database.connection.statements()[0]
    assert "started_at = now()" in statement
    assert database.committed == 1


@pytest.mark.unit
def test_complete_stage_with_a_model_registers_it_before_linking_it(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.complete_stage(CODE, StageNumber.SEGMENTATION, "segmentation_lung", "1.0.0")

    connection = database.connection
    assert connection.params_of("insert into model") == [
        ("segmentation_lung", "1.0.0", None, None)
    ]
    assert connection.params_of("update processing_stage") == [
        ("completed", CODE, 3, "segmentation_lung", "1.0.0")
    ]
    events = database.events
    assert index_of(events, "insert into model") < index_of(events, "update processing_stage")
    assert database.committed == 1


@pytest.mark.unit
def test_complete_stage_without_a_model_does_not_touch_the_model_table(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.complete_stage(CODE, StageNumber.PREPROCESSING)

    connection = database.connection
    assert connection.params_of("insert into model") == []
    assert connection.params_of("update processing_stage") == [("completed", CODE, 1)]
    assert database.committed == 1


@pytest.mark.unit
def test_complete_stage_needs_both_the_model_name_and_its_version(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    with pytest.raises(PersistenceError):
        store.complete_stage(CODE, StageNumber.RECONSTRUCTION, "reconstruction_en1", None)

    assert database.connection.calls == []


@pytest.mark.unit
def test_complete_stage_of_an_unknown_study_raises_not_found(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    connection = database.connection
    connection.rules.clear()
    connection.when("update processing_stage", [])
    connection.when("select study_id from study where study_code", [])

    with pytest.raises(StudyNotFoundError):
        store.complete_stage("it_no_existe", StageNumber.MESHING)

    assert database.rolled_back == 1


@pytest.mark.unit
def test_complete_study_marks_it_completed_with_model_grid_and_time(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.complete_study(CODE, "segmentation_lung", "1.0.0", 128, 12.5)

    connection = database.connection
    assert connection.params_of("insert into model") == [
        ("segmentation_lung", "1.0.0", None, None)
    ]
    assert connection.params_of("update study set status") == [
        ("completed", 128, 12.5, CODE, "segmentation_lung", "1.0.0")
    ]
    assert database.committed == 1


@pytest.mark.unit
def test_complete_study_of_an_unknown_study_raises_not_found(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    connection = database.connection
    connection.rules.insert(0, ("update study", FakeCursor([], rowcount=0), False))
    connection.rules.insert(0, ("select study_id from study where study_code", [], False))

    with pytest.raises(StudyNotFoundError):
        store.complete_study("it_no_existe", "segmentation_lung", "1.0.0", 128, 1.0)


@pytest.mark.unit
def test_register_model_returns_the_model_without_a_training_date(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    model = store.register_model("segmentation_lung", "1.0.0")

    assert model == Model("segmentation_lung", "1.0.0")
    assert model.trained_on is None
    assert database.committed == 1


@pytest.mark.unit
def test_register_model_passes_the_description_it_receives(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.register_model("segmentation_lung", "1.0.0", description="U-Net 3D residual EN-2")

    assert database.connection.params_of("insert into model") == [
        ("segmentation_lung", "1.0.0", None, "U-Net 3D residual EN-2")
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.start_processing("../x"),
        lambda s: s.start_stage("../x", StageNumber.PREPROCESSING),
        lambda s: s.complete_stage("../x", StageNumber.PREPROCESSING),
        lambda s: s.complete_study("../x", "m", "1.0.0", 128, 1.0),
    ],
)
def test_an_invalid_code_is_rejected_before_opening_a_transaction(
    database: FakeDatabase, store: ProcessingProgressStore, call
) -> None:
    with pytest.raises(InvalidStudyIdError):
        call(store)

    assert database.events == []


# ---------------------------------------------------------------------------
# fail_from_stage (historia 2, escenario 4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_failing_stage_three_skips_stage_four_and_fails_the_study(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.fail_from_stage(CODE, StageNumber.SEGMENTATION)

    connection = database.connection
    assert connection.params_of("update processing_stage") == [
        ("failed", CODE, 3),
        ("skipped", CODE, 4),
    ]
    assert connection.params_of("update study set status") == [("failed", CODE)]
    assert database.committed == 1


@pytest.mark.unit
def test_failing_stage_one_skips_the_other_three(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.fail_from_stage(CODE, StageNumber.PREPROCESSING)

    assert database.connection.params_of("update processing_stage") == [
        ("failed", CODE, 1),
        ("skipped", CODE, 2),
        ("skipped", CODE, 3),
        ("skipped", CODE, 4),
    ]
    assert database.committed == 1


@pytest.mark.unit
def test_failing_the_last_stage_skips_nothing(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    store.fail_from_stage(CODE, StageNumber.MESHING)

    assert database.connection.params_of("update processing_stage") == [("failed", CODE, 4)]


@pytest.mark.unit
def test_fail_from_stage_of_an_unknown_study_raises_not_found(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    connection = database.connection
    connection.rules.clear()
    connection.when("update processing_stage", [])
    connection.when("select study_id from study where study_code", [])

    with pytest.raises(StudyNotFoundError):
        store.fail_from_stage("it_no_existe", StageNumber.SEGMENTATION)

    assert database.rolled_back == 1


# ---------------------------------------------------------------------------
# fail_interrupted_studies (funcionalidad 004, research.md R5)
# ---------------------------------------------------------------------------


def stage_rows(*statuses: str) -> list[dict]:
    return [
        {
            "stage_number": number,
            "stage_status": status,
            "started_at": None,
            "finished_at": None,
            "model_name": None,
            "version": None,
            "trained_on": None,
            "description": None,
        }
        for number, status in enumerate(statuses, 1)
    ]


def interrupted(database: FakeDatabase, codes: list[str], stages: list[dict]) -> None:
    connection = database.connection
    connection.rules.insert(0, ("where status = %s", [{"study_code": c} for c in codes], False))
    connection.rules.insert(0, ("for update", [{"status": "processing"}], False))
    connection.rules.insert(0, ("from processing_stage ps join study", stages, False))


@pytest.mark.unit
def test_an_interrupted_study_fails_from_its_running_stage(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, [CODE], stage_rows("completed", "running", "waiting", "waiting"))

    recovered = store.fail_interrupted_studies()

    connection = database.connection
    assert recovered == [CODE]
    assert connection.params_of("where status = %s") == [("processing",)]
    assert connection.params_of("update processing_stage") == [
        ("failed", CODE, 2),
        ("skipped", CODE, 3),
        ("skipped", CODE, 4),
    ]
    assert connection.params_of("update study set status") == [("failed", CODE)]


@pytest.mark.unit
def test_without_a_running_stage_the_first_waiting_one_fails(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, [CODE], stage_rows("completed", "completed", "waiting", "waiting"))

    store.fail_interrupted_studies()

    assert database.connection.params_of("update processing_stage") == [
        ("failed", CODE, 3),
        ("skipped", CODE, 4),
    ]


@pytest.mark.unit
def test_an_interrupted_study_with_every_stage_done_only_fails_the_study(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, [CODE], stage_rows(*["completed"] * 4))

    store.fail_interrupted_studies()

    assert database.connection.params_of("update processing_stage") == []
    assert database.connection.params_of("update study set status") == [("failed", CODE)]


@pytest.mark.unit
def test_each_interrupted_study_is_its_own_unit_of_work(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, ["it_a", "it_b"], stage_rows("running", "waiting", "waiting", "waiting"))

    recovered = store.fail_interrupted_studies()

    assert recovered == ["it_a", "it_b"]
    # Una transaccion para listar y una por estudio.
    assert database.committed == 3


@pytest.mark.unit
def test_with_no_study_in_processing_nothing_changes(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, [], [])

    assert store.fail_interrupted_studies() == []
    assert database.connection.params_of("update study") == []
    assert database.connection.params_of("update processing_stage") == []


@pytest.mark.unit
def test_a_study_that_left_processing_meanwhile_is_not_touched(
    database: FakeDatabase, store: ProcessingProgressStore
) -> None:
    interrupted(database, [CODE], stage_rows(*["completed"] * 4))
    database.connection.rules.insert(0, ("for update", [{"status": "completed"}], False))

    assert store.fail_interrupted_studies() == []
    assert database.connection.params_of("update study") == []
    assert database.connection.params_of("update processing_stage") == []
