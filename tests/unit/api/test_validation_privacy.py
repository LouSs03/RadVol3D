"""Ninguna respuesta ni registro devuelve datos del paciente (FR-029, SC-005).

El 422 de FastAPI trae el campo input con el valor recibido: con un DNI mal escrito,
lo devolveria tal cual. Estas pruebas exigen el 422 propio, sin input.
"""

import pytest

from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidPatientDataError,
    ModelNotAvailableError,
)

FIRST_NAME = "Rosaura"
LAST_NAME = "Quispecahuana"
NATIONAL_ID = "87654321"


def body(**patient) -> dict:
    return {"study_code": "it_privado", "organ": "lung", "patient": patient}


@pytest.mark.unit
def test_an_invalid_national_id_is_rejected_without_echoing_it(client) -> None:
    response = client.post("/studies", json=body(national_id="1234567X"))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    for item in detail:
        assert set(item) == {"loc", "msg", "type"}
    assert "1234567X" not in response.text


@pytest.mark.unit
def test_a_name_too_long_is_rejected_without_echoing_it(client) -> None:
    long_name = "Maximiliana" * 8  # 88 caracteres

    response = client.post("/studies", json=body(first_name=long_name))

    assert response.status_code == 422
    assert long_name not in response.text
    assert "input" not in response.json()["detail"][0]


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        DuplicateStudyError("Ya existe el estudio 'it_privado'."),
        InvalidPatientDataError("Los datos del paciente no cumplen el formato."),
        ModelNotAvailableError("No hay modelo de segmentacion para liver."),
        RuntimeError(f"fallo con {FIRST_NAME} {LAST_NAME} {NATIONAL_ID}"),
    ],
)
def test_no_error_response_or_log_has_the_patient_data_that_was_sent(
    client, caplog, error: Exception
) -> None:
    client.app.state.services.study_service.create_study.side_effect = error

    with caplog.at_level("DEBUG"):
        response = client.post(
            "/studies",
            json=body(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID),
        )

    assert response.status_code >= 400
    for value in (FIRST_NAME, LAST_NAME, NATIONAL_ID):
        assert value not in response.text
        assert value not in caplog.text
