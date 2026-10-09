"""Comprueba la jerarquia de los errores nuevos del dominio."""

import pytest

from radvol3d.domain import exceptions
from radvol3d.domain.enums import StageNumber
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


# ---------------------------------------------------------------------------
# Errores de la capa de servicios (funcionalidad 002).
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("name", ["StageFailedError", "StudyInProgressError"])
def test_service_errors_inherit_from_the_root_error(name: str) -> None:
    assert issubclass(getattr(exceptions, name), RadVol3DError)


@pytest.mark.unit
def test_stage_failed_error_names_the_stage_and_the_study() -> None:
    error = exceptions.StageFailedError(
        study_code="it_a", stage_number=StageNumber.SEGMENTATION
    )

    assert error.study_code == "it_a"
    assert error.stage_number is StageNumber.SEGMENTATION
    assert str(error) == "La etapa 3 (segmentation) del estudio it_a falló."


@pytest.mark.unit
def test_stage_failed_error_does_not_repeat_the_text_of_its_cause() -> None:
    try:
        try:
            raise RuntimeError("detalle interno")
        except RuntimeError as cause:
            raise exceptions.StageFailedError("it_a", StageNumber.MESHING) from cause
    except exceptions.StageFailedError as error:
        assert "detalle interno" not in str(error)
        assert "detalle interno" not in repr(error)
        assert isinstance(error.__cause__, RuntimeError)


@pytest.mark.unit
def test_study_in_progress_error_carries_a_spanish_message() -> None:
    error = exceptions.StudyInProgressError("El estudio it_a se esta procesando.")

    assert str(error) == "El estudio it_a se esta procesando."
