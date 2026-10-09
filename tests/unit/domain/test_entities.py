"""Comprueba las entidades nuevas y los campos agregados al dominio."""

from datetime import date

import pytest

from radvol3d.domain.entities import (
    Model,
    Patient,
    PatientDetails,
    ProcessingStage,
    SegmentationResult,
    StoredResult,
    Study,
)
from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus

FIRST_NAME = "Rosa"
LAST_NAME = "Quispe"
NATIONAL_ID = "12345678"


@pytest.mark.unit
def test_study_and_stage_still_build_without_the_new_fields() -> None:
    study = Study(study_code="it_a", organ=OrganName.LUNG, status=StudyStatus.PENDING)
    stage = ProcessingStage(stage_number=StageNumber.PREPROCESSING, status=StageStatus.WAITING)

    assert study.patient is None
    assert study.model is None
    assert study.grid_size is None
    assert stage.model is None


@pytest.mark.unit
def test_patient_representation_hides_personal_data() -> None:
    patient = Patient(
        patient_code="PAC000001",
        first_name=FIRST_NAME,
        last_name=LAST_NAME,
        national_id=NATIONAL_ID,
    )

    shown = f"{patient!r} {patient!s}"

    assert "PAC000001" in shown
    for secret in (FIRST_NAME, LAST_NAME, NATIONAL_ID):
        assert secret not in shown


@pytest.mark.unit
def test_patient_details_representation_hides_personal_data() -> None:
    details = PatientDetails(first_name=FIRST_NAME, last_name=LAST_NAME, national_id=NATIONAL_ID)

    shown = f"{details!r} {details!s}"

    for secret in (FIRST_NAME, LAST_NAME, NATIONAL_ID):
        assert secret not in shown


@pytest.mark.unit
def test_patient_details_fields_are_all_optional() -> None:
    details = PatientDetails()

    assert details.first_name is None
    assert details.last_name is None
    assert details.national_id is None


@pytest.mark.unit
def test_study_keeps_patient_model_and_grid_size() -> None:
    patient = Patient(patient_code="PAC000000")
    model = Model(model_name="reconstruction_en1", version="1.0.0", trained_on=date(2026, 1, 2))

    study = Study(
        study_code="it_a",
        organ=OrganName.LIVER,
        status=StudyStatus.COMPLETED,
        patient=patient,
        model=model,
        grid_size=128,
    )

    assert study.patient is patient
    assert study.model is model
    assert study.grid_size == 128


@pytest.mark.unit
def test_stage_keeps_the_model_that_ran_it() -> None:
    model = Model(model_name="segmentation_lung", version="1.0.0")

    stage = ProcessingStage(
        stage_number=StageNumber.SEGMENTATION, status=StageStatus.COMPLETED, model=model
    )

    assert stage.model is model


@pytest.mark.unit
def test_stored_result_built_with_only_the_code_is_empty() -> None:
    result = StoredResult("it_x")

    assert result.study_code == "it_x"
    assert result.lesions == []
    assert result.mask_path is None
    assert result.probability_path is None
    assert result.summary_path is None
    assert result.organ_mesh_path is None
    assert result.tumor_mesh_path is None


@pytest.mark.unit
def test_stored_results_do_not_share_the_lesion_list() -> None:
    first = StoredResult("it_a")
    second = StoredResult("it_b")

    first.lesions.append(object())

    assert second.lesions == []


@pytest.mark.unit
def test_segmentation_result_still_builds_without_a_summary() -> None:
    result = SegmentationResult(mask="mascara", probability="probabilidad", global_confidence=0.9)

    assert result.summary == {}


@pytest.mark.unit
def test_segmentation_result_keeps_the_summary_it_receives() -> None:
    summary = {"study_code": "it_a", "regions": []}

    result = SegmentationResult(
        mask="mascara", probability="probabilidad", global_confidence=0.9, summary=summary
    )

    assert result.summary == summary


@pytest.mark.unit
def test_segmentation_results_do_not_share_the_summary() -> None:
    first = SegmentationResult(mask=None, probability=None, global_confidence=0.0)
    second = SegmentationResult(mask=None, probability=None, global_confidence=0.0)

    assert first.summary is not second.summary
