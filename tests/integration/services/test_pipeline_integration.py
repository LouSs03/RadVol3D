"""Tuberia completa con dobles contra el Supabase de prueba (historia 1).

Se omite si no existe .env.test. Los estudios llevan el prefijo "it_" y la limpieza
de tests/integration/conftest.py los borra al terminar, con sus archivos.
"""

import secrets
from collections.abc import Callable

import pytest

from radvol3d import config
from radvol3d.domain.entities import PatientDetails, Study
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.study_service import StudyRequest
from tests.fixtures.fake_strategies import FakeSegmentationStrategy
from tests.fixtures.projection_files import four_valid_files
from tests.integration.services.service_builder import build_service

pytestmark = pytest.mark.integration


def request_for(code: str) -> StudyRequest:
    patient = PatientDetails("Prueba", "Integracion", f"{secrets.randbelow(10**8):08d}")
    return StudyRequest(code, OrganName.LUNG, four_valid_files(seed=11), patient)


def remember_patient(study: Study, created_patient_codes: list[str]) -> None:
    if study.patient is not None:
        created_patient_codes.append(study.patient.patient_code)


def test_a_study_runs_end_to_end_and_everything_is_recorded(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    code = make_study_code()
    service, _ = build_service(database, object_storage)

    study = service.process_study(request_for(code))
    remember_patient(study, created_patient_codes)

    assert study.status is StudyStatus.COMPLETED
    assert study.grid_size == config.GRID_SIZE
    assert study.total_time_sec is not None and study.total_time_sec > 0
    assert study.model.model_name == "fake_segmentation"
    stages = {s.stage_number: s for s in study.stages}
    assert all(s.status is StageStatus.COMPLETED for s in stages.values())
    assert all(s.started_at <= s.finished_at for s in stages.values())
    assert stages[StageNumber.PREPROCESSING].model is None
    assert stages[StageNumber.RECONSTRUCTION].model.model_name == "fake_reconstruction"
    assert stages[StageNumber.SEGMENTATION].model.model_name == "fake_segmentation"
    assert stages[StageNumber.MESHING].model is None

    result = service.get_result(code)
    assert None not in (
        result.mask_path,
        result.probability_path,
        result.summary_path,
        result.organ_mesh_path,
        result.tumor_mesh_path,
    )
    assert len(result.lesions) == 1
    for path in (
        *(p.file_path for p in study.projections),
        f"{code}/volume.npy",
        result.mask_path,
        result.probability_path,
        result.summary_path,
        result.organ_mesh_path,
        result.tumor_mesh_path,
    ):
        assert object_storage.exists(path), path

    # Funcionalidad 004: cada lesion tiene su propia malla y su organo como texto.
    # Necesita la migracion docs/database/schema/002_add_lesion_organ.sql aplicada.
    (lesion,) = result.lesions
    assert lesion.mesh_path == f"{code}/meshes/lesion_001.glb"
    assert lesion.organ is OrganName.LUNG
    assert object_storage.exists(lesion.mesh_path)


def test_while_segmenting_the_stages_show_how_far_the_pipeline_went(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    code = make_study_code()
    seen: dict[StageNumber, StageStatus] = {}
    metadata_holder: list[StudyMetadataStore] = []

    class ObservingSegmentation(FakeSegmentationStrategy):
        """Mientras corre la etapa 3, lee las etapas de la base."""

        def segment(self, volume, study_code: str):
            for stage in metadata_holder[0].get_study(study_code).stages:
                seen[stage.stage_number] = stage.status
            return super().segment(volume, study_code)

    service, metadata = build_service(database, object_storage, ObservingSegmentation)
    metadata_holder.append(metadata)

    study = service.process_study(request_for(code))
    remember_patient(study, created_patient_codes)

    assert seen == {
        StageNumber.PREPROCESSING: StageStatus.COMPLETED,
        StageNumber.RECONSTRUCTION: StageStatus.COMPLETED,
        StageNumber.SEGMENTATION: StageStatus.RUNNING,
        StageNumber.MESHING: StageStatus.WAITING,
    }
