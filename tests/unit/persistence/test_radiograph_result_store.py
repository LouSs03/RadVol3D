"""Pruebas del almacen de resultados del modo de una radiografia con X2CT-GAN."""

import json

import pytest

from radvol3d.persistence.radiograph_result_store import RadiographResultStore

CODE = "rx_001"
FILES = {
    "volumen.nii.gz": b"\x1f\x8bnifti",
    "entrada_modelo_128.png": b"\x89PNG",
    "metadatos.json": b'{"avisos": []}',
}
VIEW = {"voxel_mm": [3.3, 3.3, 3.1], "relative_measurements": False, "warnings": []}


class Bucket:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    def upload_bytes(self, path: str, data: bytes, content_type: str) -> None:
        self.files[path] = (data, content_type)

    def download_bytes(self, path: str) -> bytes:
        return self.files[path][0]

    def exists(self, path: str) -> bool:
        return path in self.files


@pytest.mark.unit
def test_the_output_package_and_the_view_go_to_the_reconstruction_folder() -> None:
    bucket = Bucket()
    store = RadiographResultStore(bucket)

    store.save_reconstruction(CODE, FILES, VIEW)

    assert bucket.files[f"{CODE}/reconstruction/volumen.nii.gz"] == (FILES["volumen.nii.gz"], "application/gzip")
    assert bucket.files[f"{CODE}/reconstruction/entrada_modelo_128.png"][1] == "image/png"
    assert bucket.files[f"{CODE}/reconstruction/metadatos.json"][1] == "application/json"
    assert json.loads(bucket.files[f"{CODE}/reconstruction/visor.json"][0]) == VIEW


@pytest.mark.unit
def test_the_surface_goes_where_the_viewer_reads_the_organ_mesh() -> None:
    bucket = Bucket()

    RadiographResultStore(bucket).save_organ_mesh(CODE, b"glTF")

    assert bucket.files[f"{CODE}/meshes/organ.glb"] == (b"glTF", "model/gltf-binary")


@pytest.mark.unit
def test_the_view_and_the_files_are_read_back() -> None:
    bucket = Bucket()
    store = RadiographResultStore(bucket)
    assert store.has_view(CODE) is False
    store.save_reconstruction(CODE, FILES, VIEW)

    assert store.has_view(CODE) is True
    assert store.read_view(CODE) == VIEW
    assert store.read_file(CODE, "metadatos.json") == FILES["metadatos.json"]


@pytest.mark.unit
def test_only_the_reconstruction_files_can_be_read() -> None:
    with pytest.raises(ValueError):
        RadiographResultStore(Bucket()).read_file(CODE, "../otro/volume.npy")
