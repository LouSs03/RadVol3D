"""Guarda y lee los metadatos de un estudio.

Los metadatos son todo lo que la base guarda sobre un estudio: paciente, estudio,
proyecciones, etapas y lesiones. Los binarios van al bucket y la base solo guarda sus rutas.

Orden de register_study (research.md R8): primero se insertan el paciente y el
estudio, y SOLO despues se suben los archivos. Asi un codigo repetido falla antes de
tocar el bucket y no pisa los archivos del estudio original. Si algo falla despues
de subir, la transaccion se revierte y los archivos quedan sueltos en el bucket,
pero sin fila que los registre; como las rutas son deterministas, reintentar con el
mismo codigo los reemplaza.

Flujo en tres pasos de la funcionalidad 004 (research.md R2 y R3):

- create_study: paciente, estudio en pending y sus cuatro etapas, sin subir nada.
- add_projections: bloquea la fila del estudio, exige pending y cero proyecciones, y
  solo entonces sube y registra las cuatro. Si algo falla, nada queda registrado.
- claim_for_processing: bloquea la fila, exige pending y cuatro proyecciones, y pasa el
  estudio a processing en la misma transaccion. Con el bloqueo, de dos pedidos
  simultaneos solo uno lo reclama: el otro espera, ve processing y se rechaza.

register_study es create_study + add_projections en una sola transaccion.

Orden de delete_study (research.md R8 de la funcionalidad 002): todo dentro de una
transaccion. Se bloquea la fila del estudio, se comprueba que no se este procesando,
se borra la fila (lo demas cae en cascada) y despues se borran sus archivos del
bucket: las diez rutas fijas mas las mallas de lesion (lesion_<NNN>.glb) que haya en
<study_code>/meshes. Esas se listan en el bucket y no se leen de las filas de lesion,
para limpiar tambien las de un guardado que fallo antes de insertarlas (research.md
R12 de 004). Si el bucket falla, la transaccion se revierte: el estudio sigue en pie
y el borrado se puede reintentar.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from radvol3d import config
from radvol3d.domain.entities import PatientDetails, Projection, Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.domain.exceptions import (
    InvalidProjectionError,
    InvalidStudyStateError,
    StudyInProgressError,
)
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

# Nombre de las mallas de lesion (storage_layout.lesion_mesh_path).
LESION_MESH_NAME = re.compile(r"lesion_[0-9]{3,}\.glb")


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
            self._insert_study(connection, study_code, organ_name, patient)
            self._store_projections(connection, study_code, uploads)
            ProcessingStageRepository(connection).prepare_stages(study_code)
            return self._load(connection, study_code)

    def create_study(
        self,
        study_code: str,
        organ: OrganName | str,
        patient: PatientDetails | None = None,
    ) -> Study:
        """Registra un estudio en pending con sus cuatro etapas, todavia sin proyecciones.

        No sube nada al bucket. Valida el codigo y el organo antes de tocar la base.
        """
        validate_study_code(study_code)
        organ_name = parse_organ_name(organ)
        with self._database.transaction() as connection:
            self._insert_study(connection, study_code, organ_name, patient)
            ProcessingStageRepository(connection).prepare_stages(study_code)
            return self._load(connection, study_code)

    def add_projections(self, study_code: str, projections: list[ProjectionUpload]) -> Study:
        """Sube y registra las cuatro proyecciones de un estudio en pending que no tiene.

        Lanza InvalidStudyStateError, sin subir nada, si el estudio no esta en pending
        o ya tiene proyecciones. Para cambiarlas, se borra el estudio y se crea de nuevo.
        """
        validate_study_code(study_code)
        uploads = self._validated_uploads(study_code, projections)
        with self._database.transaction() as connection:
            status = StudyRepository(connection).lock_status(study_code)
            if status is not StudyStatus.PENDING:
                raise InvalidStudyStateError(
                    f"El estudio '{study_code}' esta en {status.value}: solo se suben "
                    "proyecciones a un estudio en pending."
                )
            if ProjectionRepository(connection).count_by_study(study_code) > 0:
                raise InvalidStudyStateError(
                    f"El estudio '{study_code}' ya tiene sus proyecciones. Para cambiarlas, "
                    "borra el estudio y crealo de nuevo."
                )
            self._store_projections(connection, study_code, uploads)
            return self._load(connection, study_code)

    def claim_for_processing(
        self,
        study_code: str,
        check_organ: Callable[[OrganName], object] | None = None,
    ) -> None:
        """Pasa a processing un estudio en pending con sus cuatro proyecciones.

        Lanza InvalidStudyStateError si no cumple. El bloqueo de la fila hace que, de
        dos pedidos simultaneos, solo uno reclame el estudio.

        check_organ recibe el organo del estudio dentro de la transaccion, antes de
        cambiar el estado: si lanza (por ejemplo, ModelNotAvailableError), la
        transaccion se revierte y el estudio sigue en pending. Asi la comprobacion del
        modelo no cuesta una lectura aparte del estudio.
        """
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            studies = StudyRepository(connection)
            status, organ = studies.lock_for_claim(study_code)
            if status is not StudyStatus.PENDING:
                raise InvalidStudyStateError(
                    f"El estudio '{study_code}' esta en {status.value}: solo se procesa un "
                    "estudio en pending."
                )
            count = ProjectionRepository(connection).count_by_study(study_code)
            expected = len(config.PROJECTION_ANGLES)
            if count != expected:
                raise InvalidStudyStateError(
                    f"El estudio '{study_code}' tiene {count} de {expected} proyecciones: "
                    "sube las cuatro antes de procesarlo."
                )
            if check_organ is not None:
                check_organ(organ)
            studies.update_status(study_code, StudyStatus.PROCESSING)

    def load_projections(self, study_code: str) -> dict[int, np.ndarray]:
        """Baja del bucket las cuatro proyecciones del estudio, por angulo."""
        validate_study_code(study_code)
        return {
            angle: self._storage.download_array(projection_path(study_code, angle))
            for angle in config.PROJECTION_ANGLES
        }

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
            self._storage.remove_many(
                self._study_files(study_code) + self._lesion_mesh_files(study_code)
            )

    def list_studies(self) -> list[Study]:
        """Devuelve los estudios del mas reciente al mas antiguo, sin datos anidados."""
        with self._database.transaction() as connection:
            return StudyRepository(connection).list_recent()

    @staticmethod
    def _insert_study(
        connection: Any,
        study_code: str,
        organ_name: OrganName,
        patient: PatientDetails | None,
    ) -> None:
        """Inserta el paciente (o reutiliza el de referencia) y el estudio en pending."""
        patient_entity = PatientRepository(connection).find_or_create(patient)
        StudyRepository(connection).create(study_code, organ_name, patient_entity.patient_code)

    def _store_projections(
        self,
        connection: Any,
        study_code: str,
        uploads: list[tuple[ProjectionUpload, str]],
    ) -> None:
        """Sube cada proyeccion y despues registra sus filas."""
        for upload, path in uploads:
            self._storage.upload_array(path, upload.array)
        ProjectionRepository(connection).add_many(
            study_code,
            [Projection(u.angle_degrees, path, u.original_name) for u, path in uploads],
        )

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

    def _lesion_mesh_files(self, study_code: str) -> list[str]:
        """Las mallas de lesion que hay en el bucket para el estudio."""
        folder = f"{study_code}/meshes"
        return [
            f"{folder}/{name}"
            for name in self._storage.list_names(folder)
            if LESION_MESH_NAME.fullmatch(name)
        ]

    @staticmethod
    def _study_files(study_code: str) -> list[str]:
        """Las diez rutas fijas que puede tener un estudio en el bucket."""
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
