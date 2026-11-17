"""Archivos del resultado de un estudio de una radiografia reconstruido con X2CT-GAN.

Es un camino propio, separado de ResultStore (modo de cuatro proyecciones): este modo
no tiene segmentacion, asi que no guarda mascara, probabilidad, resumen, lesiones ni
malla del tumor. Guarda, en el bucket del estudio:

    <study_code>/reconstruction/volumen.nii.gz          volumen de X2CT en HU, con su voxel
    <study_code>/reconstruction/entrada_modelo_128.png  la placa exacta que vio el modelo
    <study_code>/reconstruction/metadatos.json          lo que informa X2CT (mm, avisos...)
    <study_code>/reconstruction/visor.json              voxel con que se muestra y avisos
    <study_code>/meshes/organ.glb                       la superficie para el visor

El volumen del sistema (<study_code>/volume.npy) lo guarda StudyMetadataStore, como
en los demas estudios. Borrar el estudio borra todo esto (StudyMetadataStore).
"""

import json
from collections.abc import Mapping
from typing import Any

from radvol3d.persistence.object_storage import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_MESH,
    ObjectStorage,
)
from radvol3d.persistence.storage_layout import (
    RADIOGRAPH_OUTPUT_FILES,
    organ_mesh_path,
    radiograph_output_path,
)

VIEW_FILE = "visor.json"
CONTENT_TYPES: dict[str, str] = {
    "volumen.nii.gz": "application/gzip",
    "entrada_modelo_128.png": "image/png",
    "metadatos.json": CONTENT_TYPE_JSON,
    VIEW_FILE: CONTENT_TYPE_JSON,
}


class RadiographResultStore:
    """Guarda y lee los archivos de X2CT-GAN de un estudio."""

    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    def save_reconstruction(
        self, study_code: str, files: Mapping[str, bytes], view: Mapping[str, Any]
    ) -> None:
        """Sube el paquete de salida de X2CT-GAN y los datos del visor."""
        for name, data in files.items():
            self._storage.upload_bytes(
                radiograph_output_path(study_code, name), data, CONTENT_TYPES[name]
            )
        self._storage.upload_bytes(
            radiograph_output_path(study_code, VIEW_FILE),
            json.dumps(dict(view), ensure_ascii=False, indent=2).encode("utf-8"),
            CONTENT_TYPE_JSON,
        )

    def save_organ_mesh(self, study_code: str, organ_mesh: bytes) -> None:
        """Sube la superficie que dibuja el visor (la misma ruta que en los demas estudios)."""
        self._storage.upload_bytes(organ_mesh_path(study_code), organ_mesh, CONTENT_TYPE_MESH)

    def has_view(self, study_code: str) -> bool:
        """True si el estudio tiene datos del visor (lo reconstruyo X2CT-GAN)."""
        return self._storage.exists(radiograph_output_path(study_code, VIEW_FILE))

    def read_view(self, study_code: str) -> dict[str, Any]:
        """Los datos del visor: voxel, si las medidas son relativas y los avisos."""
        return json.loads(self.read_file(study_code, VIEW_FILE))

    def read_file(self, study_code: str, file_name: str) -> bytes:
        """Bytes de uno de los archivos de la reconstruccion."""
        if file_name not in RADIOGRAPH_OUTPUT_FILES:
            raise ValueError(f"'{file_name}' no es un archivo de la reconstruccion.")
        return self._storage.download_bytes(radiograph_output_path(study_code, file_name))
