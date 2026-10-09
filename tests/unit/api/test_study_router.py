"""Pruebas de las rutas de estudios con el servicio simulado (contracts/http_api.md)."""

from datetime import UTC, datetime

import pytest

from radvol3d.domain.entities import Patient, PatientDetails, ProcessingStage, Study
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import InvalidStudyStateError

CODE = "lung_028"
CREATED_AT = datetime(2026, 10, 9, 15, 4, 5, tzinfo=UTC)
FIRST_NAME = "Rosa"
LAST_NAME = "Quispe"
NATIONAL_ID = "12345678"


def study(status: StudyStatus = StudyStatus.PENDING, **overrides) -> Study:
    values = {
        "study_code": CODE,
        "organ": OrganName.LUNG,
        "status": status,
        "created_at": CREATED_AT,
        "patient": Patient("PAC000001", FIRST_NAME, LAST_NAME, NATIONAL_ID),
        "stages": [
            ProcessingStage(StageNumber.PREPROCESSING, StageStatus.COMPLETED, CREATED_AT, CREATED_AT),
            ProcessingStage(StageNumber.RECONSTRUCTION, StageStatus.RUNNING, CREATED_AT),
            ProcessingStage(StageNumber.SEGMENTATION, StageStatus.WAITING),
            ProcessingStage(StageNumber.MESHING, StageStatus.WAITING),
        ],
    }
    values.update(overrides)
    return Study(**values)


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


def assert_no_personal_data(text: str) -> None:
    for value in (FIRST_NAME, LAST_NAME, NATIONAL_ID):
        assert value not in text


@pytest.mark.unit
def test_creating_a_study_answers_201_with_its_location(client, service) -> None:
    service.create_study.return_value = study()

    response = client.post(
        "/studies",
        json={
            "study_code": CODE,
            "organ": "lung",
            "patient": {
                "first_name": FIRST_NAME,
                "last_name": LAST_NAME,
                "national_id": NATIONAL_ID,
            },
        },
    )

    assert response.status_code == 201
    assert response.headers["location"] == f"/studies/{CODE}/status"
    assert response.json() == {
        "study_code": CODE,
        "organ": "lung",
        "status": "pending",
        "created_at": "2026-10-09T15:04:05Z",
        "patient_code": "PAC000001",
    }
    service.create_study.assert_called_once_with(
        CODE,
        OrganName.LUNG,
        PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID),
    )
    assert_no_personal_data(response.text)


@pytest.mark.unit
def test_creating_a_study_without_patient_passes_none(client, service) -> None:
    service.create_study.return_value = study()

    client.post("/studies", json={"study_code": CODE, "organ": "lung"})

    service.create_study.assert_called_once_with(CODE, OrganName.LUNG, None)


@pytest.mark.unit
def test_the_status_has_the_four_stages_in_order_and_no_personal_data(client, service) -> None:
    service.get_study.return_value = study(StudyStatus.PROCESSING)

    response = client.get(f"/studies/{CODE}/status")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "processing"
    assert body["total_time_sec"] is None
    assert [s["stage_number"] for s in body["stages"]] == [1, 2, 3, 4]
    assert [s["stage_name"] for s in body["stages"]] == [
        "preprocessing",
        "reconstruction",
        "segmentation",
        "meshing",
    ]
    assert body["stages"][1] == {
        "stage_number": 2,
        "stage_name": "reconstruction",
        "status": "running",
        "started_at": "2026-10-09T15:04:05Z",
        "finished_at": None,
    }
    assert_no_personal_data(response.text)
    service.get_study.assert_called_once_with(CODE)


@pytest.mark.unit
def test_processing_answers_202_and_runs_the_pipeline_once_in_the_background(
    client, service
) -> None:
    service.start_processing.return_value = study(StudyStatus.PROCESSING)

    response = client.post(f"/studies/{CODE}/process")

    assert response.status_code == 202
    assert response.json() == {
        "study_code": CODE,
        "status": "processing",
        "status_url": f"/studies/{CODE}/status",
    }
    service.start_processing.assert_called_once_with(CODE)
    service.run_processing.assert_called_once_with(CODE)


@pytest.mark.unit
def test_a_rejected_claim_does_not_launch_the_pipeline(client, service) -> None:
    service.start_processing.side_effect = InvalidStudyStateError(
        f"El estudio '{CODE}' esta en processing: solo se procesa un estudio en pending."
    )

    response = client.post(f"/studies/{CODE}/process")

    assert response.status_code == 409
    service.run_processing.assert_not_called()
