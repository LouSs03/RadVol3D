"""Pruebas del repositorio de organos (FR-026). Es de solo lectura."""

import pytest

from radvol3d.domain.entities import Organ
from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import UnknownOrganError
from radvol3d.persistence.repositories.organ_repository import OrganRepository
from tests.fixtures.fake_database import FakeConnection

LUNG_ROW = {"organ_id": 1, "name": "lung", "anatomical_region": "thorax"}
LIVER_ROW = {"organ_id": 2, "name": "liver", "anatomical_region": "upper abdomen"}


@pytest.mark.unit
def test_list_all_returns_lung_and_liver_as_organ_entities() -> None:
    connection = FakeConnection([[LUNG_ROW, LIVER_ROW]])

    organs = OrganRepository(connection).list_all()

    assert organs == [
        Organ(1, OrganName.LUNG, "thorax"),
        Organ(2, OrganName.LIVER, "upper abdomen"),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("name", [OrganName.LUNG, "lung"])
def test_get_by_name_accepts_the_enum_or_the_text(name: OrganName | str) -> None:
    connection = FakeConnection([[LUNG_ROW]])

    organ = OrganRepository(connection).get_by_name(name)

    assert organ == Organ(1, OrganName.LUNG, "thorax")
    assert connection.params_of("from organ") == [("lung",)]


@pytest.mark.unit
def test_an_organ_outside_the_scope_is_rejected_without_touching_the_database() -> None:
    connection = FakeConnection()

    with pytest.raises(UnknownOrganError):
        OrganRepository(connection).get_by_name("heart")

    assert connection.calls == []


@pytest.mark.unit
def test_an_organ_missing_from_the_table_is_unknown() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(UnknownOrganError):
        OrganRepository(connection).get_by_name(OrganName.LIVER)


@pytest.mark.unit
def test_the_repository_has_no_write_methods() -> None:
    public = {name for name in dir(OrganRepository) if not name.startswith("_")}

    assert public == {"list_all", "get_by_name"}
