"""Pruebas del repositorio de modelos (FR-027 a FR-029)."""

from datetime import date

import pytest

from radvol3d.domain.entities import Model
from radvol3d.domain.exceptions import PersistenceError
from radvol3d.persistence.repositories.model_repository import ModelRepository
from tests.fixtures.fake_database import FakeConnection, FakeUniqueViolation

TRAINED_ON = date(2026, 1, 2)


def model_row(**overrides) -> dict:
    row = {
        "model_name": "reconstruction_en1",
        "version": "1.0.0",
        "trained_on": None,
        "description": None,
    }
    row.update(overrides)
    return row


@pytest.mark.unit
def test_a_new_pair_is_inserted_and_returned() -> None:
    connection = FakeConnection([[model_row()]])

    model = ModelRepository(connection).get_or_create("reconstruction_en1", "1.0.0")

    assert model == Model("reconstruction_en1", "1.0.0")
    assert len(connection.calls) == 1


@pytest.mark.unit
def test_the_insert_uses_on_conflict_so_the_pair_is_never_duplicated() -> None:
    connection = FakeConnection([[model_row()]])

    ModelRepository(connection).get_or_create("reconstruction_en1", "1.0.0")

    statement = connection.statements()[0]
    assert "insert into model" in statement
    assert "on conflict (model_name, version) do nothing" in statement
    assert "returning" in statement


@pytest.mark.unit
def test_registering_the_same_pair_twice_returns_the_same_model() -> None:
    connection = FakeConnection(
        [
            [model_row()],  # primera vez: el insert devuelve la fila nueva
            [],  # segunda vez: el insert choca y no devuelve nada
            [model_row()],  # ... y se lee la fila existente
        ]
    )
    repository = ModelRepository(connection)

    first = repository.get_or_create("reconstruction_en1", "1.0.0")
    second = repository.get_or_create("reconstruction_en1", "1.0.0")

    assert first == second
    selects = [s for s in connection.statements() if s.startswith("select")]
    assert len(selects) == 1
    assert connection.params_of("from model") == [("reconstruction_en1", "1.0.0")]


@pytest.mark.unit
def test_an_existing_model_is_returned_as_it_was_without_overwriting_it() -> None:
    existing = model_row(trained_on=TRAINED_ON, description="Descripcion original")
    connection = FakeConnection([[], [existing]])

    model = ModelRepository(connection).get_or_create(
        "reconstruction_en1", "1.0.0", description="Otra descripcion"
    )

    assert model.description == "Descripcion original"
    assert model.trained_on == TRAINED_ON
    assert not [s for s in connection.statements() if s.startswith("update")]


@pytest.mark.unit
def test_optional_data_is_stored_only_when_it_arrives() -> None:
    connection = FakeConnection([[model_row()], [model_row()]])
    repository = ModelRepository(connection)

    repository.get_or_create("reconstruction_en1", "1.0.0")
    repository.get_or_create(
        "reconstruction_en1", "1.0.0", trained_on=TRAINED_ON, description="Red EN-1"
    )

    assert connection.params_of("insert into model") == [
        ("reconstruction_en1", "1.0.0", None, None),
        ("reconstruction_en1", "1.0.0", TRAINED_ON, "Red EN-1"),
    ]


@pytest.mark.unit
def test_get_returns_the_model_or_none() -> None:
    connection = FakeConnection([[model_row(trained_on=TRAINED_ON)], []])
    repository = ModelRepository(connection)

    found = repository.get("reconstruction_en1", "1.0.0")
    missing = repository.get("reconstruction_en1", "9.9.9")

    assert found == Model("reconstruction_en1", "1.0.0", TRAINED_ON)
    assert missing is None
    assert connection.params_of("from model") == [
        ("reconstruction_en1", "1.0.0"),
        ("reconstruction_en1", "9.9.9"),
    ]


@pytest.mark.unit
def test_a_model_that_vanishes_between_the_insert_and_the_read_is_an_error() -> None:
    connection = FakeConnection([[], []])

    with pytest.raises(PersistenceError):
        ModelRepository(connection).get_or_create("reconstruction_en1", "1.0.0")


@pytest.mark.unit
def test_database_errors_are_translated() -> None:
    connection = FakeConnection([FakeUniqueViolation("model_name_version_unique")])

    with pytest.raises(PersistenceError) as raised:
        ModelRepository(connection).get_or_create("reconstruction_en1", "1.0.0")

    assert raised.value.__cause__ is None
