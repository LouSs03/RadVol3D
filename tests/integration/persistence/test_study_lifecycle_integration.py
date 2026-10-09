"""Flujo en tres pasos contra el Supabase de prueba (funcionalidad 004, historia 1).

Crear, subir las proyecciones y reclamar el estudio, con la base real: el bloqueo de
fila de claim_for_processing solo se puede probar aqui. Se omite si no existe
.env.test. Los estudios usan el prefijo "it_" y la limpieza de conftest.py los borra.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from radvol3d.domain.enums import OrganName, StageStatus, StudyStatus
from radvol3d.domain.exceptions import InvalidStudyStateError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore

pytestmark = pytest.mark.integration

ANGLES = (0, 45, 90, 135)


def make_uploads() -> list[ProjectionUpload]:
    return [
        ProjectionUpload(angle, np.full((4, 4), angle, dtype=np.float32)) for angle in ANGLES
    ]


@pytest.fixture
def metadata(database: Database, object_storage: ObjectStorage) -> StudyMetadataStore:
    return StudyMetadataStore(database, object_storage)


@pytest.fixture
def ready_study(metadata: StudyMetadataStore, make_study_code: Callable[[], str]) -> str:
    """Un estudio en pending con sus cuatro proyecciones."""
    code = make_study_code()
    metadata.create_study(code, OrganName.LUNG)
    metadata.add_projections(code, make_uploads())
    return code


def test_create_upload_and_claim_leave_the_study_in_processing(
    metadata: StudyMetadataStore, make_study_code: Callable[[], str]
) -> None:
    code = make_study_code()

    created = metadata.create_study(code, OrganName.LUNG)
    assert created.status is StudyStatus.PENDING
    assert created.projections == []
    assert [s.status for s in created.stages] == [StageStatus.WAITING] * 4

    with_projections = metadata.add_projections(code, make_uploads())
    assert [p.angle_degrees for p in with_projections.projections] == list(ANGLES)

    metadata.claim_for_processing(code)
    assert metadata.get_study(code).status is StudyStatus.PROCESSING
    loaded = metadata.load_projections(code)
    assert float(loaded[90][0, 0]) == 90.0


def test_a_second_upload_is_rejected(metadata: StudyMetadataStore, ready_study: str) -> None:
    with pytest.raises(InvalidStudyStateError):
        metadata.add_projections(ready_study, make_uploads())


def test_a_study_without_projections_cannot_be_claimed(
    metadata: StudyMetadataStore, make_study_code: Callable[[], str]
) -> None:
    code = make_study_code()
    metadata.create_study(code, OrganName.LUNG)

    with pytest.raises(InvalidStudyStateError):
        metadata.claim_for_processing(code)

    assert metadata.get_study(code).status is StudyStatus.PENDING


def test_two_simultaneous_claims_only_one_wins(
    metadata: StudyMetadataStore, ready_study: str
) -> None:
    def claim() -> str:
        try:
            metadata.claim_for_processing(ready_study)
        except InvalidStudyStateError:
            return "rechazado"
        return "reclamado"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(lambda _: claim(), range(2)))

    assert results == ["reclamado", "rechazado"]


def test_an_interrupted_study_fails_from_its_running_stage(
    database: Database, metadata: StudyMetadataStore, ready_study: str
) -> None:
    progress = ProcessingProgressStore(database)
    metadata.claim_for_processing(ready_study)
    progress.start_stage(ready_study, 1)

    recovered = progress.fail_interrupted_studies()

    assert ready_study in recovered
    study = metadata.get_study(ready_study)
    assert study.status is StudyStatus.FAILED
    assert [s.status for s in study.stages] == [
        StageStatus.FAILED,
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
    ]
