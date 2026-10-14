"""Regeneracion de la malla del organo contra el Supabase de prueba.

Comprueba lo que promete scripts/regenerate_organ_meshes.py: solo cambia organ.glb, el
resto del resultado (tumor, lesiones, sus filas, el resumen) queda igual, y la malla
vieja se puede volver a poner. Se omite si no existe .env.test.
"""

import io
import secrets
from collections.abc import Callable

import pytest
import trimesh

from radvol3d.domain.entities import PatientDetails
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.lung_air_region import LungAirRegion
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.organ_mesh_regeneration import OrganMeshRegenerator
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyRequest
from tests.fixtures.projection_files import four_valid_files
from tests.integration.services.service_builder import build_service
from tests.unit.services.test_lung_air_region import thorax

pytestmark = pytest.mark.integration


def test_regenerating_changes_only_the_organ_mesh_and_can_be_undone(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    code = make_study_code()
    service, metadata = build_service(database, object_storage)
    patient = PatientDetails("Prueba", "Regeneracion", f"{secrets.randbelow(10**8):08d}")
    study = service.process_study(
        StudyRequest(code, OrganName.LUNG, four_valid_files(seed=5), patient)
    )
    if study.patient is not None:
        created_patient_codes.append(study.patient.patient_code)
    assert study.status is StudyStatus.COMPLETED
    # El volumen de los dobles es constante: se pone un torax para que haya pulmon.
    volume, _, _ = thorax()
    object_storage.upload_array(f"{code}/volume.npy", volume)

    result = service.get_result(code)
    untouched = [result.tumor_mesh_path, result.summary_path, result.mask_path]
    untouched += [lesion.mesh_path for lesion in result.lesions]
    before = {path: object_storage.download_bytes(path) for path in untouched}
    old_organ = object_storage.download_bytes(result.organ_mesh_path)

    factory = StrategyFactory(
        reconstruction_builders={},
        segmentation_builders={},
        meshing_builder=MarchingCubesStrategy,
        reconstruction_key="en1",
        organ_meshing_builders={
            OrganName.LUNG: lambda: MarchingCubesStrategy(organ_region=LungAirRegion())
        },
    )
    factory.preload()
    regenerator = OrganMeshRegenerator(
        StudyMetadataStore(database, object_storage),
        ResultStore(database, object_storage),
        factory,
    )
    assert code in [s.study_code for s in regenerator.completed_studies()]

    update = regenerator.build(metadata.get_study(code))
    assert update.previous == old_organ
    regenerator.save(code, update.current)

    new_organ = object_storage.download_bytes(result.organ_mesh_path)
    assert new_organ == update.current != old_organ
    scene = trimesh.load(io.BytesIO(new_organ), file_type="glb")
    assert sum(len(g.vertices) for g in scene.geometry.values()) > 0
    assert {path: object_storage.download_bytes(path) for path in untouched} == before
    after = service.get_result(code)
    assert after.lesions == result.lesions
    assert service.get_study(code).status is StudyStatus.COMPLETED

    regenerator.save(code, update.previous)  # deshacer
    assert object_storage.download_bytes(result.organ_mesh_path) == old_organ
