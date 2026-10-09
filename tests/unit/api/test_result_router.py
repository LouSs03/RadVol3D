"""Pruebas del resultado y las descargas con el servicio simulado (research.md R6)."""

import pytest

from radvol3d.domain.entities import Lesion, StoredResult
from radvol3d.domain.enums import OrganName, ResultFile
from radvol3d.domain.exceptions import InvalidStudyStateError, StorageObjectNotFoundError

CODE = "lung_028"


def stored_result() -> StoredResult:
    return StoredResult(
        study_code=CODE,
        lesions=[
            Lesion(
                "medio del eje 0 · medio del eje 1 · medio del eje 2",
                8000.0,
                0.9,
                34.64,
                f"{CODE}/meshes/lesion_001.glb",
                OrganName.LUNG,
            ),
            Lesion("inicio del eje 0", 120.5, 0.61, None, f"{CODE}/meshes/lesion_002.glb", OrganName.LUNG),
        ],
        volume_path=f"{CODE}/volume.npy",
        organ_mesh_path=f"{CODE}/meshes/organ.glb",
        tumor_mesh_path=f"{CODE}/meshes/tumor.glb",
    )


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


@pytest.mark.unit
def test_the_result_has_service_urls_and_one_row_per_lesion(client, service) -> None:
    service.get_completed_result.return_value = stored_result()

    response = client.get(f"/studies/{CODE}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["study_code"] == CODE
    assert body["organ_mesh_url"] == f"/studies/{CODE}/result/organ.glb"
    assert body["tumor_mesh_url"] == f"/studies/{CODE}/result/tumor.glb"
    assert body["volume_url"] == f"/studies/{CODE}/result/volume.npy"
    assert body["lesions"] == [
        {
            "lesion_number": 1,
            "organ": "lung",
            "location": "medio del eje 0 · medio del eje 1 · medio del eje 2",
            "volume_mm3": 8000.0,
            "max_diameter_mm": 34.64,
            "confidence": 0.9,
            "mesh_url": f"/studies/{CODE}/result/lesions/1.glb",
        },
        {
            "lesion_number": 2,
            "organ": "lung",
            "location": "inicio del eje 0",
            "volume_mm3": 120.5,
            "max_diameter_mm": None,
            "confidence": 0.61,
            "mesh_url": f"/studies/{CODE}/result/lesions/2.glb",
        },
    ]
    for hidden in ("region_id", "lesion_id", "meshes/lesion_001.glb", "supabase"):
        assert hidden not in response.text


@pytest.mark.unit
def test_a_result_without_lesions_has_an_empty_list(client, service) -> None:
    service.get_completed_result.return_value = StoredResult(CODE)

    response = client.get(f"/studies/{CODE}/result")

    assert response.status_code == 200
    assert response.json()["lesions"] == []


@pytest.mark.unit
def test_the_result_of_an_unfinished_study_is_a_conflict(client, service) -> None:
    message = f"El estudio '{CODE}' esta en processing: el resultado solo existe cuando termina."
    service.get_completed_result.side_effect = InvalidStudyStateError(message)

    response = client.get(f"/studies/{CODE}/result")

    assert response.status_code == 409
    assert response.json() == {"detail": message}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "file"),
    [("organ.glb", ResultFile.ORGAN_MESH), ("tumor.glb", ResultFile.TUMOR_MESH)],
)
def test_the_meshes_are_served_as_glb(client, service, path: str, file: ResultFile) -> None:
    service.read_result_file.return_value = b"glTF-malla"

    response = client.get(f"/studies/{CODE}/result/{path}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.content == b"glTF-malla"
    service.read_result_file.assert_called_once_with(CODE, file)


@pytest.mark.unit
def test_the_volume_is_an_attachment(client, service) -> None:
    service.read_result_file.return_value = b"\x93NUMPY-volumen"

    response = client.get(f"/studies/{CODE}/result/volume.npy")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="{CODE}_volume.npy"'
    )
    service.read_result_file.assert_called_once_with(CODE, ResultFile.VOLUME)


@pytest.mark.unit
def test_a_lesion_mesh_is_served_by_its_number(client, service) -> None:
    service.read_lesion_mesh.return_value = b"glTF-lesion-2"

    response = client.get(f"/studies/{CODE}/result/lesions/2.glb")

    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.content == b"glTF-lesion-2"
    service.read_lesion_mesh.assert_called_once_with(CODE, 2)


@pytest.mark.unit
def test_a_lesion_number_outside_the_list_is_not_found(client, service) -> None:
    service.read_lesion_mesh.side_effect = StorageObjectNotFoundError(
        f"El estudio '{CODE}' no tiene la lesion 9."
    )

    response = client.get(f"/studies/{CODE}/result/lesions/9.glb")

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("number", ["0", "abc"])
def test_a_lesion_number_that_is_not_positive_is_invalid(client, service, number: str) -> None:
    response = client.get(f"/studies/{CODE}/result/lesions/{number}.glb")

    assert response.status_code == 422
    service.read_lesion_mesh.assert_not_called()


@pytest.mark.unit
def test_a_download_of_an_unfinished_study_is_a_conflict(client, service) -> None:
    service.read_result_file.side_effect = InvalidStudyStateError("esta en pending")

    response = client.get(f"/studies/{CODE}/result/organ.glb")

    assert response.status_code == 409
