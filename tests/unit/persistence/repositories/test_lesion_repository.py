"""Pruebas del repositorio de lesiones (FR-041 a FR-043)."""

from decimal import Decimal

import pytest

from radvol3d.domain.entities import Lesion
from radvol3d.domain.exceptions import (
    InvalidLesionError,
    InvalidStudyIdError,
    StudyNotFoundError,
)
from radvol3d.persistence.repositories.lesion_repository import LesionRepository
from tests.fixtures.fake_database import FakeCheckViolation, FakeConnection

STUDY_LOOKUP = [{"study_id": 7}]
MESH = "it_a/meshes/tumor.glb"


def make_lesion(**overrides) -> Lesion:
    values = {
        "location": "centro del lobulo",
        "volume_mm3": 8000.0,
        "confidence": 0.9,
        "max_diameter_mm": 25.5,
        "mesh_path": MESH,
    }
    values.update(overrides)
    return Lesion(**values)


@pytest.mark.unit
def test_add_many_stores_every_field_of_every_lesion() -> None:
    connection = FakeConnection([STUDY_LOOKUP])
    lesions = [make_lesion(), make_lesion(location="borde", volume_mm3=120.5, confidence=0.61)]

    LesionRepository(connection).add_many("it_a", lesions)

    assert connection.params_of("insert into lesion") == [
        (7, "centro del lobulo", 8000.0, 25.5, 0.9, MESH),
        (7, "borde", 120.5, 25.5, 0.61, MESH),
    ]


@pytest.mark.unit
def test_a_lesion_without_diameter_is_accepted_and_stays_empty() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    LesionRepository(connection).add_many("it_a", [make_lesion(max_diameter_mm=None)])

    assert connection.params_of("insert into lesion")[0][3] is None


@pytest.mark.unit
def test_a_lesion_without_mesh_path_is_accepted() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    LesionRepository(connection).add_many("it_a", [make_lesion(mesh_path=None)])

    assert connection.params_of("insert into lesion")[0][5] is None


@pytest.mark.unit
@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_the_confidence_bounds_are_accepted(confidence: float) -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    LesionRepository(connection).add_many("it_a", [make_lesion(confidence=confidence)])

    assert connection.params_of("insert into lesion")[0][4] == confidence


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        {"volume_mm3": 0.0},
        {"volume_mm3": -1.0},
        {"volume_mm3": float("nan")},
        {"confidence": -0.01},
        {"confidence": 1.01},
        {"confidence": float("nan")},
        {"location": ""},
        {"location": "   "},
        {"location": "x" * 129},
    ],
)
def test_an_invalid_lesion_rejects_the_whole_batch_before_touching_the_database(bad: dict) -> None:
    connection = FakeConnection([STUDY_LOOKUP])
    batch = [make_lesion(), make_lesion(**bad), make_lesion()]

    with pytest.raises(InvalidLesionError):
        LesionRepository(connection).add_many("it_a", batch)

    assert connection.calls == []


@pytest.mark.unit
def test_a_location_of_128_characters_is_accepted() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    LesionRepository(connection).add_many("it_a", [make_lesion(location="x" * 128)])

    assert len(connection.params_of("insert into lesion")) == 1


@pytest.mark.unit
@pytest.mark.parametrize("constraint", ["lesion_volume_positive", "lesion_confidence_range"])
def test_the_database_constraints_are_translated_as_a_backstop(constraint: str) -> None:
    connection = FakeConnection([STUDY_LOOKUP, FakeCheckViolation(constraint)])

    with pytest.raises(InvalidLesionError) as raised:
        LesionRepository(connection).add_many("it_a", [make_lesion()])

    assert raised.value.__cause__ is None


@pytest.mark.unit
def test_add_many_raises_not_found_for_an_unknown_study() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(StudyNotFoundError):
        LesionRepository(connection).add_many("it_a", [make_lesion()])

    assert not connection.params_of("insert into lesion")


@pytest.mark.unit
def test_add_many_with_no_lesions_does_nothing() -> None:
    connection = FakeConnection()

    LesionRepository(connection).add_many("it_a", [])

    assert connection.calls == []


@pytest.mark.unit
def test_add_many_rejects_an_invalid_study_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        LesionRepository(connection).add_many("a b", [make_lesion()])

    assert connection.calls == []


@pytest.mark.unit
def test_list_by_study_returns_the_same_values_that_were_stored() -> None:
    connection = FakeConnection(
        [
            [
                {
                    "location": "centro del lobulo",
                    "volume_mm3": Decimal("8000.00"),
                    "max_diameter_mm": Decimal("25.50"),
                    "confidence": Decimal("0.9000"),
                    "mesh_path": MESH,
                },
                {
                    "location": "borde",
                    "volume_mm3": Decimal("120.50"),
                    "max_diameter_mm": None,
                    "confidence": Decimal("0.6100"),
                    "mesh_path": None,
                },
            ]
        ]
    )

    lesions = LesionRepository(connection).list_by_study("it_a")

    assert lesions == [
        make_lesion(),
        make_lesion(location="borde", volume_mm3=120.5, confidence=0.61,
                    max_diameter_mm=None, mesh_path=None),
    ]
    assert all(isinstance(lesion.volume_mm3, float) for lesion in lesions)
    assert all(isinstance(lesion.confidence, float) for lesion in lesions)
    assert "order by l.lesion_id" in connection.statements()[0]
    assert connection.params_of("from lesion l") == [("it_a",)]


@pytest.mark.unit
def test_list_by_study_returns_an_empty_list_when_there_are_no_lesions() -> None:
    assert LesionRepository(FakeConnection([[]])).list_by_study("it_a") == []


@pytest.mark.unit
def test_list_by_study_rejects_an_invalid_study_code() -> None:
    with pytest.raises(InvalidStudyIdError):
        LesionRepository(FakeConnection()).list_by_study("..")


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        {"volume_mm3": "mucho"},
        {"confidence": "alta"},
        {"max_diameter_mm": "grande"},
        {"volume_mm3": True},
        {"volume_mm3": None},
    ],
)
def test_values_that_are_not_numbers_are_rejected_as_invalid_lesions(bad: dict) -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    with pytest.raises(InvalidLesionError):
        LesionRepository(connection).add_many("it_a", [make_lesion(**bad)])

    assert connection.calls == []
