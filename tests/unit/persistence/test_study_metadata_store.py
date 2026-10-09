"""Pruebas del almacen de metadatos de un estudio (FR-044, FR-045).

La base y el bucket comparten una lista de eventos para poder comprobar el orden
entre ellos: el estudio se inserta ANTES de subir cualquier archivo.
"""

from datetime import UTC, datetime

import numpy as np
import pytest
from storage3.utils import StorageException

from radvol3d.domain.entities import Lesion, Patient, PatientDetails, Projection
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidProjectionError,
    InvalidStudyIdError,
    StorageError,
    StudyNotFoundError,
    UnknownOrganError,
)
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from tests.fixtures.fake_database import (
    FakeCheckViolation,
    FakeDatabase,
    FakeUniqueViolation,
    index_of,
)
from tests.fixtures.fake_object_storage import InMemoryBucket

CODE = "it_a"
CREATED_AT = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
ANGLES = (0, 45, 90, 135)

STUDY_ROW = {
    "study_code": CODE,
    "status": "pending",
    "grid_size": None,
    "total_time_sec": None,
    "created_at": CREATED_AT,
    "organ_name": "lung",
    "patient_code": "PAC000000",
    "first_name": None,
    "last_name": None,
    "national_id": None,
    "model_name": None,
    "version": None,
    "trained_on": None,
    "description": None,
}
PROJECTION_ROWS = [
    {"angle_degrees": a, "file_path": f"{CODE}/projections/angle_{a:03d}.npy", "original_name": None}
    for a in ANGLES
]
STAGE_ROWS = [
    {
        "stage_number": n,
        "stage_status": "waiting",
        "started_at": None,
        "finished_at": None,
        "model_name": None,
        "version": None,
        "trained_on": None,
        "description": None,
    }
    for n in (1, 2, 3, 4)
]
REFERENCE_PATIENT = {
    "patient_code": "PAC000000",
    "first_name": None,
    "last_name": None,
    "national_id": None,
}


class World:
    """Base y bucket falsos conectados entre si por una lista de eventos."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.database = FakeDatabase(events=self.events)
        self.bucket = InMemoryBucket(events=self.events)
        self.store = StudyMetadataStore(self.database, ObjectStorage(self.bucket))
        self.connection = self.database.connection
        self.connection.when("from patient where patient_code", [REFERENCE_PATIENT])
        self.connection.when("insert into study", [{"study_id": 1}])
        self.connection.when("select study_id from study where study_code", [{"study_id": 1}])
        self.connection.when("from study s join organ", [STUDY_ROW])
        self.connection.when("from projection p", PROJECTION_ROWS)
        self.connection.when("from processing_stage ps", STAGE_ROWS)

    def uploaded(self) -> list[str]:
        return [e.removeprefix("upload:") for e in self.events if e.startswith("upload:")]


def four_uploads() -> list[ProjectionUpload]:
    return [
        ProjectionUpload(angle, np.full((4, 4), angle, dtype=np.float32), f"angulo_{angle}.npy")
        for angle in ANGLES
    ]


@pytest.fixture
def world() -> World:
    return World()


@pytest.mark.unit
def test_register_study_inserts_the_study_before_uploading_any_file(world: World) -> None:
    world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert index_of(world.events, "insert into study") != -1
    assert index_of(world.events, "insert into study") < index_of(world.events, "upload:")


@pytest.mark.unit
def test_register_study_does_everything_in_the_agreed_order_and_commits_last(
    world: World,
) -> None:
    world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    events = world.events
    last_upload = max(i for i, e in enumerate(events) if e.startswith("upload:"))
    assert index_of(events, "from patient where patient_code") < index_of(events, "insert into study")
    assert last_upload < index_of(events, "insert into projection")
    assert index_of(events, "insert into projection") < index_of(events, "insert into processing_stage")
    assert events[-1] == "db:commit"
    assert "db:rollback" not in events
    assert world.database.committed == 1


@pytest.mark.unit
def test_register_study_uploads_the_four_projections_to_their_paths(world: World) -> None:
    uploads = four_uploads()

    world.store.register_study(CODE, OrganName.LUNG, uploads)

    assert world.uploaded() == [
        f"{CODE}/projections/angle_000.npy",
        f"{CODE}/projections/angle_045.npy",
        f"{CODE}/projections/angle_090.npy",
        f"{CODE}/projections/angle_135.npy",
    ]
    stored = ObjectStorage(world.bucket).download_array(f"{CODE}/projections/angle_090.npy")
    assert np.array_equal(stored, uploads[2].array)
    assert set(world.bucket.content_types.values()) == {"application/octet-stream"}


@pytest.mark.unit
def test_register_study_records_the_projection_rows_and_the_four_stages(world: World) -> None:
    world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert world.connection.params_of("insert into projection") == [
        (1, angle, f"{CODE}/projections/angle_{angle:03d}.npy", f"angulo_{angle}.npy")
        for angle in ANGLES
    ]
    assert [p[1] for p in world.connection.params_of("insert into processing_stage")] == [1, 2, 3, 4]


@pytest.mark.unit
def test_register_study_returns_the_complete_study(world: World) -> None:
    study = world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert study.study_code == CODE
    assert study.status is StudyStatus.PENDING
    assert study.patient == Patient("PAC000000")
    assert study.projections == [
        Projection(a, f"{CODE}/projections/angle_{a:03d}.npy", None) for a in ANGLES
    ]
    assert [s.stage_number for s in study.stages] == list(StageNumber)
    assert all(s.status is StageStatus.WAITING for s in study.stages)


@pytest.mark.unit
def test_register_study_without_personal_data_uses_the_reference_patient(world: World) -> None:
    world.store.register_study(CODE, OrganName.LUNG, four_uploads(), patient=None)

    assert world.connection.params_of("insert into study") == [(CODE, "PAC000000", "lung")]


@pytest.mark.unit
def test_register_study_identifies_a_new_patient_and_links_the_study_to_it(world: World) -> None:
    new_patient = {
        "patient_code": "PAC000008",
        "first_name": "Rosa",
        "last_name": "Quispe",
        "national_id": "12345678",
    }
    world.connection.rules.clear()
    world.connection.when("pg_advisory_xact_lock", [])
    world.connection.when("where national_id", [])
    world.connection.when("select max(patient_code)", [{"last_code": "PAC000007"}])
    world.connection.when("insert into patient", [new_patient])
    world.connection.when("insert into study", [{"study_id": 1}])
    world.connection.when("select study_id from study where study_code", [{"study_id": 1}])
    world.connection.when("from study s join organ", [{**STUDY_ROW, **new_patient}])
    world.connection.when("from projection p", PROJECTION_ROWS)
    world.connection.when("from processing_stage ps", STAGE_ROWS)

    study = world.store.register_study(
        CODE,
        OrganName.LUNG,
        four_uploads(),
        patient=PatientDetails("Rosa", "Quispe", "12345678"),
    )

    assert world.connection.params_of("insert into study") == [(CODE, "PAC000008", "lung")]
    assert study.patient.patient_code == "PAC000008"


@pytest.mark.unit
def test_a_duplicate_code_fails_before_uploading_anything(world: World) -> None:
    world.connection.rules.insert(0, ("insert into study", FakeUniqueViolation("study_study_code_key"), False))

    with pytest.raises(DuplicateStudyError):
        world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert world.uploaded() == []
    assert world.bucket.files == {}
    assert "db:rollback" in world.events
    assert "db:commit" not in world.events


@pytest.mark.unit
@pytest.mark.parametrize("code", ["", "a b", "a/b", "..", "x" * 65])
def test_an_invalid_code_fails_without_touching_the_database_or_the_bucket(
    world: World, code: str
) -> None:
    with pytest.raises(InvalidStudyIdError):
        world.store.register_study(code, OrganName.LUNG, four_uploads())

    assert world.events == []


@pytest.mark.unit
def test_an_unknown_organ_fails_without_touching_anything(world: World) -> None:
    with pytest.raises(UnknownOrganError):
        world.store.register_study(CODE, "heart", four_uploads())

    assert world.events == []


@pytest.mark.unit
def test_the_four_distinct_angles_are_required(world: World) -> None:
    three = four_uploads()[:3]
    repeated = [*four_uploads()[:3], ProjectionUpload(0, np.zeros((4, 4)))]
    wrong_angle = [*four_uploads()[:3], ProjectionUpload(30, np.zeros((4, 4)))]

    for bad in (three, repeated, wrong_angle, []):
        with pytest.raises(InvalidProjectionError):
            world.store.register_study(CODE, OrganName.LUNG, bad)

    assert world.events == []


@pytest.mark.unit
def test_a_failed_upload_rolls_the_transaction_back_and_records_no_projection(
    world: World,
) -> None:
    world.bucket.fail_next("upload", StorageException("cuota excedida"), after=2)

    with pytest.raises(StorageError):
        world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert "db:rollback" in world.events
    assert "db:commit" not in world.events
    assert not world.connection.params_of("insert into projection")


@pytest.mark.unit
def test_a_database_failure_after_the_uploads_rolls_back(world: World) -> None:
    world.connection.rules.insert(
        0, ("insert into projection", FakeCheckViolation("projection_angle_allowed"), False)
    )

    with pytest.raises(InvalidProjectionError):
        world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    assert "db:rollback" in world.events
    assert "db:commit" not in world.events


@pytest.mark.unit
def test_retrying_with_the_same_code_replaces_files_left_by_a_failed_attempt(
    world: World,
) -> None:
    world.bucket.files[f"{CODE}/projections/angle_000.npy"] = b"huerfano"

    world.store.register_study(CODE, OrganName.LUNG, four_uploads())

    stored = ObjectStorage(world.bucket).download_array(f"{CODE}/projections/angle_000.npy")
    assert stored.shape == (4, 4)


@pytest.mark.unit
def test_get_study_returns_the_study_with_projections_and_stages(world: World) -> None:
    study = world.store.get_study(CODE)

    assert study.study_code == CODE
    assert [p.angle_degrees for p in study.projections] == list(ANGLES)
    assert len(study.stages) == 4
    assert world.connection.params_of("where s.study_code = %s")[0] == (CODE,)


@pytest.mark.unit
def test_get_study_raises_not_found_for_an_unknown_study(world: World) -> None:
    world.connection.rules.clear()
    world.connection.when("from study s join organ", [])

    with pytest.raises(StudyNotFoundError):
        world.store.get_study("it_no_existe")


@pytest.mark.unit
def test_get_study_rejects_an_invalid_code_without_touching_the_database(world: World) -> None:
    with pytest.raises(InvalidStudyIdError):
        world.store.get_study("../otro")

    assert world.events == []


@pytest.mark.unit
def test_list_studies_returns_the_studies_without_nested_data(world: World) -> None:
    world.connection.rules.clear()
    world.connection.when(
        "from study s join organ",
        [{**STUDY_ROW, "study_code": "it_nuevo"}, {**STUDY_ROW, "study_code": "it_viejo"}],
    )

    studies = world.store.list_studies()

    assert [s.study_code for s in studies] == ["it_nuevo", "it_viejo"]
    assert all((s.projections, s.stages, s.lesions) == ([], [], []) for s in studies)


# --- Historia 2: volumen reconstruido (FR-046) ---


@pytest.mark.unit
def test_save_volume_uploads_the_array_and_returns_its_path(world: World) -> None:
    volume = np.arange(8, dtype=np.float32).reshape(2, 2, 2)

    path = world.store.save_volume(CODE, volume)

    assert path == f"{CODE}/volume.npy"
    assert world.uploaded() == [f"{CODE}/volume.npy"]
    assert world.bucket.content_types[path] == "application/octet-stream"
    assert np.array_equal(ObjectStorage(world.bucket).download_array(path), volume)


@pytest.mark.unit
def test_save_volume_only_reads_from_the_database_it_never_writes(world: World) -> None:
    world.store.save_volume(CODE, np.zeros((2, 2, 2), dtype=np.float32))

    statements = world.connection.statements()
    assert statements, "debia comprobar que el estudio existe"
    assert all(statement.startswith("select") for statement in statements)


@pytest.mark.unit
def test_save_volume_checks_the_study_exists_before_uploading(world: World) -> None:
    world.store.save_volume(CODE, np.zeros((2, 2, 2), dtype=np.float32))

    lookup = index_of(world.events, "select study_id from study where study_code")
    assert lookup != -1
    assert lookup < index_of(world.events, "upload:")


@pytest.mark.unit
def test_save_volume_releases_the_connection_before_the_slow_upload(world: World) -> None:
    world.store.save_volume(CODE, np.zeros((2, 2, 2), dtype=np.float32))

    commit = index_of(world.events, "db:commit")
    assert commit != -1
    assert commit < index_of(world.events, "upload:")


@pytest.mark.unit
def test_save_volume_for_an_unknown_study_uploads_nothing(world: World) -> None:
    world.connection.rules.clear()
    world.connection.when("select study_id from study where study_code", [])

    with pytest.raises(StudyNotFoundError):
        world.store.save_volume("it_no_existe", np.zeros((2, 2, 2), dtype=np.float32))

    assert world.uploaded() == []
    assert world.bucket.files == {}
    assert index_of(world.events, "upload:") == -1


@pytest.mark.unit
@pytest.mark.parametrize("code", ["", "a b", "a/b", "..", "x" * 65])
def test_save_volume_rejects_an_invalid_code_without_uploading(world: World, code: str) -> None:
    with pytest.raises(InvalidStudyIdError):
        world.store.save_volume(code, np.zeros((2, 2, 2), dtype=np.float32))

    assert world.events == []
    assert world.bucket.files == {}


@pytest.mark.unit
def test_save_volume_replaces_a_previous_volume(world: World) -> None:
    world.store.save_volume(CODE, np.zeros((2, 2, 2), dtype=np.float32))

    world.store.save_volume(CODE, np.ones((2, 2, 2), dtype=np.float32))

    stored = ObjectStorage(world.bucket).download_array(f"{CODE}/volume.npy")
    assert np.array_equal(stored, np.ones((2, 2, 2), dtype=np.float32))


@pytest.mark.unit
def test_save_volume_reports_a_failed_upload_as_a_storage_error(world: World) -> None:
    world.bucket.fail_next("upload", StorageException("cuota excedida"))

    with pytest.raises(StorageError):
        world.store.save_volume(CODE, np.zeros((2, 2, 2), dtype=np.float32))


# --- Historia 3: get_study devuelve tambien las lesiones (FR-045) ---


@pytest.mark.unit
def test_get_study_returns_the_lesions_too(world: World) -> None:
    world.connection.when(
        "from lesion l",
        [
            {
                "location": "centro",
                "volume_mm3": 8000.0,
                "max_diameter_mm": 25.5,
                "confidence": 0.9,
                "mesh_path": f"{CODE}/meshes/tumor.glb",
            }
        ],
    )

    study = world.store.get_study(CODE)

    assert study.lesions == [Lesion("centro", 8000.0, 0.9, 25.5, f"{CODE}/meshes/tumor.glb")]
    assert world.connection.params_of("from lesion l") == [(CODE,)]


@pytest.mark.unit
def test_a_study_without_lesions_has_an_empty_list(world: World) -> None:
    assert world.store.get_study(CODE).lesions == []


# ---------------------------------------------------------------------------
# delete_study (funcionalidad 002, historia 3; research.md R8)
# ---------------------------------------------------------------------------

STUDY_FILES = [
    f"{CODE}/projections/angle_000.npy",
    f"{CODE}/projections/angle_045.npy",
    f"{CODE}/projections/angle_090.npy",
    f"{CODE}/projections/angle_135.npy",
    f"{CODE}/volume.npy",
    f"{CODE}/segmentation/mask.npy",
    f"{CODE}/segmentation/probability.npy",
    f"{CODE}/segmentation/summary.json",
    f"{CODE}/meshes/organ.glb",
    f"{CODE}/meshes/tumor.glb",
]


class DeleteWorld:
    """Un estudio con sus diez archivos en el bucket, listo para borrar."""

    def __init__(self, status: str = "completed") -> None:
        self.events: list[str] = []
        self.database = FakeDatabase(events=self.events)
        self.bucket = InMemoryBucket(events=self.events)
        self.store = StudyMetadataStore(self.database, ObjectStorage(self.bucket))
        for path in STUDY_FILES:
            self.bucket.files[path] = b"x"
        self.bucket.files["it_otro/volume.npy"] = b"y"
        self.connection = self.database.connection
        self.connection.when("for update", [{"status": status}])


@pytest.mark.unit
def test_delete_locks_checks_deletes_removes_the_files_and_then_commits() -> None:
    world = DeleteWorld()

    world.store.delete_study(CODE)

    events = world.events
    lock = index_of(events, "for update")
    delete = index_of(events, "delete from study")
    remove = index_of(events, "remove:")
    assert -1 not in (lock, delete, remove)
    assert lock < delete < remove < events.index("db:commit")
    assert world.database.committed == 1


@pytest.mark.unit
def test_delete_removes_exactly_the_ten_files_of_the_study() -> None:
    world = DeleteWorld()

    world.store.delete_study(CODE)

    removes = [e for e in world.events if e.startswith("remove:")]
    assert removes == [f"remove:{','.join(STUDY_FILES)}"]
    assert world.bucket.uploaded_paths() == ["it_otro/volume.npy"]


@pytest.mark.unit
@pytest.mark.parametrize("status", ["pending", "completed", "failed"])
def test_studies_that_are_not_processing_can_be_deleted(status: str) -> None:
    world = DeleteWorld(status)

    world.store.delete_study(CODE)

    assert world.connection.params_of("delete from study") == [(CODE,)]


@pytest.mark.unit
def test_a_study_in_processing_is_not_deleted_and_the_bucket_is_not_touched() -> None:
    from radvol3d.domain.exceptions import StudyInProgressError

    world = DeleteWorld("processing")

    with pytest.raises(StudyInProgressError) as caught:
        world.store.delete_study(CODE)

    assert CODE in str(caught.value)
    assert world.connection.params_of("delete from study") == []
    assert not any(e.startswith("remove:") for e in world.events)
    assert len(world.bucket.files) == len(STUDY_FILES) + 1


@pytest.mark.unit
def test_if_the_bucket_fails_the_deletion_is_rolled_back() -> None:
    world = DeleteWorld()
    world.bucket.fail_next("remove", StorageException("sin permiso"))

    with pytest.raises(StorageError):
        world.store.delete_study(CODE)

    assert world.database.rolled_back == 1
    assert world.database.committed == 0
    assert "db:rollback" in world.events


@pytest.mark.unit
def test_an_unknown_study_raises_not_found_and_removes_nothing() -> None:
    world = DeleteWorld()
    world.connection.rules.clear()
    world.connection.when("for update", [])

    with pytest.raises(StudyNotFoundError):
        world.store.delete_study("it_no_existe")

    assert not any(e.startswith("remove:") for e in world.events)


@pytest.mark.unit
def test_an_invalid_code_is_rejected_before_opening_the_transaction() -> None:
    world = DeleteWorld()

    with pytest.raises(InvalidStudyIdError):
        world.store.delete_study("../otro")

    assert world.events == []
