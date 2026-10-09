"""Guardado y consulta de resultados contra el Supabase de prueba (historia 3).

Se omite si no existe .env.test. Los modelos de prueba llevan el prefijo "it_" y la
limpieza de conftest.py los borra al terminar, igual que los estudios y sus archivos.

Desde la funcionalidad 002 (research.md R7), save_result sube los archivos e inserta
las lesiones, pero NO cierra las etapas 3 y 4: eso lo hace la tuberia con
ProcessingProgressStore. Hasta entonces get_result sigue vacio.

Desde la funcionalidad 004 (research.md R10 y R11), cada lesion tiene su propia malla
(lesion_<NNN>.glb, enlazada por mesh_path) y su organo como texto en lesion.organ.
Necesita docs/database/schema/002_add_lesion_organ.sql aplicada en la base de prueba.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
import psycopg
import psycopg.errors
import pytest

from radvol3d.domain.entities import Lesion, StoredResult
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus
from radvol3d.domain.exceptions import InvalidLesionError, StudyNotFoundError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.settings import Settings
from radvol3d.persistence.study_metadata_store import ProjectionUpload, StudyMetadataStore

pytestmark = pytest.mark.integration

ANGLES = (0, 45, 90, 135)


def make_summary(regions: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
    return {
        "study_id": "prueba",
        "organ": "lung",
        "model_name": model_name,
        "model_version": "1.0.0",
        "threshold": 0.45,
        "mm_per_voxel": 2.5,
        "grid": 128,
        "has_lesion": bool(regions),
        "lesion_count": len(regions),
        "global_confidence": 0.885,
        "total_volume_mm3": sum(r["volume_mm3"] for r in regions),
        "location_note": "Región central del pulmón",
        "regions": regions,
    }


def make_region(region_id: int, volume: float, diameter: float, confidence: float) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "has_lesion": True,
        "location": f"posicion {region_id}",
        "volume_mm3": volume,
        "max_diameter_mm": diameter,
        "confidence": confidence,
        "confidence_min": 0.5,
        "confidence_max": 0.99,
        "voxels": 1000 + region_id,
        "centroid_voxel": [60, 61, 62],
    }


def make_model_name() -> str:
    return f"it_seg_{uuid.uuid4().hex[:8]}"


def register_ready(database: Database, storage: ObjectStorage, code: str) -> StudyMetadataStore:
    """Registra un estudio y deja completadas las etapas 1 y 2, como antes de segmentar."""
    store = StudyMetadataStore(database, storage)
    uploads = [ProjectionUpload(a, np.full((4, 4), a, dtype=np.float32)) for a in ANGLES]
    store.register_study(code, OrganName.LUNG, uploads)
    for number in (StageNumber.PREPROCESSING, StageNumber.RECONSTRUCTION):
        with database.transaction() as connection:
            ProcessingStageRepository(connection).set_status(code, number, StageStatus.COMPLETED)
    return store


def close_stages(database: Database, code: str, model_name: str) -> None:
    """Cierra las etapas 3 y 4 como lo hace la tuberia despues de save_result."""
    progress = ProcessingProgressStore(database)
    progress.complete_stage(code, StageNumber.SEGMENTATION, model_name, "1.0.0")
    progress.complete_stage(code, StageNumber.MESHING)


def save(
    store: ResultStore, code: str, summary: dict[str, Any], lesion_meshes: list[bytes]
) -> StoredResult:
    return store.save_result(
        code,
        np.ones((4, 4, 4), dtype=np.uint8),
        np.full((4, 4, 4), 0.75, dtype=np.float32),
        summary,
        b"glTF-organ",
        b"glTF-tumor",
        lesion_meshes=lesion_meshes,
    )


def test_a_saved_result_comes_back_with_the_same_lesions_and_files(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    metadata = register_ready(database, object_storage, code)
    results = ResultStore(database, object_storage)
    model_name = make_model_name()
    regions = [make_region(1, 8000.0, 26.5, 0.885), make_region(2, 500.25, 11.75, 0.7123)]
    summary = make_summary(regions, model_name)
    lesion_meshes = [f"{code}/meshes/lesion_001.glb", f"{code}/meshes/lesion_002.glb"]

    saved = save(results, code, summary, lesion_meshes=[b"glTF-lesion-1", b"glTF-lesion-2"])
    assert results.get_result(code) == StoredResult(code)  # etapas aun abiertas
    close_stages(database, code, model_name)
    result = results.get_result(code)

    expected = [
        Lesion("posicion 1", 8000.0, 0.885, 26.5, lesion_meshes[0], OrganName.LUNG),
        Lesion("posicion 2", 500.25, 0.7123, 11.75, lesion_meshes[1], OrganName.LUNG),
    ]
    assert saved.lesions == expected
    assert result.lesions == expected
    assert metadata.get_study(code).lesions == expected
    assert np.array_equal(
        object_storage.download_array(result.mask_path), np.ones((4, 4, 4), dtype=np.uint8)
    )
    assert np.array_equal(
        object_storage.download_array(result.probability_path),
        np.full((4, 4, 4), 0.75, dtype=np.float32),
    )
    assert json.loads(object_storage.download_bytes(result.summary_path)) == summary
    assert object_storage.download_bytes(result.organ_mesh_path) == b"glTF-organ"
    assert object_storage.download_bytes(result.tumor_mesh_path) == b"glTF-tumor"
    for number, path in enumerate(lesion_meshes, 1):
        assert object_storage.exists(path), path
        assert object_storage.download_bytes(path) == f"glTF-lesion-{number}".encode()
    stages = {s.stage_number: s for s in metadata.get_study(code).stages}
    assert stages[StageNumber.SEGMENTATION].status is StageStatus.COMPLETED
    assert stages[StageNumber.SEGMENTATION].model.model_name == model_name
    assert stages[StageNumber.MESHING].status is StageStatus.COMPLETED


def test_a_result_without_lesions_still_has_its_five_paths(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    metadata = register_ready(database, object_storage, code)
    results = ResultStore(database, object_storage)

    model_name = make_model_name()
    save(results, code, make_summary([], model_name), lesion_meshes=[])
    close_stages(database, code, model_name)
    result = results.get_result(code)

    assert result.lesions == []
    assert result.mask_path == f"{code}/segmentation/mask.npy"
    stages = {s.stage_number: s for s in metadata.get_study(code).stages}
    assert stages[StageNumber.SEGMENTATION].status is StageStatus.COMPLETED
    assert stages[StageNumber.MESHING].status is StageStatus.COMPLETED


def test_an_invalid_lesion_leaves_the_stages_as_they_were_and_uploads_nothing(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    metadata = register_ready(database, object_storage, code)
    results = ResultStore(database, object_storage)
    summary = make_summary([make_region(1, 8000.0, 26.5, 2.0)], make_model_name())

    with pytest.raises(InvalidLesionError):
        save(results, code, summary, lesion_meshes=[b"glTF-lesion-1"])

    stages = {s.stage_number: s for s in metadata.get_study(code).stages}
    assert stages[StageNumber.SEGMENTATION].status is StageStatus.WAITING
    assert stages[StageNumber.MESHING].status is StageStatus.WAITING
    assert results.get_result(code) == StoredResult(code)
    assert object_storage.exists(f"{code}/segmentation/mask.npy") is False


def test_a_study_without_result_gives_an_empty_result_and_no_error(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    register_ready(database, object_storage, code)

    result = ResultStore(database, object_storage).get_result(code)

    assert result == StoredResult(code)
    assert result.lesions == []
    assert result.mask_path is None


def test_an_unknown_study_is_rejected_and_nothing_is_uploaded(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    code = make_study_code()
    results = ResultStore(database, object_storage)

    with pytest.raises(StudyNotFoundError):
        save(results, code, make_summary([], make_model_name()), lesion_meshes=[])
    with pytest.raises(StudyNotFoundError):
        results.get_result(code)

    assert object_storage.exists(f"{code}/segmentation/mask.npy") is False


def test_the_database_rejects_an_organ_outside_the_scope_in_a_lesion(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
    test_settings: Settings,
) -> None:
    code = make_study_code()
    register_ready(database, object_storage, code)

    # SQL a mano y con una conexion propia, a proposito: prueba la ultima defensa de la
    # base, que la aplicacion nunca llega a usar porque toma el organo del estudio.
    # Database.transaction() traduciria el error y ocultaria el nombre de la restriccion.
    with psycopg.connect(test_settings.database_url.get_secret_value()) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "insert into lesion (study_id, location, volume_mm3, confidence, organ) "
                "select study_id, 'a mano', 1, 0.5, 'kidney' from study where study_code = %s",
                (code,),
            )
        connection.rollback()

    assert raised.value.diag.constraint_name == "lesion_organ_allowed"
