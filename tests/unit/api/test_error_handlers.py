"""Comprueba la traduccion de los errores del dominio a codigos HTTP."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radvol3d.api.error_handlers import register_error_handlers
from radvol3d.domain.enums import StageNumber
from radvol3d.domain.exceptions import StageFailedError, StudyInProgressError


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
    assert response.json() == {"detalle": "La etapa 3 (segmentation) del estudio it_a falló."}


@pytest.mark.unit
def test_deleting_a_study_in_progress_is_a_conflict() -> None:
    client = app_raising(StudyInProgressError("El estudio it_a se esta procesando."))

    response = client.get("/falla")

    assert response.status_code == 409
    assert response.json() == {"detalle": "El estudio it_a se esta procesando."}
