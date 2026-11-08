"""Pruebas de la subida del DICOM y de la disponibilidad del modo de una radiografia."""

import pytest

from radvol3d import config
from radvol3d.domain.entities import Study
from radvol3d.domain.enums import InputMode, OrganName, StudyStatus
from radvol3d.domain.exceptions import InvalidRadiographError, InvalidStudyStateError
from tests.fixtures.radiograph_files import fake_dicom

CODE = "rx_001"


@pytest.fixture
def service(client):
    service = client.app.state.services.study_service
    service.add_radiograph.return_value = Study(
        CODE, OrganName.LUNG, StudyStatus.PENDING, input_mode=InputMode.RADIOGRAPH
    )
    return service


def dicom_form(content: bytes = None, name: str = "placa.dcm") -> dict:
    return {"file": (name, content if content is not None else fake_dicom(), "application/dicom")}


@pytest.mark.unit
def test_a_dicom_is_stored_and_its_size_confirmed(client, service) -> None:
    response = client.post(f"/studies/{CODE}/radiograph", files=dicom_form())

    assert response.status_code == 201
    assert response.json() == {"study_code": CODE, "size_bytes": len(fake_dicom())}
    service.add_radiograph.assert_called_once_with(CODE, fake_dicom(), "placa.dcm")


@pytest.mark.unit
def test_a_file_over_the_limit_is_rejected_with_413_without_storing(
    client, service, monkeypatch
) -> None:
    monkeypatch.setattr(config, "MAX_RADIOGRAPH_BYTES", 2000)

    response = client.post(f"/studies/{CODE}/radiograph", files=dicom_form(fake_dicom(2001)))

    assert response.status_code == 413
    assert "tamaño máximo" in response.json()["detail"]
    service.add_radiograph.assert_not_called()


@pytest.mark.unit
def test_a_file_that_is_not_dicom_is_a_validation_error(client, service) -> None:
    service.add_radiograph.side_effect = InvalidRadiographError("El archivo no es un DICOM.")

    response = client.post(f"/studies/{CODE}/radiograph", files=dicom_form(b"%PDF", "informe.pdf"))

    assert response.status_code == 422
    assert response.json() == {"detail": "El archivo no es un DICOM."}


@pytest.mark.unit
def test_a_study_that_already_has_its_radiograph_is_a_conflict(client, service) -> None:
    service.add_radiograph.side_effect = InvalidStudyStateError("ya tiene su radiografia")

    response = client.post(f"/studies/{CODE}/radiograph", files=dicom_form())

    assert response.status_code == 409


@pytest.mark.unit
def test_the_mode_is_reported_available_when_the_service_answers(client, service) -> None:
    service.radiograph_mode_available.return_value = True

    response = client.get("/radiograph-mode")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "message": None,
        "max_bytes": config.MAX_RADIOGRAPH_BYTES,
    }


@pytest.mark.unit
def test_the_mode_is_reported_unavailable_with_a_clear_message(client, service) -> None:
    service.radiograph_mode_available.return_value = False

    body = client.get("/radiograph-mode").json()

    assert body["available"] is False
    assert body["message"] == "El modo de una radiografía no está disponible en este momento."
