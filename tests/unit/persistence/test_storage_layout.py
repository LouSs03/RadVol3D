"""Pruebas de las rutas de los archivos dentro del bucket."""

import ast
from pathlib import Path

import pytest

from radvol3d.domain.exceptions import (
    InvalidLesionError,
    InvalidProjectionError,
    InvalidStudyIdError,
)
from radvol3d.persistence import storage_layout
from radvol3d.persistence.storage_layout import (
    mask_path,
    organ_mesh_path,
    probability_path,
    projection_path,
    summary_path,
    tumor_mesh_path,
    validate_projection_angle,
    validate_study_code,
    volume_path,
)

CODE = "it_estudio-01"

INVALID_CODES = [
    "",
    "..",
    "a..b",
    "../otro",
    "a/b",
    "a\\b",
    "con espacio",
    "tilde-á",
    "salto\n",
    "x" * 65,
]

SINGLE_FILE_PATHS = [
    (volume_path, "volume.npy"),
    (mask_path, "segmentation/mask.npy"),
    (probability_path, "segmentation/probability.npy"),
    (summary_path, "segmentation/summary.json"),
    (organ_mesh_path, "meshes/organ.glb"),
    (tumor_mesh_path, "meshes/tumor.glb"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("angle", "file_name"),
    [(0, "angle_000.npy"), (45, "angle_045.npy"), (90, "angle_090.npy"), (135, "angle_135.npy")],
)
def test_projection_paths_use_a_three_digit_angle(angle: int, file_name: str) -> None:
    assert projection_path(CODE, angle) == f"{CODE}/projections/{file_name}"


@pytest.mark.unit
@pytest.mark.parametrize(("build_path", "suffix"), SINGLE_FILE_PATHS)
def test_each_file_lives_under_the_study_code(build_path, suffix: str) -> None:
    assert build_path(CODE) == f"{CODE}/{suffix}"


@pytest.mark.unit
def test_the_same_input_always_gives_the_same_path() -> None:
    assert projection_path(CODE, 90) == projection_path(CODE, 90)
    assert tumor_mesh_path(CODE) == tumor_mesh_path(CODE)


@pytest.mark.unit
def test_a_code_of_64_valid_characters_is_accepted() -> None:
    code = "A" * 32 + "_" * 16 + "-" * 8 + "9" * 8

    assert validate_study_code(code) == code


@pytest.mark.unit
@pytest.mark.parametrize("code", INVALID_CODES)
def test_an_invalid_study_code_is_rejected(code: str) -> None:
    with pytest.raises(InvalidStudyIdError):
        validate_study_code(code)


@pytest.mark.unit
@pytest.mark.parametrize("code", INVALID_CODES)
def test_every_path_function_rejects_an_invalid_study_code(code: str) -> None:
    for build_path, _ in SINGLE_FILE_PATHS:
        with pytest.raises(InvalidStudyIdError):
            build_path(code)
    with pytest.raises(InvalidStudyIdError):
        projection_path(code, 0)


@pytest.mark.unit
@pytest.mark.parametrize("angle", [-45, 1, 30, 180, 360, 45.0, True, "45", None])
def test_an_angle_outside_the_allowed_set_is_rejected(angle) -> None:
    with pytest.raises(InvalidProjectionError):
        projection_path(CODE, angle)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("number", "file_name"), [(1, "lesion_001.glb"), (12, "lesion_012.glb"), (999, "lesion_999.glb")]
)
def test_each_lesion_mesh_has_a_three_digit_number(number: int, file_name: str) -> None:
    assert storage_layout.lesion_mesh_path("lung_028", number) == f"lung_028/meshes/{file_name}"


@pytest.mark.unit
@pytest.mark.parametrize("number", [0, -1, True, "1", 1.0, None])
def test_a_lesion_number_that_is_not_a_positive_integer_is_rejected(number) -> None:
    with pytest.raises(InvalidLesionError):
        storage_layout.lesion_mesh_path(CODE, number)


@pytest.mark.unit
def test_a_lesion_mesh_path_rejects_an_invalid_study_code() -> None:
    with pytest.raises(InvalidStudyIdError):
        storage_layout.lesion_mesh_path("../otro", 1)


@pytest.mark.unit
def test_the_module_never_touches_the_database_or_the_bucket() -> None:
    source = Path(storage_layout.__file__).read_text(encoding="utf-8")
    imported_roots = {
        (alias.name if isinstance(node, ast.Import) else node.module or "").split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [node])
    }

    assert not imported_roots & {"psycopg", "psycopg_pool", "supabase", "storage3", "numpy"}


@pytest.mark.unit
@pytest.mark.parametrize("angle", [0, 45, 90, 135])
def test_validate_projection_angle_returns_an_allowed_angle(angle: int) -> None:
    assert validate_projection_angle(angle) == angle


@pytest.mark.unit
@pytest.mark.parametrize("angle", [-45, 30, 45.0, True, "45", None])
def test_validate_projection_angle_rejects_anything_else(angle) -> None:
    with pytest.raises(InvalidProjectionError):
        validate_projection_angle(angle)
