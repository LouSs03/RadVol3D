"""Pruebas del almacen de resultados de segmentacion (FR-047 a FR-050, FR-049).

La base y el bucket comparten una lista de eventos para comprobar el orden entre
ellos: se valida y se comprueba el estudio ANTES de subir, y las lesiones se
insertan al final, en una sola transaccion.

Desde la funcionalidad 002 (research.md R7), save_result ya no marca las etapas 3 y
4 ni registra el modelo: eso lo hace la tuberia con ProcessingProgressStore.
"""

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from storage3.utils import StorageException

from radvol3d.domain.entities import Lesion, StoredResult
from radvol3d.domain.exceptions import (
    InvalidLesionError,
    InvalidStudyIdError,
    PersistenceError,
    StorageError,
    StudyNotFoundError,
)
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.result_store import ResultStore
from tests.fixtures.fake_database import FakeCheckViolation, FakeDatabase, index_of
from tests.fixtures.fake_object_storage import InMemoryBucket

CODE = "it_a"
FINISHED = datetime(2026, 10, 9, 12, 5, tzinfo=UTC)
TUMOR_MESH = f"{CODE}/meshes/tumor.glb"
MODEL_ROW = {
    "model_name": "segmentation_lung",
    "version": "1.0.0",
    "trained_on": None,
    "description": None,
}
FILES = [
    f"{CODE}/segmentation/mask.npy",
    f"{CODE}/segmentation/probability.npy",
    f"{CODE}/segmentation/summary.json",
    f"{CODE}/meshes/organ.glb",
    f"{CODE}/meshes/tumor.glb",
]


def make_region(region_id: int, volume: float = 8000.0, **overrides: Any) -> dict[str, Any]:
    region = {
        "region_id": region_id,
        "has_lesion": True,
        "location": f"posicion {region_id}",
        "volume_mm3": volume,
        "max_diameter_mm": 25.5 + region_id,
        "confidence": 0.9 - region_id / 100,
        "confidence_min": 0.5,
        "confidence_max": 0.99,
        "voxels": 7000 + region_id,
        "centroid_voxel": [60, 61, 62],
    }
    region.update(overrides)
    return region


def make_summary(regions: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    regions = [] if regions is None else regions
    summary = {
        "study_id": CODE,
        "organ": "lung",
        "model_name": "segmentation_lung",
        "model_version": "1.0.0",
        "threshold": 0.45,
        "mm_per_voxel": 2.5,
        "grid": 128,
        "has_lesion": bool(regions),
        "lesion_count": len(regions),
        "global_confidence": 0.885,
        "total_volume_mm3": sum(
            r["volume_mm3"] for r in regions if isinstance(r.get("volume_mm3"), int | float)
        ),
        "location_note": "Región central del pulmón",
        "regions": regions,
    }
    summary.update(overrides)
    return summary


def stage_rows(**statuses: str) -> list[dict[str, Any]]:
    """Cuatro filas de etapa; por defecto todas en waiting. Ej.: stage_rows(s3="completed")."""
    return [
        {
            "stage_number": number,
            "stage_status": statuses.get(f"s{number}", "waiting"),
            "started_at": None,
            "finished_at": None,
            "model_name": None,
            "version": None,
            "trained_on": None,
            "description": None,
        }
        for number in (1, 2, 3, 4)
    ]


class World:
    """Base y bucket falsos conectados entre si por una lista de eventos."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.database = FakeDatabase(events=self.events)
        self.bucket = InMemoryBucket(events=self.events)
        self.store = ResultStore(self.database, ObjectStorage(self.bucket))
        self.connection = self.database.connection
        self.lesion_rows: list[dict[str, Any]] = []
        self.connection.when("select study_id from study where study_code", [{"study_id": 1}])
        self.connection.when("insert into model", [MODEL_ROW])
        self.connection.when(
            "update processing_stage", [{"started_at": None, "finished_at": FINISHED}]
        )
        self.connection.when("from lesion l", self.lesion_rows)
        self.connection.when("from processing_stage ps", stage_rows())

    def save(self, summary: dict[str, Any] | None = None, code: str = CODE) -> StoredResult:
        if summary is None:
            summary = make_summary([make_region(1), make_region(2, 500.0)])
        return self.store.save_result(
            code,
            np.zeros((2, 2, 2), dtype=np.uint8),
            np.full((2, 2, 2), 0.5, dtype=np.float32),
            summary,
            b"glTF-organ",
            b"glTF-tumor",
        )

    def set_stage_rows(self, rows: list[dict[str, Any]]) -> None:
        """Cambia lo que responde la lectura de etapas (la que usa get_result)."""
        self.connection.rules[:] = [
            r for r in self.connection.rules if r[0] != "from processing_stage ps"
        ]
        self.connection.when("from processing_stage ps", rows)

    def uploaded(self) -> list[str]:
        return [e.removeprefix("upload:") for e in self.events if e.startswith("upload:")]

    def bucket_calls_since(self, start: int) -> list[str]:
        return [e for e in self.events[start:] if e.startswith(("upload:", "download:", "exists:"))]


@pytest.fixture
def world() -> World:
    return World()


# --- save_result: lo que se sube ---


@pytest.mark.unit
def test_save_result_uploads_the_five_files_to_their_paths(world: World) -> None:
    world.save()

    assert sorted(world.uploaded()) == sorted(FILES)


@pytest.mark.unit
def test_arrays_meshes_and_summary_have_their_content_types(world: World) -> None:
    world.save()

    types = world.bucket.content_types
    assert types[FILES[0]] == "application/octet-stream"
    assert types[FILES[1]] == "application/octet-stream"
    assert types[FILES[2]] == "application/json"
    assert types[FILES[3]] == "model/gltf-binary"
    assert types[FILES[4]] == "model/gltf-binary"


@pytest.mark.unit
def test_the_summary_is_stored_as_it_arrived_with_accents_and_key_order(world: World) -> None:
    summary = make_summary([make_region(1)])

    world.save(summary)

    raw = world.bucket.files[FILES[2]]
    assert "Región central del pulmón".encode() in raw
    assert json.loads(raw.decode("utf-8")) == summary
    assert list(json.loads(raw.decode("utf-8"))) == list(summary)


@pytest.mark.unit
def test_arrays_and_meshes_come_back_identical(world: World) -> None:
    world.save()

    storage = ObjectStorage(world.bucket)
    assert np.array_equal(storage.download_array(FILES[0]), np.zeros((2, 2, 2), dtype=np.uint8))
    assert storage.download_bytes(FILES[3]) == b"glTF-organ"
    assert storage.download_bytes(FILES[4]) == b"glTF-tumor"


# --- save_result: lesiones ---


@pytest.mark.unit
def test_each_region_becomes_one_lesion_row_pointing_to_the_tumor_mesh(world: World) -> None:
    summary = make_summary([make_region(1), make_region(2, 500.0), make_region(3, 90.0)])

    world.save(summary)

    params = world.connection.params_of("insert into lesion")
    first = summary["regions"][0]
    assert len(params) == 3
    assert params[0] == (
        1,
        first["location"],
        first["volume_mm3"],
        first["max_diameter_mm"],
        first["confidence"],
        TUMOR_MESH,
    )
    assert all(p[5] == TUMOR_MESH for p in params)


@pytest.mark.unit
def test_region_data_without_a_column_never_reaches_the_database(world: World) -> None:
    world.save(make_summary([make_region(1)]))

    params = world.connection.params_of("insert into lesion")[0]
    assert len(params) == 6
    for value in (0.5, 0.99, 7001, [60, 61, 62]):
        assert value not in params


@pytest.mark.unit
def test_a_region_without_diameter_is_accepted(world: World) -> None:
    region = make_region(1)
    del region["max_diameter_mm"]

    world.save(make_summary([region]))

    assert world.connection.params_of("insert into lesion")[0][3] is None


@pytest.mark.unit
def test_no_regions_means_no_lesion_rows_but_the_five_files_are_uploaded(
    world: World,
) -> None:
    world.save(make_summary([]))

    assert not world.connection.params_of("insert into lesion")
    assert sorted(world.uploaded()) == sorted(FILES)


@pytest.mark.unit
def test_an_element_that_is_not_a_lesion_is_ignored(world: World) -> None:
    summary = make_summary([make_region(1), make_region(2, has_lesion=False)])

    world.save(summary)

    assert len(world.connection.params_of("insert into lesion")) == 1


# --- save_result: validacion antes de tocar nada ---


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["location", "volume_mm3", "confidence"])
def test_a_region_without_a_required_key_is_rejected_before_touching_anything(
    world: World, missing: str
) -> None:
    region = make_region(1)
    del region[missing]

    with pytest.raises(InvalidLesionError):
        world.save(make_summary([make_region(2), region]))

    assert world.events == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        {"volume_mm3": 0.0},
        {"volume_mm3": -5.0},
        {"volume_mm3": "mucho"},
        {"confidence": 1.5},
        {"confidence": -0.2},
        {"location": ""},
    ],
)
def test_an_invalid_lesion_value_is_rejected_before_touching_anything(
    world: World, bad: dict[str, Any]
) -> None:
    with pytest.raises(InvalidLesionError):
        world.save(make_summary([make_region(1, **bad)]))

    assert world.events == []


@pytest.mark.unit
@pytest.mark.parametrize("regions", [None, "no es una lista", {"region_id": 1}])
def test_regions_must_be_a_list(world: World, regions: Any) -> None:
    summary = make_summary([])
    summary["regions"] = regions

    with pytest.raises(InvalidLesionError):
        world.save(summary)

    assert world.events == []


@pytest.mark.unit
def test_a_summary_without_regions_is_rejected(world: World) -> None:
    summary = make_summary([])
    del summary["regions"]

    with pytest.raises(InvalidLesionError):
        world.save(summary)

    assert world.events == []


@pytest.mark.unit
@pytest.mark.parametrize("key", ["model_name", "model_version"])
def test_a_summary_without_the_model_is_rejected_before_touching_anything(
    world: World, key: str
) -> None:
    summary = make_summary([make_region(1)])
    del summary[key]

    with pytest.raises(PersistenceError):
        world.save(summary)

    assert world.events == []


@pytest.mark.unit
@pytest.mark.parametrize("broken", [{"no": {1, 2}}, {"nan": float("nan")}])
def test_a_summary_that_cannot_be_written_as_json_is_rejected(
    world: World, broken: dict[str, Any]
) -> None:
    with pytest.raises(PersistenceError):
        world.save(make_summary([make_region(1)], extra=broken))

    assert world.events == []


@pytest.mark.unit
def test_an_invalid_study_code_is_rejected_before_touching_anything(world: World) -> None:
    with pytest.raises(InvalidStudyIdError):
        world.save(code="../otro")

    assert world.events == []


@pytest.mark.unit
def test_an_unknown_study_uploads_nothing(world: World) -> None:
    world.connection.rules.clear()
    world.connection.when("select study_id from study where study_code", [])

    with pytest.raises(StudyNotFoundError):
        world.save(code="it_no_existe")

    assert world.uploaded() == []
    assert world.bucket.files == {}


# --- save_result: orden y atomicidad ---


@pytest.mark.unit
def test_the_order_is_check_then_upload_then_write_and_commit_last(world: World) -> None:
    world.save()

    events = world.events
    lookup = index_of(events, "select study_id from study where study_code")
    first_upload = index_of(events, "upload:")
    last_upload = max(i for i, e in enumerate(events) if e.startswith("upload:"))
    lesion_insert = index_of(events, "insert into lesion")
    assert -1 not in (lookup, first_upload, lesion_insert)
    assert lookup < events.index("db:commit") < first_upload
    assert last_upload < lesion_insert
    assert events[-1] == "db:commit"
    assert "db:rollback" not in events


@pytest.mark.unit
def test_save_result_never_touches_the_stages_or_the_model_table(world: World) -> None:
    # research.md R7: si save_result marcara la etapa 3, pisaria su hora de fin con la
    # del fin de la etapa 4. Las etapas las cierra la tuberia.
    world.save()

    statements = world.connection.statements()
    assert not any("processing_stage" in s and s.startswith("update") for s in statements)
    assert not any(s.startswith("insert into model") for s in statements)


@pytest.mark.unit
def test_lesions_are_written_in_one_transaction_after_the_check(world: World) -> None:
    world.save()

    assert world.database.committed == 2  # la comprobacion previa y las lesiones


@pytest.mark.unit
def test_a_failed_lesion_insert_rolls_back_and_leaves_the_stages_untouched(world: World) -> None:
    world.connection.rules.insert(
        0, ("insert into lesion", FakeCheckViolation("lesion_volume_positive"), False)
    )

    with pytest.raises(InvalidLesionError):
        world.save()

    assert "db:rollback" in world.events
    assert world.database.committed == 1  # solo la comprobacion previa del estudio
    assert not world.connection.params_of("update processing_stage")


@pytest.mark.unit
def test_a_failed_upload_writes_nothing_to_the_database(world: World) -> None:
    world.bucket.fail_next("upload", StorageException("cuota excedida"), after=2)

    with pytest.raises(StorageError):
        world.save()

    assert not world.connection.params_of("insert into lesion")
    assert not world.connection.params_of("update processing_stage")
    assert world.database.committed == 1


@pytest.mark.unit
def test_save_result_returns_the_stored_result_with_paths_and_lesions(world: World) -> None:
    world.lesion_rows.append(
        {
            "location": "posicion 1",
            "volume_mm3": 8000.0,
            "max_diameter_mm": 26.5,
            "confidence": 0.89,
            "mesh_path": TUMOR_MESH,
        }
    )

    result = world.save()

    assert result == StoredResult(
        study_code=CODE,
        lesions=[Lesion("posicion 1", 8000.0, 0.89, 26.5, TUMOR_MESH)],
        mask_path=FILES[0],
        probability_path=FILES[1],
        summary_path=FILES[2],
        organ_mesh_path=FILES[3],
        tumor_mesh_path=FILES[4],
    )


# --- get_result (FR-049) ---


@pytest.mark.unit
def test_get_result_with_stages_three_and_four_completed_returns_paths_and_lesions(
    world: World,
) -> None:
    world.set_stage_rows(stage_rows(s3="completed", s4="completed"))
    world.lesion_rows.append(
        {
            "location": "centro",
            "volume_mm3": 10.0,
            "max_diameter_mm": None,
            "confidence": 0.7,
            "mesh_path": TUMOR_MESH,
        }
    )

    result = world.store.get_result(CODE)

    assert result.mask_path == FILES[0]
    assert result.probability_path == FILES[1]
    assert result.summary_path == FILES[2]
    assert result.organ_mesh_path == FILES[3]
    assert result.tumor_mesh_path == FILES[4]
    assert result.lesions == [Lesion("centro", 10.0, 0.7, None, TUMOR_MESH)]


@pytest.mark.unit
def test_a_result_with_no_lesions_still_has_its_five_paths(world: World) -> None:
    world.set_stage_rows(stage_rows(s3="completed", s4="completed"))

    result = world.store.get_result(CODE)

    assert result.lesions == []
    assert result.mask_path == FILES[0]
    assert result.tumor_mesh_path == FILES[4]


@pytest.mark.unit
def test_get_result_of_a_study_still_waiting_is_empty_and_does_not_raise(world: World) -> None:
    result = world.store.get_result(CODE)

    assert result == StoredResult(CODE)
    assert result.lesions == []
    assert result.mask_path is None
    assert result.probability_path is None
    assert result.summary_path is None
    assert result.organ_mesh_path is None
    assert result.tumor_mesh_path is None


@pytest.mark.unit
def test_get_result_with_only_stage_three_completed_is_also_empty(world: World) -> None:
    world.set_stage_rows(stage_rows(s3="completed"))

    assert world.store.get_result(CODE) == StoredResult(CODE)


@pytest.mark.unit
def test_get_result_after_a_failed_save_that_uploaded_files_is_still_empty(world: World) -> None:
    world.connection.rules.insert(
        0, ("insert into lesion", FakeCheckViolation("lesion_volume_positive"), False)
    )
    with pytest.raises(InvalidLesionError):
        world.save()
    assert sorted(world.bucket.files) == sorted(FILES)  # los archivos quedaron sueltos

    result = world.store.get_result(CODE)

    assert result == StoredResult(CODE)


@pytest.mark.unit
def test_get_result_of_a_study_without_result_never_calls_the_bucket(world: World) -> None:
    start = len(world.events)

    world.store.get_result(CODE)

    assert world.bucket_calls_since(start) == []


@pytest.mark.unit
def test_get_result_with_a_result_never_calls_the_bucket_either(world: World) -> None:
    world.set_stage_rows(stage_rows(s3="completed", s4="completed"))
    start = len(world.events)

    world.store.get_result(CODE)

    assert world.bucket_calls_since(start) == []


@pytest.mark.unit
def test_only_an_unknown_code_raises_not_found(world: World) -> None:
    world.connection.rules.clear()
    world.connection.when("select study_id from study where study_code", [])

    with pytest.raises(StudyNotFoundError):
        world.store.get_result("it_no_existe")


@pytest.mark.unit
def test_a_study_without_prepared_stages_gives_an_empty_result_not_an_error(world: World) -> None:
    world.set_stage_rows([])

    assert world.store.get_result(CODE) == StoredResult(CODE)


@pytest.mark.unit
def test_get_result_rejects_an_invalid_code_before_touching_anything(world: World) -> None:
    with pytest.raises(InvalidStudyIdError):
        world.store.get_result("a b")

    assert world.events == []
