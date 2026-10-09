"""Fallos de la tuberia contra el Supabase de prueba (historia 2).

Se omite si no existe .env.test. Lo que se crea lleva el prefijo "it_" y la limpieza
de tests/integration/conftest.py lo borra al terminar.
"""

from collections.abc import Callable

import pytest

from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import (
    InvalidProjectionError,
    ModelNotAvailableError,
    StageFailedError,
    StudyNotFoundError,
)
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.services.pipeline.projection_loader import ProjectionFile
from radvol3d.services.study_service import StudyRequest
from tests.fixtures.fake_strategies import FailingSegmentationStrategy
from tests.fixtures.projection_files import four_valid_files, png_bytes
from tests.integration.services.service_builder import build_service

pytestmark = pytest.mark.integration


def test_a_failure_in_stage_three_leaves_a_consistent_failed_study(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    service, metadata = build_service(database, object_storage, FailingSegmentationStrategy)

    with pytest.raises(StageFailedError) as caught:
        service.process_study(StudyRequest(code, OrganName.LUNG, four_valid_files(seed=21)))

    assert caught.value.stage_number is StageNumber.SEGMENTATION
    study = metadata.get_study(code)
    assert study.status is StudyStatus.FAILED
    stages = {s.stage_number: s.status for s in study.stages}
    assert stages == {
        StageNumber.PREPROCESSING: StageStatus.COMPLETED,
        StageNumber.RECONSTRUCTION: StageStatus.COMPLETED,
        StageNumber.SEGMENTATION: StageStatus.FAILED,
        StageNumber.MESHING: StageStatus.SKIPPED,
    }


def test_liver_fails_without_creating_the_study(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    service, _ = build_service(database, object_storage)

    with pytest.raises(ModelNotAvailableError):
        service.process_study(StudyRequest(code, OrganName.LIVER, four_valid_files()))

    with pytest.raises(StudyNotFoundError):
        service.get_study(code)


def test_a_png_projection_fails_without_creating_the_study(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    service, _ = build_service(database, object_storage)
    files = [
        ProjectionFile(f.angle_degrees, png_bytes() if f.angle_degrees == 90 else f.content)
        for f in four_valid_files()
    ]

    with pytest.raises(InvalidProjectionError):
        service.process_study(StudyRequest(code, OrganName.LUNG, files))

    with pytest.raises(StudyNotFoundError):
        service.get_study(code)
    assert object_storage.exists(f"{code}/projections/angle_000.npy") is False
