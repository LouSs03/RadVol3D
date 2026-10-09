"""Escenarios 1 a 6 de la historia 2: cada pedido invalido con su codigo y su mensaje.

El servicio doble lanza el error del dominio de cada caso; aqui se comprueba la
traduccion de punta a punta por las rutas reales.
"""

import pytest

from radvol3d.domain.exceptions import (
    DuplicateStudyError,
    InvalidProjectionError,
    InvalidStudyIdError,
    InvalidStudyStateError,
    ModelNotAvailableError,
    StudyNotFoundError,
)
from tests.fixtures.projection_files import png_bytes, valid_npy

CODE = "lung_028"
FIELDS = {0: "angle_000", 45: "angle_045", 90: "angle_090", 135: "angle_135"}


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


def files(**replacements: bytes) -> dict:
    payload = {
        field: (f"{field}.npy", valid_npy(angle), "application/octet-stream")
        for angle, field in FIELDS.items()
    }
    for field, content in replacements.items():
        payload[field] = (f"{field}.npy", content, "application/octet-stream")
    return payload


@pytest.mark.unit
def test_a_repeated_code_is_a_conflict(client, service) -> None:
    service.create_study.side_effect = DuplicateStudyError(f"Ya existe el estudio '{CODE}'.")

    response = client.post("/studies", json={"study_code": CODE, "organ": "lung"})

    assert response.status_code == 409
    assert response.json() == {"detail": f"Ya existe el estudio '{CODE}'."}


@pytest.mark.unit
def test_a_code_with_forbidden_characters_in_the_body_is_invalid_input(client, service) -> None:
    response = client.post("/studies", json={"study_code": "con espacio", "organ": "lung"})

    assert response.status_code == 422
    service.create_study.assert_not_called()


@pytest.mark.unit
def test_a_code_with_forbidden_characters_in_the_path_is_a_bad_request(client, service) -> None:
    service.get_study.side_effect = InvalidStudyIdError(
        "El codigo del estudio solo admite letras, digitos, guion y guion bajo (hasta 64)."
    )

    response = client.get("/studies/con%20espacio/status")

    assert response.status_code == 400


@pytest.mark.unit
def test_an_organ_outside_the_scope_is_invalid_input(client, service) -> None:
    response = client.post("/studies", json={"study_code": CODE, "organ": "kidney"})

    assert response.status_code == 422
    service.create_study.assert_not_called()


@pytest.mark.unit
def test_liver_is_unavailable_with_the_message_of_the_service(client, service) -> None:
    message = "No hay modelo de segmentacion de higado (liver) todavia."
    service.create_study.side_effect = ModelNotAvailableError(message)

    response = client.post("/studies", json={"study_code": CODE, "organ": "liver"})

    assert response.status_code == 503
    assert response.json() == {"detail": message}


@pytest.mark.unit
def test_an_invalid_projection_is_invalid_input_naming_the_angle(client, service) -> None:
    message = "La proyeccion de 45 grados no es un .npy: solo se acepta .npy en el convenio de TA-2."
    service.add_projections.side_effect = InvalidProjectionError(message)

    response = client.post(f"/studies/{CODE}/projections", files=files(angle_045=png_bytes()))

    assert response.status_code == 422
    assert "45" in response.json()["detail"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        f"El estudio '{CODE}' tiene 0 de 4 proyecciones: sube las cuatro antes de procesarlo.",
        f"El estudio '{CODE}' esta en completed: solo se procesa un estudio en pending.",
    ],
)
def test_processing_a_study_that_is_not_ready_is_a_conflict(client, service, message) -> None:
    service.start_processing.side_effect = InvalidStudyStateError(message)

    response = client.post(f"/studies/{CODE}/process")

    assert response.status_code == 409
    assert response.json() == {"detail": message}
    service.run_processing.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("get", f"/studies/{CODE}/status", "get_study"),
        ("post", f"/studies/{CODE}/process", "start_processing"),
        ("post", f"/studies/{CODE}/projections", "add_projections"),
    ],
)
def test_an_unknown_study_is_not_found_on_every_route(
    client, service, method: str, path: str, operation: str
) -> None:
    getattr(service, operation).side_effect = StudyNotFoundError(f"No existe el estudio '{CODE}'.")
    kwargs = {"files": files()} if operation == "add_projections" else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": f"No existe el estudio '{CODE}'."}
