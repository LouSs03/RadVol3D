"""Consulta y borrado de estudios contra el Supabase de prueba (historia 3).

Se omite si no existe .env.test. Lo que se crea lleva el prefijo "it_" y la limpieza
de tests/integration/conftest.py borra lo que quede.
"""

import secrets
from collections.abc import Callable

import pytest

from radvol3d.domain.entities import PatientDetails
from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import (
    StageFailedError,
    StudyInProgressError,
    StudyNotFoundError,
)
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.repositories.patient_repository import PatientRepository
from radvol3d.persistence.study_metadata_store import ProjectionUpload
from radvol3d.services.study_service import StudyRequest
from tests.fixtures.fake_strategies import FailingSegmentationStrategy
from tests.fixtures.projection_files import four_valid_files, valid_array
from tests.integration.services.service_builder import build_service

pytestmark = pytest.mark.integration


def study_paths(code: str) -> list[str]:
    return [f"{code}/projections/angle_{a:03d}.npy" for a in (0, 45, 90, 135)] + [
        f"{code}/volume.npy",
        f"{code}/segmentation/mask.npy",
        f"{code}/segmentation/probability.npy",
        f"{code}/segmentation/summary.json",
        f"{code}/meshes/organ.glb",
        f"{code}/meshes/tumor.glb",
    ]


def test_a_completed_study_is_deleted_with_all_its_files_and_the_patient_stays(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    code = make_study_code()
    service, _ = build_service(database, object_storage)
    patient = PatientDetails("Prueba", "Borrado", f"{secrets.randbelow(10**8):08d}")
    study = service.process_study(
        StudyRequest(code, OrganName.LUNG, four_valid_files(seed=31), patient)
    )
    created_patient_codes.append(study.patient.patient_code)
    assert all(object_storage.exists(p) for p in study_paths(code))
    # Funcionalidad 004: tambien la malla de cada lesion.
    assert object_storage.exists(f"{code}/meshes/lesion_001.glb")
    assert code in [s.study_code for s in service.list_studies()]

    service.delete_study(code)

    with pytest.raises(StudyNotFoundError):
        service.get_study(code)
    assert not any(object_storage.exists(p) for p in study_paths(code))
    for folder in (code, f"{code}/projections", f"{code}/segmentation", f"{code}/meshes"):
        assert object_storage.list_names(folder) == [], folder
    assert code not in [s.study_code for s in service.list_studies()]
    with database.transaction() as connection:
        kept = PatientRepository(connection).get_by_code(study.patient.patient_code)
    assert kept is not None


def test_deleting_an_unknown_study_raises_not_found(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    service, _ = build_service(database, object_storage)

    with pytest.raises(StudyNotFoundError):
        service.delete_study(make_study_code())


def test_a_study_in_processing_cannot_be_deleted(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    service, metadata = build_service(database, object_storage)
    uploads = [ProjectionUpload(a, valid_array(a)) for a in (0, 45, 90, 135)]
    metadata.register_study(code, OrganName.LUNG, uploads)
    ProcessingProgressStore(database).start_processing(code)

    with pytest.raises(StudyInProgressError):
        service.delete_study(code)

    assert service.get_study(code).study_code == code
    assert object_storage.exists(f"{code}/projections/angle_000.npy")


def test_deleting_a_failed_study_cleans_the_files_it_left(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    service, _ = build_service(database, object_storage, FailingSegmentationStrategy)
    with pytest.raises(StageFailedError):
        service.process_study(StudyRequest(code, OrganName.LUNG, four_valid_files(seed=32)))
    assert object_storage.exists(f"{code}/volume.npy")

    service.delete_study(code)

    with pytest.raises(StudyNotFoundError):
        service.get_study(code)
    assert not any(object_storage.exists(p) for p in study_paths(code))
