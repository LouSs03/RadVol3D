"""Pruebas del paso de filas de la base a entidades del dominio."""

from datetime import date

import pytest

from radvol3d.domain.entities import Model, Patient
from radvol3d.persistence.repositories.row_mapping import model_from_row, patient_from_row


@pytest.mark.unit
def test_patient_from_row_builds_the_entity() -> None:
    row = {
        "patient_code": "PAC000003",
        "first_name": "Rosa",
        "last_name": "Quispe",
        "national_id": "12345678",
    }

    assert patient_from_row(row) == Patient("PAC000003", "Rosa", "Quispe", "12345678")


@pytest.mark.unit
def test_patient_from_row_keeps_the_optional_fields_empty() -> None:
    row = {"patient_code": "PAC000000", "first_name": None, "last_name": None, "national_id": None}

    patient = patient_from_row(row)

    assert patient.first_name is None
    assert patient.last_name is None
    assert patient.national_id is None


@pytest.mark.unit
def test_model_from_row_builds_the_entity() -> None:
    row = {
        "model_name": "reconstruction_en1",
        "version": "1.0.0",
        "trained_on": date(2026, 1, 2),
        "description": "Red de reconstruccion",
    }

    assert model_from_row(row) == Model(
        "reconstruction_en1", "1.0.0", date(2026, 1, 2), "Red de reconstruccion"
    )


@pytest.mark.unit
def test_model_from_row_returns_none_when_the_outer_join_found_no_model() -> None:
    row = {"model_name": None, "version": None, "trained_on": None, "description": None}

    assert model_from_row(row) is None
