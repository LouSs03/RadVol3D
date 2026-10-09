"""Comprueba la traduccion de los errores del dominio a codigos HTTP."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radvol3d.api.error_handlers import register_error_handlers
from radvol3d.domain import exceptions as domain_errors
from radvol3d.domain.enums import StageNumber
from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidStudyStateError,
    StageFailedError,
    StudyInProgressError,
)


def app_raising(error: Exception) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/falla")
    def fail() -> None:
        raise error

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
def test_a_failed_stage_is_a_server_error_with_its_spanish_message() -> None:
    client = app_raising(StageFailedError("it_a", StageNumber.SEGMENTATION))

    response = client.get("/falla")

    assert response.status_code == 500
    assert response.json() == {"detail": "La etapa 3 (segmentation) del estudio it_a falló."}


@pytest.mark.unit
def test_deleting_a_study_in_progress_is_a_conflict() -> None:
    client = app_raising(StudyInProgressError("El estudio it_a se esta procesando."))

    response = client.get("/falla")

    assert response.status_code == 409
    assert response.json() == {"detail": "El estudio it_a se esta procesando."}


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        DuplicateStudyError("Ya existe el estudio it_a."),
        InvalidStudyStateError("El estudio it_a esta en processing."),
    ],
)
def test_a_duplicate_or_a_wrong_state_is_a_conflict(error: Exception) -> None:
    client = app_raising(error)

    response = client.get("/falla")

    assert response.status_code == 409
    assert response.json() == {"detail": str(error)}


# ---------------------------------------------------------------------------
# Tabla completa de research.md R8 (funcionalidad 004, historia 2)
# ---------------------------------------------------------------------------


STATUS_TABLE = {
    "StudyNotFoundError": 404,
    "StorageObjectNotFoundError": 404,
    "InvalidStudyIdError": 400,
    "InvalidProjectionError": 422,
    "InvalidPatientDataError": 422,
    "UnknownOrganError": 422,
    "DuplicateStudyError": 409,
    "StudyInProgressError": 409,
    "InvalidStudyStateError": 409,
    "ModelNotAvailableError": 503,
    "DatabaseUnavailableError": 503,
    "StorageError": 500,
    "PersistenceError": 500,
    "InvalidLesionError": 500,
    "PatientCodeExhaustedError": 500,
}


@pytest.mark.unit
@pytest.mark.parametrize(("name", "code"), sorted(STATUS_TABLE.items()))
def test_each_domain_error_has_its_http_code_and_its_message(name: str, code: int) -> None:
    error = getattr(domain_errors, name)(f"Mensaje de {name}.")
    client = app_raising(error)

    response = client.get("/falla")

    assert response.status_code == code
    assert response.json() == {"detail": f"Mensaje de {name}."}


@pytest.mark.unit
def test_an_unexpected_error_is_a_generic_server_error_without_its_text(caplog) -> None:
    client = app_raising(RuntimeError("detalle interno con una-clave"))

    with caplog.at_level("ERROR"):
        response = client.get("/falla")

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor."}
    assert "detalle interno" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" in caplog.text
    assert "una-clave" not in caplog.text
