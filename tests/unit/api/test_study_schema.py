"""Comprueba los esquemas HTTP de estudios (data-model.md §5)."""

import pytest
from pydantic import ValidationError

from radvol3d.api.schemas.projection_schema import ProjectionsUploaded
from radvol3d.api.schemas.study_schema import (
    PatientInput,
    ProcessingAccepted,
    StageStatusResponse,
    StudyCreate,
    StudyResponse,
    StudyStatusResponse,
)
from radvol3d.domain.enums import OrganName

PERSONAL_FIELDS = {"first_name", "last_name", "national_id"}


@pytest.mark.unit
@pytest.mark.parametrize("code", ["lung_028", "A-1", "x" * 64])
def test_a_valid_study_code_is_accepted(code: str) -> None:
    assert StudyCreate(study_code=code, organ="lung").study_code == code


@pytest.mark.unit
@pytest.mark.parametrize("code", ["", "x" * 65, "con espacio", "../otro", "a/b", "ñandu"])
def test_a_study_code_outside_the_pattern_is_rejected(code: str) -> None:
    with pytest.raises(ValidationError):
        StudyCreate(study_code=code, organ="lung")


@pytest.mark.unit
def test_the_organ_is_lung_or_liver() -> None:
    assert StudyCreate(study_code="a", organ="liver").organ is OrganName.LIVER
    with pytest.raises(ValidationError):
        StudyCreate(study_code="a", organ="kidney")


@pytest.mark.unit
def test_the_patient_is_optional_and_so_is_each_field() -> None:
    assert StudyCreate(study_code="a", organ="lung").patient is None
    assert PatientInput().national_id is None


@pytest.mark.unit
def test_first_and_last_name_accept_up_to_80_characters() -> None:
    PatientInput(first_name="a" * 80, last_name="b" * 80)
    with pytest.raises(ValidationError):
        PatientInput(first_name="a" * 81)
    with pytest.raises(ValidationError):
        PatientInput(last_name="b" * 81)


@pytest.mark.unit
@pytest.mark.parametrize("national_id", ["1234567", "123456789", "1234567X", "abcdefgh"])
def test_the_national_id_needs_eight_digits(national_id: str) -> None:
    with pytest.raises(ValidationError):
        PatientInput(national_id=national_id)


@pytest.mark.unit
def test_an_eight_digit_national_id_is_accepted() -> None:
    assert PatientInput(national_id="12345678").national_id == "12345678"


@pytest.mark.unit
@pytest.mark.parametrize(
    "schema", [StudyResponse, StudyStatusResponse, ProcessingAccepted, ProjectionsUploaded]
)
def test_no_response_has_personal_data_of_the_patient(schema: type) -> None:
    assert PERSONAL_FIELDS.isdisjoint(schema.model_fields)


@pytest.mark.unit
def test_a_stage_name_is_one_of_the_four_stages() -> None:
    for name in ("preprocessing", "reconstruction", "segmentation", "meshing"):
        StageStatusResponse(stage_number=1, stage_name=name, status="waiting")
    with pytest.raises(ValidationError):
        StageStatusResponse(stage_number=1, stage_name="otra", status="waiting")
    with pytest.raises(ValidationError):
        StageStatusResponse(stage_number=5, stage_name="meshing", status="waiting")
