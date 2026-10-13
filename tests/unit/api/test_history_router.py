"""Pruebas de las rutas del historial con el servicio simulado (005, http_api_history.md)."""

from datetime import UTC, datetime

import pytest

from radvol3d.domain.entities import StudyHistoryEntry, StudyHistoryPage
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import DatabaseUnavailableError

CREATED_AT = datetime(2026, 10, 12, 15, 30, tzinfo=UTC)
NATIONAL_ID = "12345678"


def entry(code: str, **overrides) -> StudyHistoryEntry:
    values = {
        "study_code": code,
        "organ": OrganName.LUNG,
        "status": StudyStatus.COMPLETED,
        "created_at": CREATED_AT,
        "lesion_count": 2,
        "total_lesion_volume_mm3": 42.75,
        "national_id": NATIONAL_ID,
    }
    values.update(overrides)
    return StudyHistoryEntry(**values)


def page(*entries: StudyHistoryEntry, offset: int = 0, limit: int = 50, has_more: bool = False):
    return StudyHistoryPage(list(entries), offset, limit, has_more)


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


# --- GET /studies ------------------------------------------------------------------


@pytest.mark.unit
def test_history_answers_the_page_in_the_service_order(client, service) -> None:
    service.list_history.return_value = page(
        entry("nuevo"), entry("viejo", status=StudyStatus.PENDING), has_more=True
    )

    response = client.get("/studies")

    assert response.status_code == 200
    body = response.json()
    assert [item["study_code"] for item in body["items"]] == ["nuevo", "viejo"]
    assert (body["offset"], body["limit"], body["has_more"]) == (0, 50, True)
    assert body["items"][0]["total_lesion_volume_mm3"] == 42.75
    assert body["items"][0]["lesion_count"] == 2


@pytest.mark.unit
def test_history_uses_the_default_page(client, service) -> None:
    service.list_history.return_value = page()

    client.get("/studies")

    service.list_history.assert_called_once_with(limit=50, offset=0, national_id=None)


@pytest.mark.unit
def test_history_passes_the_requested_page(client, service) -> None:
    service.list_history.return_value = page(offset=50, limit=100)

    client.get("/studies", params={"offset": 50, "limit": 100})

    service.list_history.assert_called_once_with(limit=100, offset=50, national_id=None)


@pytest.mark.unit
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_history_rejects_a_page_out_of_range(client, service, params: dict) -> None:
    response = client.get("/studies", params=params)

    assert response.status_code == 422
    service.list_history.assert_not_called()


@pytest.mark.unit
def test_history_answers_an_empty_page(client, service) -> None:
    service.list_history.return_value = page()

    body = client.get("/studies").json()

    assert body["items"] == []
    assert body["has_more"] is False


@pytest.mark.unit
def test_history_items_have_no_names(client, service) -> None:
    service.list_history.return_value = page(entry("it_a"))

    [item] = client.get("/studies").json()["items"]

    assert "first_name" not in item
    assert "last_name" not in item


@pytest.mark.unit
def test_history_answers_503_when_the_database_is_down(client, service) -> None:
    service.list_history.side_effect = DatabaseUnavailableError("La base no responde.")

    assert client.get("/studies").status_code == 503


# --- POST /studies/search ------------------------------------------------------------


@pytest.mark.unit
def test_search_passes_the_national_id_from_the_body(client, service) -> None:
    service.list_history.return_value = page(entry("it_a"))

    response = client.post("/studies/search", json={"national_id": NATIONAL_ID})

    assert response.status_code == 200
    service.list_history.assert_called_once_with(limit=50, offset=0, national_id=NATIONAL_ID)
    assert response.json()["items"][0]["national_id"] == NATIONAL_ID


@pytest.mark.unit
def test_search_strips_the_spaces_around_the_national_id(client, service) -> None:
    service.list_history.return_value = page()

    client.post("/studies/search", json={"national_id": " 12345678 "})

    service.list_history.assert_called_once_with(limit=50, offset=0, national_id=NATIONAL_ID)


@pytest.mark.unit
def test_search_passes_the_requested_page(client, service) -> None:
    service.list_history.return_value = page(offset=50, limit=10)

    client.post("/studies/search", json={"national_id": NATIONAL_ID, "offset": 50, "limit": 10})

    service.list_history.assert_called_once_with(limit=10, offset=50, national_id=NATIONAL_ID)


@pytest.mark.unit
def test_search_without_studies_is_an_empty_page(client, service) -> None:
    service.list_history.return_value = page()

    response = client.post("/studies/search", json={"national_id": NATIONAL_ID})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["has_more"] is False


@pytest.mark.unit
@pytest.mark.parametrize("national_id", ["1234567", "123456789", "1234567a"])
def test_search_rejects_an_invalid_national_id_without_echoing_it(
    client, service, national_id: str
) -> None:
    response = client.post("/studies/search", json={"national_id": national_id})

    assert response.status_code == 422
    assert national_id not in response.text
    service.list_history.assert_not_called()


@pytest.mark.unit
def test_search_requires_the_national_id(client, service) -> None:
    response = client.post("/studies/search", json={})

    assert response.status_code == 422
    service.list_history.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("page_fields", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_search_rejects_a_page_out_of_range(client, service, page_fields: dict) -> None:
    response = client.post("/studies/search", json={"national_id": NATIONAL_ID, **page_fields})

    assert response.status_code == 422
    service.list_history.assert_not_called()


@pytest.mark.unit
def test_history_shows_the_national_id_or_null(client, service) -> None:
    service.list_history.return_value = page(entry("con_dni"), entry("sin_dni", national_id=None))

    items = client.get("/studies").json()["items"]

    assert [item["national_id"] for item in items] == [NATIONAL_ID, None]


@pytest.mark.unit
def test_search_leaves_no_national_id_in_the_logs(client, service, caplog) -> None:
    service.list_history.return_value = page(entry("it_a"))

    with caplog.at_level("DEBUG"):
        client.post("/studies/search", json={"national_id": NATIONAL_ID})
        client.post("/studies/search", json={"national_id": "1234567"})

    assert NATIONAL_ID not in caplog.text
    assert "1234567" not in caplog.text
