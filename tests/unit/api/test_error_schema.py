"""Comprueba la forma de los cuerpos de error de la API."""

import pytest

from radvol3d.api.schemas.error_schema import (
    ErrorResponse,
    ValidationErrorItem,
    ValidationErrorResponse,
)


@pytest.mark.unit
def test_an_error_body_only_has_the_detail() -> None:
    assert set(ErrorResponse.model_fields) == {"detail"}


@pytest.mark.unit
def test_a_validation_error_never_carries_the_received_input() -> None:
    assert set(ValidationErrorItem.model_fields) == {"loc", "msg", "type"}
    assert set(ValidationErrorResponse.model_fields) == {"detail"}
