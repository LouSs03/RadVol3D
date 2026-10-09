"""Avance del procesamiento contra el Supabase de prueba (historia 2).

Se omite si no existe .env.test. Los modelos de prueba llevan el prefijo "it_" y la
limpieza de conftest.py los borra al terminar, igual que los estudios.
"""

import uuid
from collections.abc import Callable

import numpy as np
import pytest

from radvol3d.domain.entities import Model
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import PersistenceError, StudyNotFoundError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.repositories.model_repository import ModelRepository
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from radvol3d.persistence.repositories.study_repository import StudyRepository
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore
from tests.integration.conftest import SESSION_PREFIX

pytestmark = pytest.mark.integration

ANGLES = (0, 45, 90, 135)


def make_uploads() -> list[ProjectionUpload]:
    return [ProjectionUpload(a, np.full((4, 4), a, dtype=np.float32)) for a in ANGLES]


def make_model_name() -> str:
    """Nombre de modelo de prueba, unico por ejecucion y con el prefijo de limpieza."""
    return f"{SESSION_PREFIX}model_{uuid.uuid4().hex[:8]}"


def register(database: Database, storage: ObjectStorage, code: str) -> StudyMetadataStore:
    store = StudyMetadataStore(database, storage)
    store.register_study(code, OrganName.LUNG, make_uploads())
    return store


def test_the_progress_of_a_study_that_fails_halfway_is_recorded(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    store = register(database, object_storage, code)
    volume = np.arange(64, dtype=np.float32).reshape(4, 4, 4)

    # Cada cambio va en su propia transaccion, como en el procesamiento real.
    with database.transaction() as connection:
        model = ModelRepository(connection).get_or_create(make_model_name(), "1.0.0")
        StudyRepository(connection).update_status(code, StudyStatus.PROCESSING)
    for number in (StageNumber.PREPROCESSING, StageNumber.RECONSTRUCTION):
        with database.transaction() as connection:
            ProcessingStageRepository(connection).set_status(code, number, StageStatus.RUNNING)
        with database.transaction() as connection:
            used = model if number is StageNumber.RECONSTRUCTION else None
            ProcessingStageRepository(connection).set_status(
                code, number, StageStatus.COMPLETED, model=used
            )
    volume_path = store.save_volume(code, volume)
    with database.transaction() as connection:
        ProcessingStageRepository(connection).set_status(
            code, StageNumber.SEGMENTATION, StageStatus.FAILED
        )
        StudyRepository(connection).update_status(code, StudyStatus.FAILED)

    study = store.get_study(code)
    by_number = {stage.stage_number: stage for stage in study.stages}
    assert study.status is StudyStatus.FAILED
    for number in (StageNumber.PREPROCESSING, StageNumber.RECONSTRUCTION):
        stage = by_number[number]
        assert stage.status is StageStatus.COMPLETED
        assert stage.started_at is not None
        assert stage.finished_at is not None
        assert stage.started_at <= stage.finished_at
    assert by_number[StageNumber.RECONSTRUCTION].model == model
    assert by_number[StageNumber.SEGMENTATION].status is StageStatus.FAILED
    assert by_number[StageNumber.MESHING].status is StageStatus.WAITING
    assert by_number[StageNumber.MESHING].started_at is None
    assert volume_path == f"{code}/volume.npy"
    assert np.array_equal(object_storage.download_array(volume_path), volume)


def test_a_model_registered_twice_leaves_a_single_row(database: Database) -> None:
    name = make_model_name()

    with database.transaction() as connection:
        repository = ModelRepository(connection)
        first = repository.get_or_create(name, "1.0.0", description="Primera descripcion")
        second = repository.get_or_create(name, "1.0.0", description="Otra descripcion")
        count = connection.execute(
            "select count(*) as total from model where model_name = %s and version = %s",
            (name, "1.0.0"),
        ).fetchone()["total"]

    assert first == second
    assert second.description == "Primera descripcion"
    assert count == 1


def test_mark_completed_leaves_the_study_with_model_grid_size_and_time(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    store = register(database, object_storage, code)

    with database.transaction() as connection:
        model = ModelRepository(connection).get_or_create(make_model_name(), "1.0.0")
        StudyRepository(connection).mark_completed(code, model, 128, 12.5)
    study = store.get_study(code)

    assert study.status is StudyStatus.COMPLETED
    assert study.model == model
    assert study.grid_size == 128
    assert study.total_time_sec == 12.5


def test_mark_completed_with_an_unregistered_model_changes_nothing(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    store = register(database, object_storage, code)

    with pytest.raises(PersistenceError), database.transaction() as connection:
        StudyRepository(connection).mark_completed(code, Model(make_model_name(), "9.9.9"), 128, 1.0)
    study = store.get_study(code)

    assert study.status is StudyStatus.PENDING
    assert study.model is None
    assert study.grid_size is None


def test_a_stage_skipped_without_starting_has_no_start_time(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    store = register(database, object_storage, code)

    with database.transaction() as connection:
        ProcessingStageRepository(connection).set_status(
            code, StageNumber.MESHING, StageStatus.SKIPPED
        )
    stage = {s.stage_number: s for s in store.get_study(code).stages}[StageNumber.MESHING]

    assert stage.status is StageStatus.SKIPPED
    assert stage.started_at is None
    assert stage.finished_at is not None


def test_a_volume_for_an_unknown_study_is_rejected_and_never_uploaded(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    store = StudyMetadataStore(database, object_storage)

    with pytest.raises(StudyNotFoundError):
        store.save_volume(code, np.zeros((4, 4, 4), dtype=np.float32))

    assert object_storage.exists(f"{code}/volume.npy") is False
