"""Registra el avance del procesamiento de un estudio: su estado, sus etapas y sus modelos.

Cada metodo es una unidad de trabajo completa: abre una sola transaccion y combina
los repositorios que ya existen. Asi la capa de servicios avanza la tuberia sin
manejar conexiones (research.md R9 de la funcionalidad 002).

Cuando una etapa o el estudio se cierran con un modelo, primero se registra el
modelo en el catalogo (get_or_create): set_status y mark_completed exigen que el
modelo ya exista.
"""

from datetime import date
from typing import Any

from radvol3d.domain.entities import Model, ProcessingStage
from radvol3d.domain.enums import StageNumber, StageStatus, StudyStatus
from radvol3d.domain.exceptions import PersistenceError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.repositories.model_repository import ModelRepository
from radvol3d.persistence.repositories.processing_stage_repository import (
    ProcessingStageRepository,
)
from radvol3d.persistence.repositories.study_repository import StudyRepository
from radvol3d.persistence.storage_layout import validate_study_code


class ProcessingProgressStore:
    """Cambia el estado del estudio y de sus etapas, una unidad de trabajo por llamada."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def start_processing(self, study_code: str) -> None:
        """Pone el estudio en processing."""
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            StudyRepository(connection).update_status(study_code, StudyStatus.PROCESSING)

    def start_stage(self, study_code: str, stage: StageNumber) -> None:
        """Pone la etapa en running y registra su hora de inicio."""
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            ProcessingStageRepository(connection).set_status(
                study_code, stage, StageStatus.RUNNING
            )

    def complete_stage(
        self,
        study_code: str,
        stage: StageNumber,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        """Pone la etapa en completed y, si se indica, enlaza el modelo que la ejecuto."""
        validate_study_code(study_code)
        if (model_name is None) != (model_version is None):
            raise PersistenceError("El modelo de la etapa necesita nombre y version.")
        with self._database.transaction() as connection:
            model = None
            if model_name is not None and model_version is not None:
                model = ModelRepository(connection).get_or_create(model_name, model_version)
            ProcessingStageRepository(connection).set_status(
                study_code, stage, StageStatus.COMPLETED, model
            )

    def fail_from_stage(self, study_code: str, stage: StageNumber) -> None:
        """La etapa fallo: queda en failed, las siguientes en skipped y el estudio en failed.

        Todo en una sola unidad de trabajo, para que nunca quede un estudio en failed
        con etapas todavia en waiting o running.
        """
        validate_study_code(study_code)
        failed = StageNumber(stage)
        with self._database.transaction() as connection:
            self._fail_from(connection, study_code, failed)

    def fail_interrupted_studies(self) -> list[str]:
        """Pasa a failed los estudios que quedaron en processing y devuelve sus codigos.

        Se llama una vez al arrancar. La tarea en segundo plano que procesaba esos
        estudios murio con el proceso anterior, y sin esto quedarian colgados: no se
        podrian borrar, porque delete_study rechaza los estudios en processing.

        Por cada estudio, en su propia transaccion: la etapa en running (o, si no hay,
        la primera en waiting) pasa a failed, las siguientes a skipped y el estudio a
        failed. Supone un solo proceso de uvicorn (research.md R4 y R5 de la
        funcionalidad 004): con varios, marcaria como fallidos estudios que otro
        proceso sigue procesando.
        """
        with self._database.transaction() as connection:
            codes = StudyRepository(connection).list_codes_by_status(StudyStatus.PROCESSING)

        recovered: list[str] = []
        for study_code in codes:
            with self._database.transaction() as connection:
                if StudyRepository(connection).lock_status(study_code) is not (
                    StudyStatus.PROCESSING
                ):
                    continue
                stages = ProcessingStageRepository(connection).list_by_study(study_code)
                interrupted = self._interrupted_stage(stages)
                if interrupted is None:
                    StudyRepository(connection).update_status(study_code, StudyStatus.FAILED)
                else:
                    self._fail_from(connection, study_code, interrupted)
            recovered.append(study_code)
        return recovered

    @staticmethod
    def _interrupted_stage(stages: list[ProcessingStage]) -> StageNumber | None:
        """La etapa en running o, si no hay, la primera en waiting."""
        for wanted in (StageStatus.RUNNING, StageStatus.WAITING):
            for stage in stages:
                if stage.status is wanted:
                    return stage.stage_number
        return None

    @staticmethod
    def _fail_from(connection: Any, study_code: str, failed: StageNumber) -> None:
        """La etapa queda en failed, las siguientes en skipped y el estudio en failed."""
        stages = ProcessingStageRepository(connection)
        stages.set_status(study_code, failed, StageStatus.FAILED)
        for later in StageNumber:
            if later.value > failed.value:
                stages.set_status(study_code, later, StageStatus.SKIPPED)
        StudyRepository(connection).update_status(study_code, StudyStatus.FAILED)

    def complete_study(
        self,
        study_code: str,
        model_name: str,
        model_version: str,
        grid_size: int,
        total_time_sec: float,
    ) -> None:
        """Cierra el estudio en completed con su modelo, su rejilla y su tiempo total."""
        validate_study_code(study_code)
        with self._database.transaction() as connection:
            model = ModelRepository(connection).get_or_create(model_name, model_version)
            StudyRepository(connection).mark_completed(
                study_code, model, grid_size, total_time_sec
            )

    def register_model(
        self,
        model_name: str,
        version: str,
        trained_on: date | None = None,
        description: str | None = None,
    ) -> Model:
        """Registra el modelo en el catalogo. La fecha de entrenamiento nunca se estima."""
        with self._database.transaction() as connection:
            return ModelRepository(connection).get_or_create(
                model_name, version, trained_on, description
            )
