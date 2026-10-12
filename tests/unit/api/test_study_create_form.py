"""El formulario de nuevo estudio: codigo editable y datos opcionales del paciente.

La interfaz propone un codigo con la fecha, pero el usuario lo puede cambiar; la API
acepta cualquier codigo con el formato. Nombre, apellido y DNI viajan en patient, se
guardan del lado del servidor y nunca vuelven en una respuesta ni en un error (FR-029).
"""

import pytest
from pydantic import ValidationError

from radvol3d.api.schemas.study_schema import PatientInput
from radvol3d.domain.entities import Patient, PatientDetails, Study
from radvol3d.domain.enums import OrganName, StudyStatus

CUSTOM_CODE = "Torax_Control-02"
FIRST_NAME = "Rosaura"
LAST_NAME = "Quispecahuana"
NATIONAL_ID = "87654321"
PERSONAL_KEYS = (
    "patient_name",
    "patient_surname",
    "patient_dni",
    "first_name",
    "last_name",
    "national_id",
)


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


def created(study_code: str) -> Study:
    return Study(
        study_code=study_code,
        organ=OrganName.LUNG,
        status=StudyStatus.PENDING,
        patient=Patient("PAC000001", FIRST_NAME, LAST_NAME, NATIONAL_ID),
    )


@pytest.mark.unit
def test_a_study_code_chosen_by_the_user_is_accepted(client, service) -> None:
    service.create_study.return_value = created(CUSTOM_CODE)

    response = client.post("/studies", json={"study_code": CUSTOM_CODE, "organ": "lung"})

    assert response.status_code == 201
    assert response.json()["study_code"] == CUSTOM_CODE
    service.create_study.assert_called_once_with(CUSTOM_CODE, OrganName.LUNG, None)


@pytest.mark.unit
@pytest.mark.parametrize(
    "code", ["con espacio", "rv 0418", "rv.0418", "rv/0418", "ñandu", "x" * 65]
)
def test_a_study_code_with_spaces_or_other_characters_is_rejected_with_422(
    client, service, code: str
) -> None:
    response = client.post("/studies", json={"study_code": code, "organ": "lung"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "study_code"]
    service.create_study.assert_not_called()


@pytest.mark.unit
def test_an_eight_digit_national_id_is_accepted() -> None:
    assert PatientInput(national_id=NATIONAL_ID).national_id == NATIONAL_ID


@pytest.mark.unit
@pytest.mark.parametrize(
    "national_id",
    [
        pytest.param("1234567A", id="con letras"),
        pytest.param("1234567", id="siete digitos"),
        pytest.param("123456789", id="nueve digitos"),
    ],
)
def test_a_national_id_that_is_not_eight_digits_is_rejected(national_id: str) -> None:
    with pytest.raises(ValidationError):
        PatientInput(national_id=national_id)


@pytest.mark.unit
@pytest.mark.parametrize("national_id", [None, "", "   "])
def test_an_empty_national_id_is_accepted_as_absent(national_id: str | None) -> None:
    assert PatientInput(national_id=national_id).national_id is None


@pytest.mark.unit
def test_a_form_with_the_three_patient_fields_blank_creates_the_study(client, service) -> None:
    service.create_study.return_value = created(CUSTOM_CODE)

    response = client.post(
        "/studies",
        json={
            "study_code": CUSTOM_CODE,
            "organ": "lung",
            "patient": {"first_name": "", "last_name": " ", "national_id": ""},
        },
    )

    assert response.status_code == 201
    service.create_study.assert_called_once_with(
        CUSTOM_CODE, OrganName.LUNG, PatientDetails(None, None, None)
    )


@pytest.mark.unit
def test_the_response_of_creating_a_study_has_no_patient_data(client, service) -> None:
    service.create_study.return_value = created(CUSTOM_CODE)

    response = client.post(
        "/studies",
        json={
            "study_code": CUSTOM_CODE,
            "organ": "lung",
            "patient": {
                "first_name": FIRST_NAME,
                "last_name": LAST_NAME,
                "national_id": NATIONAL_ID,
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    for key in PERSONAL_KEYS:
        assert key not in body
    for value in (FIRST_NAME, LAST_NAME, NATIONAL_ID):
        assert value not in response.text
    service.create_study.assert_called_once_with(
        CUSTOM_CODE,
        OrganName.LUNG,
        PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID),
    )


@pytest.mark.unit
@pytest.mark.parametrize("national_id", ["8765432Z", "8765432", "876543219"])
def test_an_invalid_national_id_is_not_echoed_in_the_error(
    client, service, caplog, national_id: str
) -> None:
    with caplog.at_level("DEBUG"):
        response = client.post(
            "/studies",
            json={
                "study_code": CUSTOM_CODE,
                "organ": "lung",
                "patient": {"national_id": national_id},
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "patient", "national_id"]
    assert national_id not in response.text
    assert national_id not in caplog.text
    service.create_study.assert_not_called()


@pytest.mark.unit
def test_the_validation_error_text_does_not_carry_the_national_id() -> None:
    # Si un ValidationError llegara a un registro o una traza, no lleva el valor.
    with pytest.raises(ValidationError) as error:
        PatientInput(first_name=FIRST_NAME, national_id="8765432Z")

    assert "8765432Z" not in str(error.value)
    assert "8765432Z" not in repr(error.value)
