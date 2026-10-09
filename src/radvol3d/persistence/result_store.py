"""Guarda y consulta los resultados de la segmentacion de un estudio.

Un resultado son cinco archivos del bucket (mascara, probabilidad, resumen y las
mallas del organo y del tumor), mas una malla por lesion, y las filas de lesion. Cada
fila apunta a su propia malla en mesh_path: es el unico enlace entre la fila y su
malla (research.md R10 de 004). El organo de cada fila lo pone el insert, desde el
estudio.

Orden de save_result (research.md R8 y R12 de 001; R7 de 002; R10 de 004):

1. Se valida TODO sin tocar nada: el codigo, el resumen, las lesiones y que haya
   exactamente una malla por lesion.
2. Se comprueba que el estudio existe, en una transaccion corta que suelta la
   conexion antes de subir nada. Asi no se acumulan archivos de un estudio inexistente.
3. Se suben los cinco archivos y las mallas de las lesiones.
4. En UNA sola unidad de trabajo se insertan las lesiones.

save_result NO cambia el estado de las etapas ni registra el modelo: eso lo hace la
tuberia con ProcessingProgressStore, que cierra la etapa 3 al terminar la
segmentacion y la etapa 4 despues de este guardado. Si save_result cerrara la etapa
3, pisaria su hora de fin con la del final de la etapa 4.

Un estudio "tiene resultado" cuando sus etapas 3 y 4 estan en completed. Como la
etapa 4 se cierra despues de guardar, el resultado aparece entero o no aparece: los
archivos de un guardado fallido quedan sueltos en el bucket, pero get_result no los
cuenta. Quien guarda un resultado por segunda vez sobre el mismo estudio duplica las
filas de lesion; para rehacerlo, se borra el estudio.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from radvol3d.domain.entities import Lesion, StoredResult
from radvol3d.domain.enums import ResultFile, StageNumber, StageStatus
from radvol3d.domain.exceptions import (
    InvalidLesionError,
    PersistenceError,
    StorageObjectNotFoundError,
)
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_MESH,
    ObjectStorage,
)
from radvol3d.persistence.repositories.lesion_repository import (
    LesionRepository,
    validate_lesions,
)
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from radvol3d.persistence.repositories.study_repository import find_study_id
from radvol3d.persistence.storage_layout import (
    lesion_mesh_path,
    mask_path,
    organ_mesh_path,
    probability_path,
    summary_path,
    tumor_mesh_path,
    validate_study_code,
    volume_path,
)

# Claves que debe traer cada region del resumen para poder guardarla como lesion.
_REQUIRED_REGION_KEYS = ("location", "volume_mm3", "confidence")


class ResultStore:
    """Guarda y consulta los resultados de segmentacion de los estudios."""

    def __init__(self, database: Database, storage: ObjectStorage) -> None:
        self._database = database
        self._storage = storage

    def save_result(
        self,
        study_code: str,
        mask: np.ndarray,
        probability: np.ndarray,
        summary: Mapping[str, Any],
        organ_mesh: bytes,
        tumor_mesh: bytes,
        lesion_meshes: Sequence[bytes],
    ) -> StoredResult:
        """Guarda los archivos del resultado, una malla por lesion y las lesiones.

        lesion_meshes trae una malla por region con lesion, en el orden del resumen.
        No toca las etapas.
        """
        validate_study_code(study_code)
        lesions = self._lesions_from_summary(summary, study_code)
        if len(lesion_meshes) != len(lesions):
            raise PersistenceError(
                f"El resultado trae {len(lesion_meshes)} mallas de lesion para "
                f"{len(lesions)} lesiones."
            )
        self._model_of(summary)
        summary_bytes = self._summary_as_json(summary)

        # Comprobacion previa: termina (y suelta la conexion) antes de la subida lenta.
        with self._database.transaction() as connection:
            find_study_id(connection, study_code)

        self._storage.upload_array(mask_path(study_code), mask)
        self._storage.upload_array(probability_path(study_code), probability)
        self._storage.upload_bytes(summary_path(study_code), summary_bytes, CONTENT_TYPE_JSON)
        self._storage.upload_bytes(organ_mesh_path(study_code), organ_mesh, CONTENT_TYPE_MESH)
        self._storage.upload_bytes(tumor_mesh_path(study_code), tumor_mesh, CONTENT_TYPE_MESH)
        for lesion, mesh in zip(lesions, lesion_meshes, strict=True):
            self._storage.upload_bytes(lesion.mesh_path, mesh, CONTENT_TYPE_MESH)

        with self._database.transaction() as connection:
            lesion_repository = LesionRepository(connection)
            lesion_repository.add_many(study_code, lesions)
            saved = lesion_repository.list_by_study(study_code)
        return self._build_result(study_code, saved)

    def get_result(self, study_code: str) -> StoredResult:
        """Devuelve el resultado del estudio.

        Si el estudio existe pero todavia no tiene resultado (por ejemplo, porque se
        esta procesando), devuelve un resultado VACIO: rutas en None y lesiones vacias.
        No lanza error, porque la interfaz consulta mientras el estudio se procesa.
        Solo lanza StudyNotFoundError si el estudio no existe. No consulta el bucket.
        """
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            find_study_id(connection, study_code)
            stages = ProcessingStageRepository(connection).list_by_study(study_code)
            status = {stage.stage_number: stage.status for stage in stages}
            if not (
                status.get(StageNumber.SEGMENTATION) is StageStatus.COMPLETED
                and status.get(StageNumber.MESHING) is StageStatus.COMPLETED
            ):
                return StoredResult(study_code)
            lesions = LesionRepository(connection).list_by_study(study_code)
        return self._build_result(study_code, lesions)

    def read_file(self, study_code: str, file: ResultFile) -> bytes:
        """Baja la malla del organo, la del tumor o el volumen (.npy tal cual).

        No comprueba el estado del estudio: eso lo hace el servicio.
        """
        paths = {
            ResultFile.ORGAN_MESH: organ_mesh_path,
            ResultFile.TUMOR_MESH: tumor_mesh_path,
            ResultFile.VOLUME: volume_path,
        }
        return self._storage.download_bytes(paths[ResultFile(file)](study_code))

    def read_lesion_mesh(self, study_code: str, lesion_number: int) -> bytes:
        """Baja la malla de la lesion numero lesion_number (desde 1, en orden de guardado).

        Lanza StorageObjectNotFoundError si el estudio no tiene esa lesion.
        """
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            lesions = LesionRepository(connection).list_by_study(study_code)
        if not 1 <= lesion_number <= len(lesions) or lesions[lesion_number - 1].mesh_path is None:
            raise StorageObjectNotFoundError(
                f"El estudio '{study_code}' no tiene la lesion {lesion_number}."
            )
        return self._storage.download_bytes(lesions[lesion_number - 1].mesh_path)

    @staticmethod
    def _build_result(study_code: str, lesions: list[Lesion]) -> StoredResult:
        return StoredResult(
            study_code=study_code,
            lesions=lesions,
            volume_path=volume_path(study_code),
            mask_path=mask_path(study_code),
            probability_path=probability_path(study_code),
            summary_path=summary_path(study_code),
            organ_mesh_path=organ_mesh_path(study_code),
            tumor_mesh_path=tumor_mesh_path(study_code),
        )

    @staticmethod
    def _lesions_from_summary(summary: Mapping[str, Any], study_code: str) -> list[Lesion]:
        """Cada region del resumen genera una lesion (FR-047a), con su propia malla.

        La lesion n (desde 1, en el orden del resumen) apunta a lesion_<nnn>.glb.

        Las claves region_id, confidence_min, confidence_max, voxels y centroid_voxel
        no tienen columna en lesion: se quedan solo en summary.json. Una region con
        has_lesion distinto de true se ignora; el segmentador no las envia.
        """
        regions = summary.get("regions") if isinstance(summary, Mapping) else None
        if not isinstance(regions, list):
            raise InvalidLesionError("El resumen debe traer la lista de regiones (regions).")

        lesions: list[Lesion] = []
        for region in regions:
            if not isinstance(region, Mapping):
                raise InvalidLesionError("Cada region del resumen debe ser un objeto.")
            if region.get("has_lesion", True) is not True:
                continue
            missing = [key for key in _REQUIRED_REGION_KEYS if key not in region]
            if missing:
                raise InvalidLesionError(f"Una region del resumen no trae: {', '.join(missing)}.")
            lesions.append(
                Lesion(
                    location=region["location"],
                    volume_mm3=region["volume_mm3"],
                    confidence=region["confidence"],
                    max_diameter_mm=region.get("max_diameter_mm"),
                    mesh_path=lesion_mesh_path(study_code, len(lesions) + 1),
                )
            )
        validate_lesions(lesions)
        return lesions

    @staticmethod
    def _model_of(summary: Mapping[str, Any]) -> tuple[str, str]:
        """Nombre y version del modelo de segmentacion, tal como los trae el resumen.

        El resumen debe traerlos aunque save_result ya no registre el modelo: son la
        trazabilidad de summary.json.
        """
        name, version = summary.get("model_name"), summary.get("model_version")
        for value in (name, version):
            if not isinstance(value, str) or not value.strip():
                raise PersistenceError(
                    "El resumen de segmentacion debe traer model_name y model_version."
                )
        return name, version

    @staticmethod
    def _summary_as_json(summary: Mapping[str, Any]) -> bytes:
        """El resumen tal como llego: mismas claves, mismo orden, sin escapar los acentos."""
        try:
            return json.dumps(summary, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise PersistenceError(
                "El resumen de segmentacion no se puede escribir como JSON."
            ) from None
