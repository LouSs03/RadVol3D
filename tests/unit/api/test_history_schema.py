"""Pruebas de los esquemas del historial (contracts/http_api_history.md de 005)."""

import pytest
from pydantic import ValidationError

from radvol3d.api.schemas.history_schema import (
    HISTORY_DEFAULT_LIMIT,
    HISTORY_MAX_LIMIT,
    StudyHistoryItem,
    StudySearchRequest,
    history_response,
)
from radvol3d.domain.entities import StudyHistoryEntry, StudyHistoryPage
from radvol3d.domain.enums import OrganName, StudyStatus

NATIONAL_ID = "12345678"


@pytest.mark.unit
def test_search_accepts_eight_digits_with_default_page() -> None:
    request = StudySearchRequest(national_id=NATIONAL_ID)

    assert request.national_id == NATIONAL_ID
    assert (request.offset, request.limit) == (0, HISTORY_DEFAULT_LIMIT)
    assert (HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT) == (50, 100)


@pytest.mark.unit
def test_search_strips_the_spaces_around_the_national_id() -> None:
    assert StudySearchRequest(national_id="  12345678 ").national_id == NATIONAL_ID


@pytest.mark.unit
@pytest.mark.parametrize("national_id", ["1234567", "123456789", "1234567a", ""])
def test_search_rejects_an_invalid_national_id_without_echoing_it(national_id: str) -> None:
    with pytest.raises(ValidationError) as error:
        StudySearchRequest(national_id=national_id)

    if national_id:
        assert national_id not in str(error.value)


@pytest.mark.unit
def test_search_requires_the_national_id() -> None:
    with pytest.raises(ValidationError):
        StudySearchRequest()  # type: ignore[call-arg]


@pytest.mark.unit
@pytest.mark.parametrize("page", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_search_rejects_a_page_out_of_range(page: dict) -> None:
    with pytest.raises(ValidationError):
        StudySearchRequest(national_id=NATIONAL_ID, **page)


@pytest.mark.unit
def test_history_item_has_no_name_fields() -> None:
    fields = set(StudyHistoryItem.model_fields)

    assert {"first_name", "last_name", "patient_code"}.isdisjoint(fields)
    assert "national_id" in fields


@pytest.mark.unit
def test_history_response_copies_the_page() -> None:
    entry = StudyHistoryEntry(
        study_code="it_a",
        organ=OrganName.LUNG,
        status=StudyStatus.COMPLETED,
        created_at=None,
        lesion_count=2,
        total_lesion_volume_mm3=42.75,
        national_id=NATIONAL_ID,
    )

    response = history_response(StudyHistoryPage([entry], 50, 25, True))

    assert response.offset == 50
    assert response.limit == 25
    assert response.has_more is True
    [item] = response.items
    assert item.model_dump() == {
        "study_code": "it_a",
        "organ": OrganName.LUNG,
        "status": StudyStatus.COMPLETED,
        "created_at": None,
        "lesion_count": 2,
        "total_lesion_volume_mm3": 42.75,
        "national_id": NATIONAL_ID,
    }
