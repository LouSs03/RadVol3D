"""Guarda y lee los metadatos de un estudio.

Los metadatos son todo lo que la base guarda sobre un estudio: paciente, estudio,
proyecciones, etapas y lesiones. Los binarios van al bucket y la base solo guarda sus rutas.

Orden de register_study (research.md R8): primero se insertan el paciente y el
estudio, y SOLO despues se suben los archivos. Asi un codigo repetido falla antes de
tocar el bucket y no pisa los archivos del estudio original. Si algo falla despues
de subir, la transaccion se revierte y los archivos quedan sueltos en el bucket,
pero sin fila que los registre; como las rutas son deterministas, reintentar con el
mismo codigo los reemplaza.

Orden de delete_study (research.md R8 de la funcionalidad 002): todo dentro de una
transaccion. Se bloquea la fila del estudio, se comprueba que no se este procesando,
se borra la fila (lo demas cae en cascada) y despues se borran sus diez archivos del
bucket. Si el bucket falla, la transaccion se revierte: el estudio sigue en pie y el
borrado se puede reintentar.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

from radvol3d import config
from radvol3d.domain.entities import PatientDetails, Projection, Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import InvalidProjectionError, StudyInProgressError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.repositories.lesion_repository import LesionRepository
from radvol3d.persistence.repositories.organ_repository import parse_organ_name
from radvol3d.persistence.repositories.patient_repository import PatientRepository
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from radvol3d.persistence.repositories.projection_repository import ProjectionRepository
from radvol3d.persistence.repositories.study_repository import (
    StudyRepository,
    find_study_id,
)
from radvol3d.persistence.storage_layout import (
    mask_path,
    organ_mesh_path,
    probability_path,
    projection_path,
    summary_path,
    tumor_mesh_path,
    validate_projection_angle,
    validate_study_code,
    volume_path,
)


@dataclass(frozen=True, eq=False)
class ProjectionUpload:
    """Una proyeccion que llega para registrar: su angulo, sus datos y su nombre original."""

    angle_degrees: int
    array: np.ndarray
    original_name: str | None = None


class StudyMetadataStore:
    """Coordina la base y el bucket para registrar y leer estudios."""

    def __init__(self, database: Database, storage: ObjectStorage) -> None:
        self._database = database
        self._storage = storage

    def register_study(
        self,
        study_code: str,
        organ: OrganName | str,
        projections: list[ProjectionUpload],
        patient: PatientDetails | None = None,
    ) -> Study:
        """Registra un estudio con su paciente, sus cuatro proyecciones y sus cuatro etapas.

        Todo ocurre en una sola unidad de trabajo: o queda registrado completo o no
        queda registrado. Valida las entradas antes de tocar la base o el bucket.
        """
        validate_study_code(study_code)
        organ_name = parse_organ_name(organ)
        uploads = self._validated_uploads(study_code, projections)

        with self._database.transaction() as connection:
            patient_entity = PatientRepository(connection).find_or_create(patient)
            StudyRepository(connection).create(study_code, organ_name, patient_entity.patient_code)
            for upload, path in uploads:
                self._storage.upload_array(path, upload.array)
            ProjectionRepository(connection).add_many(
                study_code,
                [Projection(u.angle_degrees, path, u.original_name) for u, path in uploads],
            )
            ProcessingStageRepository(connection).prepare_stages(study_code)
            return self._load(connection, study_code)

    def get_study(self, study_code: str) -> Study:
        """Devuelve el estudio con su paciente, proyecciones y etapas."""
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            return self._load(connection, study_code)

    def save_volume(self, study_code: str, volume: np.ndarray) -> str:
        """Guarda el volumen reconstruido en <study_code>/volume.npy y devuelve la ruta.

        Comprueba que el estudio existe ANTES de subir nada: si no existe, lanza
        StudyNotFoundError. Un volumen es grande y el bucket es gratuito y limitado,
        asi que no se aceptan archivos sin estudio.

        La comprobacion termina (y suelta la conexion) antes de la subida, que es la
        parte lenta. Si ya habia un volumen, lo reemplaza. La base no guarda el
        volumen ni su ruta: solo se lee de ella.
        """
        path = volume_path(study_code)
        with self._database.transaction() as connection:
            find_study_id(connection, study_code)
        self._storage.upload_array(path, volume)
        return path

    def delete_study(self, study_code: str) -> None:
        """Borra el estudio con sus filas y sus archivos. El paciente se conserva.

        Lanza StudyInProgressError si el estudio se esta procesando, sin tocar nada.
        """
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            studies = StudyRepository(connection)
            if studies.lock_status(study_code) is StudyStatus.PROCESSING:
                raise StudyInProgressError(
                    f"El estudio '{study_code}' se esta procesando y no se puede borrar."
                )
            studies.delete(study_code)
            self._storage.remove_many(self._study_files(study_code))

    def list_studies(self) -> list[Study]:
        """Devuelve los estudios del mas reciente al mas antiguo, sin datos anidados."""
        with self._database.transaction() as connection:
            return StudyRepository(connection).list_recent()

    @staticmethod
    def _validated_uploads(
        study_code: str, projections: list[ProjectionUpload]
    ) -> list[tuple[ProjectionUpload, str]]:
        """Exige las cuatro proyecciones, una por angulo, y calcula la ruta de cada una."""
        angles = [validate_projection_angle(u.angle_degrees) for u in projections]
        if len(set(angles)) != len(angles):
            raise InvalidProjectionError("Un angulo de proyeccion no puede repetirse.")
        if set(angles) != set(config.PROJECTION_ANGLES):
            raise InvalidProjectionError(
                "Se necesitan las cuatro proyecciones: 0, 45, 90 y 135 grados."
            )
        return [(u, projection_path(study_code, u.angle_degrees)) for u in projections]

    @staticmethod
    def _study_files(study_code: str) -> list[str]:
        """Las diez rutas que puede tener un estudio en el bucket."""
        return [projection_path(study_code, a) for a in config.PROJECTION_ANGLES] + [
            volume_path(study_code),
            mask_path(study_code),
            probability_path(study_code),
            summary_path(study_code),
            organ_mesh_path(study_code),
            tumor_mesh_path(study_code),
        ]

    @staticmethod
    def _load(connection: Any, study_code: str) -> Study:
        study = StudyRepository(connection).get_by_code(study_code)
        study.projections = ProjectionRepository(connection).list_by_study(study_code)
        study.stages = ProcessingStageRepository(connection).list_by_study(study_code)
        study.lesions = LesionRepository(connection).list_by_study(study_code)
        return study
