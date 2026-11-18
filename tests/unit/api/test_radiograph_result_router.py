"""Pruebas del resultado de un estudio de una radiografia (visor propio de ese modo)."""

import pytest

from radvol3d.domain.exceptions import InvalidStudyStateError, StudyNotFoundError

CODE = "rx_001"
X2CT_VIEW = {
    "model_name": "reconstruction_x2ct",
    "model_version": "1.0.0",
    "voxel_mm": [3.3047, 3.3047, 3.1339],
    "relative_measurements": False,
    "warnings": ["Solo hay ImagerPixelSpacing (plano del detector)."],
    "input_size_px": [2140, 2140],
    "timings_s": {"inferencia": 3.4},
}


@pytest.fixture
def service(client):
    return client.app.state.services.study_service


@pytest.mark.unit
def test_the_result_has_the_voxel_the_warnings_and_the_file_urls(client, service) -> None:
    service.radiograph_view.return_value = X2CT_VIEW

    response = client.get(f"/studies/{CODE}/radiograph-result")

    assert response.status_code == 200
    body = response.json()
    assert body["voxel_mm"] == X2CT_VIEW["voxel_mm"]
    assert body["relative_measurements"] is False
    assert body["warnings"] == X2CT_VIEW["warnings"]
    assert body["input_size_px"] == [2140, 2140]
    assert body["volume_url"] == f"/studies/{CODE}/result/volume.npy"
    assert body["surface_url"] == f"/studies/{CODE}/result/organ.glb"
    assert body["nifti_url"] == f"/studies/{CODE}/radiograph-result/volumen.nii.gz"
    assert body["input_image_url"] == f"/studies/{CODE}/radiograph-result/entrada_modelo_128.png"
    assert "lesions" not in body
    service.radiograph_view.assert_called_once_with(CODE)


@pytest.mark.unit
def test_without_pixel_size_the_result_says_measurements_are_relative(client, service) -> None:
    service.radiograph_view.return_value = {
        **X2CT_VIEW,
        "voxel_mm": [13.4453, 13.4453, 15.6797],
        "relative_measurements": True,
    }

    body = client.get(f"/studies/{CODE}/radiograph-result").json()

    assert body["relative_measurements"] is True
    assert body["voxel_mm"][2] > body["voxel_mm"][0]


@pytest.mark.unit
def test_a_study_reconstructed_with_axon_has_no_x2ct_files(client, service) -> None:
    service.radiograph_view.return_value = {
        "model_name": "reconstruction_axon_coarsediff",
        "voxel_mm": [2.5, 2.5, 2.5],
        "relative_measurements": False,
        "warnings": [],
        "has_reconstruction_files": False,
    }

    body = client.get(f"/studies/{CODE}/radiograph-result").json()

    assert body["nifti_url"] is None and body["input_image_url"] is None
    assert body["volume_url"] == f"/studies/{CODE}/result/volume.npy"


@pytest.mark.unit
def test_a_study_that_is_not_ready_or_not_a_radiograph_is_a_conflict(client, service) -> None:
    service.radiograph_view.side_effect = InvalidStudyStateError("no termino")

    assert client.get(f"/studies/{CODE}/radiograph-result").status_code == 409


@pytest.mark.unit
def test_an_unknown_study_is_not_found(client, service) -> None:
    service.radiograph_view.side_effect = StudyNotFoundError("no existe")

    assert client.get(f"/studies/{CODE}/radiograph-result").status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("volumen.nii.gz", "application/gzip"),
        ("entrada_modelo_128.png", "image/png"),
        ("metadatos.json", "application/json"),
    ],
)
def test_each_x2ct_file_is_served_with_its_type(client, service, name, media_type) -> None:
    service.read_radiograph_output.return_value = b"contenido"

    response = client.get(f"/studies/{CODE}/radiograph-result/{name}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.content == b"contenido"
    service.read_radiograph_output.assert_called_once_with(CODE, name)


@pytest.mark.unit
def test_other_files_cannot_be_requested(client, service) -> None:
    response = client.get(f"/studies/{CODE}/radiograph-result/visor.json")

    assert response.status_code == 422
    service.read_radiograph_output.assert_not_called()


# --- Validacion frontal (T3) ---------------------------------------------------------


@pytest.mark.unit
def test_the_validation_comes_with_the_urls_of_its_images(client, service) -> None:
    service.radiograph_validation.return_value = {"ncc": 0.788, "pulmones": {"disponible": True}}

    response = client.get(f"/studies/{CODE}/radiograph-validation")

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["ncc"] == 0.788
    assert body["simulated_url"] == f"/studies/{CODE}/radiograph-result/proyeccion_frontal_128.png"
    assert body["overlay_url"] == f"/studies/{CODE}/radiograph-result/validacion_superposicion.png"
    assert body["json_url"] == f"/studies/{CODE}/radiograph-result/validacion.json"
    service.radiograph_validation.assert_called_once_with(CODE)


@pytest.mark.unit
def test_a_study_without_validation_is_a_conflict(client, service) -> None:
    service.radiograph_validation.side_effect = InvalidStudyStateError("no se reconstruyo con X2CT")

    assert client.get(f"/studies/{CODE}/radiograph-validation").status_code == 409


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "inline"),
    [
        ("proyeccion_frontal_128.png", True),
        ("validacion_superposicion.png", True),
        ("validacion.json", False),
    ],
)
def test_the_validation_files_are_served(client, service, name, inline) -> None:
    service.read_radiograph_output.return_value = b"contenido"

    response = client.get(f"/studies/{CODE}/radiograph-result/{name}")

    assert response.status_code == 200
    assert ("content-disposition" in response.headers) is not inline
