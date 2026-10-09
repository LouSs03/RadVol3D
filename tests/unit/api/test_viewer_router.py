"""Pruebas de la pagina del visor 3D (contracts/http_api.md, "Visor")."""

import re
from pathlib import Path

import pytest

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import InvalidStudyIdError, StudyNotFoundError

CODE = "lung_028"
VIEWER_HTML = Path(__file__).resolve().parents[3] / "src" / "radvol3d" / "web" / "viewer.html"


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


@pytest.mark.unit
def test_an_existing_study_gets_the_viewer_page(client, service) -> None:
    service.get_study.return_value = Study(CODE, OrganName.LUNG, StudyStatus.COMPLETED)

    response = client.get(f"/viewer/{CODE}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == VIEWER_HTML.read_text(encoding="utf-8")
    service.get_study.assert_called_once_with(CODE)


@pytest.mark.unit
def test_an_unknown_study_gets_the_same_page_with_not_found(client, service) -> None:
    service.get_study.side_effect = StudyNotFoundError(f"No existe el estudio '{CODE}'.")

    response = client.get(f"/viewer/{CODE}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == VIEWER_HTML.read_text(encoding="utf-8")


@pytest.mark.unit
def test_an_invalid_code_is_a_bad_request(client, service) -> None:
    service.get_study.side_effect = InvalidStudyIdError("codigo invalido")

    response = client.get("/viewer/con%20espacio")

    assert response.status_code == 400


@pytest.mark.unit
def test_the_page_uses_absolute_paths_for_its_own_files() -> None:
    page = VIEWER_HTML.read_text(encoding="utf-8")

    assert 'href="/css/main.css"' in page
    assert 'src="/js/viewer_3d.js"' in page
    assert 'href="css/' not in page
    assert 'src="js/' not in page


@pytest.mark.unit
def test_three_js_comes_from_an_import_map_with_a_fixed_version() -> None:
    page = VIEWER_HTML.read_text(encoding="utf-8")

    assert '<script type="importmap">' in page
    versions = set(re.findall(r"cdn\.jsdelivr\.net/npm/three@([^/\"]+)/", page))
    assert len(versions) == 1
    (version,) = versions
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert "latest" not in page
