"""El recorrido completo por HTTP, de punta a punta (FR-031, SC-001).

Caja negra: entra solo por la API. La aplicacion es la real, con el Supabase de
prueba y las estrategias dobles (tests/e2e/app_with_fakes.py). TestClient corre la
tarea en segundo plano al terminar la respuesta de /process, asi que al volver el
estudio ya termino y la prueba es determinista.

Se omite si no existe .env.test. El estudio lleva el prefijo "it_", no trae datos
del paciente (usa el paciente de referencia) y se borra al final aunque falle algo.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from radvol3d.domain.exceptions import ConfigurationError
from tests.e2e.app_with_fakes import create_app_with_fakes
from tests.fixtures.projection_files import valid_npy

pytestmark = pytest.mark.e2e

FIELDS = {0: "angle_000", 45: "angle_045", 90: "angle_090", 135: "angle_135"}


@pytest.fixture
def client():
    try:
        app = create_app_with_fakes()
    except ConfigurationError as error:
        pytest.skip(str(error))
    with TestClient(app) as test_client:
        yield test_client


def test_a_study_goes_from_creation_to_the_viewer_and_is_deleted(client: TestClient) -> None:
    code = f"it_{uuid.uuid4().hex[:12]}"
    try:
        created = client.post("/studies", json={"study_code": code, "organ": "lung"})
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "pending"

        files = {
            field: (f"{field}.npy", valid_npy(angle), "application/octet-stream")
            for angle, field in FIELDS.items()
        }
        uploaded = client.post(f"/studies/{code}/projections", files=files)
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()["angles"] == [0, 45, 90, 135]

        accepted = client.post(f"/studies/{code}/process")
        assert accepted.status_code == 202, accepted.text

        status = client.get(f"/studies/{code}/status")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed", body
        assert [stage["status"] for stage in body["stages"]] == ["completed"] * 4
        assert body["total_time_sec"] is not None

        result = client.get(f"/studies/{code}/result")
        assert result.status_code == 200, result.text
        result_body = result.json()
        assert len(result_body["lesions"]) == 1
        lesion = result_body["lesions"][0]
        assert lesion["organ"] == "lung"
        assert "region_id" not in lesion

        for url in (
            result_body["organ_mesh_url"],
            result_body["tumor_mesh_url"],
            lesion["mesh_url"],
        ):
            mesh = client.get(url)
            assert mesh.status_code == 200, url
            assert mesh.headers["content-type"] == "model/gltf-binary"
            assert mesh.content.startswith(b"glTF"), url
        volume = client.get(result_body["volume_url"])
        assert volume.status_code == 200
        assert volume.content.startswith(b"\x93NUMPY")

        viewer = client.get(f"/viewer/{code}")
        assert viewer.status_code == 200
        assert viewer.headers["content-type"].startswith("text/html")

        deleted = client.delete(f"/studies/{code}")
        assert deleted.status_code == 204
        assert client.get(f"/studies/{code}/status").status_code == 404
    finally:
        client.delete(f"/studies/{code}")
