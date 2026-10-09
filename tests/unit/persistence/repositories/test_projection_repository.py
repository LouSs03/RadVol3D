"""Pruebas del repositorio de proyecciones (FR-035 a FR-037)."""

import pytest

from radvol3d.domain.entities import Projection
from radvol3d.domain.exceptions import (
    InvalidProjectionError,
    InvalidStudyIdError,
    StudyNotFoundError,
)
from radvol3d.persistence.repositories.projection_repository import ProjectionRepository
from tests.fixtures.fake_database import FakeConnection, FakeUniqueViolation

STUDY_LOOKUP = [{"study_id": 7}]


def four_projections() -> list[Projection]:
    return [
        Projection(0, "it_a/projections/angle_000.npy", "frente.npy"),
        Projection(45, "it_a/projections/angle_045.npy"),
        Projection(90, "it_a/projections/angle_090.npy", "lado.npy"),
        Projection(135, "it_a/projections/angle_135.npy"),
    ]


@pytest.mark.unit
def test_add_many_stores_angle_path_and_original_name_for_each_projection() -> None:
    connection = FakeConnection([STUDY_LOOKUP])

    ProjectionRepository(connection).add_many("it_a", four_projections())

    assert connection.params_of("insert into projection") == [
        (7, 0, "it_a/projections/angle_000.npy", "frente.npy"),
        (7, 45, "it_a/projections/angle_045.npy", None),
        (7, 90, "it_a/projections/angle_090.npy", "lado.npy"),
        (7, 135, "it_a/projections/angle_135.npy", None),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("angle", [30, 180, -45, 360])
def test_an_angle_outside_the_allowed_set_is_rejected_before_touching_the_database(
    angle: int,
) -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidProjectionError):
        ProjectionRepository(connection).add_many("it_a", [Projection(angle, "it_a/x.npy")])

    assert connection.calls == []


@pytest.mark.unit
def test_a_repeated_angle_in_the_batch_is_rejected_before_touching_the_database() -> None:
    connection = FakeConnection()
    repeated = [Projection(0, "it_a/a.npy"), Projection(0, "it_a/b.npy")]

    with pytest.raises(InvalidProjectionError):
        ProjectionRepository(connection).add_many("it_a", repeated)

    assert connection.calls == []


@pytest.mark.unit
def test_the_unique_constraint_on_study_and_angle_is_translated() -> None:
    connection = FakeConnection([STUDY_LOOKUP, FakeUniqueViolation("projection_study_angle_unique")])

    with pytest.raises(InvalidProjectionError):
        ProjectionRepository(connection).add_many("it_a", [Projection(0, "it_a/a.npy")])


@pytest.mark.unit
def test_add_many_raises_not_found_for_an_unknown_study() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(StudyNotFoundError):
        ProjectionRepository(connection).add_many("it_a", four_projections())


@pytest.mark.unit
def test_add_many_rejects_an_invalid_study_code() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        ProjectionRepository(connection).add_many("a/b", four_projections())

    assert connection.calls == []


@pytest.mark.unit
def test_list_by_study_returns_projections_ordered_by_angle() -> None:
    connection = FakeConnection(
        [
            [
                {"angle_degrees": 0, "file_path": "it_a/projections/angle_000.npy",
                 "original_name": "frente.npy"},
                {"angle_degrees": 45, "file_path": "it_a/projections/angle_045.npy",
                 "original_name": None},
            ]
        ]
    )

    projections = ProjectionRepository(connection).list_by_study("it_a")

    assert projections == [
        Projection(0, "it_a/projections/angle_000.npy", "frente.npy"),
        Projection(45, "it_a/projections/angle_045.npy", None),
    ]
    assert "order by p.angle_degrees" in connection.statements()[0]
    assert connection.params_of("from projection p") == [("it_a",)]


@pytest.mark.unit
def test_list_by_study_returns_an_empty_list_when_there_are_no_projections() -> None:
    assert ProjectionRepository(FakeConnection([[]])).list_by_study("it_a") == []


@pytest.mark.unit
def test_list_by_study_rejects_an_invalid_study_code() -> None:
    with pytest.raises(InvalidStudyIdError):
        ProjectionRepository(FakeConnection()).list_by_study("..")


@pytest.mark.unit
def test_count_by_study_returns_how_many_projections_the_study_has_in_one_query() -> None:
    connection = FakeConnection([[{"projection_count": 3}]])

    assert ProjectionRepository(connection).count_by_study("it_a") == 3
    # Una sola consulta: cada ida a la base cuesta (research.md R4 de 004, SC-002).
    assert len(connection.calls) == 1
    assert connection.params_of("projection_count") == [("it_a",)]


@pytest.mark.unit
def test_count_by_study_of_an_unknown_study_is_not_found() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(StudyNotFoundError):
        ProjectionRepository(connection).count_by_study("it_x")


@pytest.mark.unit
def test_count_by_study_rejects_an_invalid_code_before_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(InvalidStudyIdError):
        ProjectionRepository(connection).count_by_study("../otro")

    assert connection.calls == []
