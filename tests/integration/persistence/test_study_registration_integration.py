"""Registro de un estudio contra el Supabase de prueba (historia 1).

Se omite si no existe .env.test. Los estudios usan el prefijo "it_" y la limpieza
de conftest.py los borra al terminar.
"""

import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from radvol3d.domain.entities import PatientDetails
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import DuplicateStudyError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore

pytestmark = pytest.mark.integration

ANGLES = (0, 45, 90, 135)
REFERENCE_PATIENT_CODE = "PAC000000"


def make_uploads(seed: int = 0) -> list[ProjectionUpload]:
    return [
        ProjectionUpload(
            angle,
            np.full((4, 4), angle + seed, dtype=np.float32),
            f"angulo_{angle}.npy",
        )
        for angle in ANGLES
    ]


def random_national_id() -> str:
    """DNI de prueba de ocho digitos, sin relacion con ninguna persona."""
    return f"{secrets.randbelow(10**8):08d}"


def count_patients_with_national_id(database: Database, national_id: str) -> int:
    with database.transaction() as connection:
        row = connection.execute(
            "select count(*) as total from patient where national_id = %s", (national_id,)
        ).fetchone()
    return row["total"]


def test_a_registered_study_comes_back_with_the_same_values(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    store = StudyMetadataStore(database, object_storage)
    code = make_study_code()
    national_id = random_national_id()
    uploads = make_uploads()

    registered = store.register_study(
        code, OrganName.LUNG, uploads, PatientDetails("Prueba", "Integracion", national_id)
    )
    created_patient_codes.append(registered.patient.patient_code)
    study = store.get_study(code)

    assert study.study_code == code
    assert study.organ is OrganName.LUNG
    assert study.status is StudyStatus.PENDING
    assert study.patient.national_id == national_id
    assert study.patient.patient_code.startswith("PAC")
    assert [p.angle_degrees for p in study.projections] == list(ANGLES)
    assert [p.original_name for p in study.projections] == [f"angulo_{a}.npy" for a in ANGLES]
    assert [s.stage_number for s in study.stages] == list(StageNumber)
    assert all(s.status is StageStatus.WAITING for s in study.stages)
    for upload, projection in zip(uploads, study.projections, strict=True):
        stored = object_storage.download_array(projection.file_path)
        assert np.array_equal(stored, upload.array)


def test_two_studies_with_the_same_national_id_share_one_patient(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    store = StudyMetadataStore(database, object_storage)
    national_id = random_national_id()
    details = PatientDetails("Prueba", "Integracion", national_id)

    first = store.register_study(make_study_code(), OrganName.LUNG, make_uploads(), details)
    second = store.register_study(make_study_code(), OrganName.LIVER, make_uploads(1), details)
    created_patient_codes.append(first.patient.patient_code)

    assert first.patient.patient_code == second.patient.patient_code
    assert count_patients_with_national_id(database, national_id) == 1


def test_simultaneous_registrations_without_national_id_get_different_codes(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    store = StudyMetadataStore(database, object_storage)
    codes = [make_study_code() for _ in range(4)]

    def register(code: str) -> str:
        study = store.register_study(
            code, OrganName.LUNG, make_uploads(), PatientDetails(first_name="Prueba")
        )
        return study.patient.patient_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        patient_codes = list(pool.map(register, codes))
    created_patient_codes.extend(patient_codes)

    assert len(set(patient_codes)) == 4
    assert REFERENCE_PATIENT_CODE not in patient_codes


def test_a_repeated_code_is_rejected_and_keeps_the_original_files(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    store = StudyMetadataStore(database, object_storage)
    code = make_study_code()
    original = make_uploads(0)
    store.register_study(code, OrganName.LUNG, original)

    with pytest.raises(DuplicateStudyError):
        store.register_study(code, OrganName.LUNG, make_uploads(100))

    kept = object_storage.download_array(f"{code}/projections/angle_000.npy")
    assert np.array_equal(kept, original[0].array)


def test_without_personal_data_the_study_belongs_to_the_reference_patient(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    store = StudyMetadataStore(database, object_storage)

    study = store.register_study(make_study_code(), OrganName.LUNG, make_uploads())

    assert study.patient.patient_code == REFERENCE_PATIENT_CODE
