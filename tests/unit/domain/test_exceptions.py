"""Comprueba la jerarquia de los errores nuevos del dominio."""

import pytest

from radvol3d.domain import exceptions
from radvol3d.domain.exceptions import RadVol3DError, StorageError

NEW_ERRORS = [
    "ConfigurationError",
    "DuplicateStudyError",
    "InvalidPatientDataError",
    "PatientCodeExhaustedError",
    "UnknownOrganError",
    "InvalidLesionError",
    "PersistenceError",
]


@pytest.mark.unit
@pytest.mark.parametrize("name", NEW_ERRORS)
def test_new_errors_inherit_from_the_root_error(name: str) -> None:
    error_type = getattr(exceptions, name)

    assert issubclass(error_type, RadVol3DError)


@pytest.mark.unit
def test_object_not_found_is_a_storage_error() -> None:
    assert issubclass(exceptions.StorageObjectNotFoundError, StorageError)
    assert issubclass(exceptions.StorageObjectNotFoundError, RadVol3DError)


@pytest.mark.unit
@pytest.mark.parametrize("name", [*NEW_ERRORS, "StorageObjectNotFoundError"])
def test_new_errors_carry_a_spanish_message(name: str) -> None:
    error = getattr(exceptions, name)("Mensaje en espanol")

    assert str(error) == "Mensaje en espanol"
