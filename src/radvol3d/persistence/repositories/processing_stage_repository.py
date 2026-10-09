"""Acceso a la tabla processing_stage.

Las cuatro etapas de la tuberia, una fila por etapa y estudio. Permiten saber hasta
donde llego un estudio que fallo a mitad de camino. El nombre de cada etapa
(stage_name) se deriva de su numero con los nombres del dominio: preprocessing,
reconstruction, segmentation y meshing.
"""

from typing import Any

from radvol3d.domain.entities import Model, ProcessingStage
from radvol3d.domain.enums import StageNumber, StageStatus
from radvol3d.domain.exceptions import PersistenceError
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.row_mapping import model_from_row
from radvol3d.persistence.repositories.study_repository import find_study_id
from radvol3d.persistence.storage_layout import validate_study_code


class ProcessingStageRepository:
    """Prepara y consulta las etapas dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def prepare_stages(self, study_code: str) -> None:
        """Crea las cuatro etapas del estudio en waiting. Repetir la operacion no duplica filas.

        El estado inicial lo pone el valor por defecto de la columna stage_status.
        """
        study_id = find_study_id(self._connection, study_code)
        for stage in StageNumber:
            execute_translated(
                self._connection,
                "insert into processing_stage (study_id, stage_number, stage_name) "
                "values (%s, %s, %s) "
                "on conflict (study_id, stage_number) do nothing",
                (study_id, stage.value, stage.name.lower()),
            )

    def set_status(
        self,
        study_code: str,
        stage_number: StageNumber | int,
        status: StageStatus | str,
        model: Model | None = None,
    ) -> None:
        """Cambia el estado de una etapa y registra la hora que corresponda.

        - running: registra started_at.
        - completed, skipped y failed: registran finished_at.
        - waiting: no registra ninguna hora.

        Nunca se inventa started_at: una etapa que termina sin haber empezado (por
        ejemplo, skipped) queda con la hora de inicio vacia. Si se indica el modelo
        que ejecuto la etapa, tambien se registra.

        Importante: la hora de fin anterior a la de inicio se detecta DESPUES de
        escribir (con returning) y se rechaza con PersistenceError. Esa excepcion es
        lo que deshace el cambio, pero solo si quien llama la deja propagar fuera del
        bloque Database.transaction(): si la captura dentro del bloque, la
        transaccion se confirma igual y la fila queda con las horas invertidas.
        """
        validate_study_code(study_code)
        try:
            number = StageNumber(stage_number)
        except ValueError:
            raise PersistenceError("El numero de etapa debe estar entre 1 y 4.") from None
        try:
            stage_status = StageStatus(status)
        except ValueError:
            raise PersistenceError(
                "El estado de la etapa debe ser waiting, running, completed, skipped o failed."
            ) from None

        assignments = ["stage_status = %s"]
        if stage_status is StageStatus.RUNNING:
            assignments.append("started_at = now()")
        elif stage_status in (StageStatus.COMPLETED, StageStatus.SKIPPED, StageStatus.FAILED):
            assignments.append("finished_at = now()")

        params: list[object] = [stage_status.value, study_code, number.value]
        sources = "study s"
        conditions = "ps.study_id = s.study_id and s.study_code = %s and ps.stage_number = %s"
        if model is not None:
            assignments.append("model_id = m.model_id")
            sources += ", model m"
            conditions += " and m.model_name = %s and m.version = %s"
            params += [model.model_name, model.version]

        row = execute_translated(
            self._connection,
            f"update processing_stage ps set {', '.join(assignments)} "
            f"from {sources} where {conditions} "
            "returning ps.started_at, ps.finished_at",
            tuple(params),
        ).fetchone()
        if row is None:
            # Si el estudio no existe, find_study_id lanza StudyNotFoundError.
            find_study_id(self._connection, study_code)
            raise PersistenceError(
                "No se pudo actualizar la etapa: no esta preparada o el modelo no esta registrado."
            )
        started_at, finished_at = row["started_at"], row["finished_at"]
        if started_at is not None and finished_at is not None and finished_at < started_at:
            raise PersistenceError(
                "La hora de fin de la etapa no puede ser anterior a la de inicio."
            )

    def list_by_study(self, study_code: str) -> list[ProcessingStage]:
        """Devuelve las etapas del estudio ordenadas por numero."""
        validate_study_code(study_code)
        rows = execute_translated(
            self._connection,
            "select ps.stage_number, ps.stage_status, ps.started_at, ps.finished_at, "
            "m.model_name, m.version, m.trained_on, m.description "
            "from processing_stage ps "
            "join study s on s.study_id = ps.study_id "
            "left join model m on m.model_id = ps.model_id "
            "where s.study_code = %s order by ps.stage_number",
            (study_code,),
        ).fetchall()
        return [
            ProcessingStage(
                stage_number=StageNumber(row["stage_number"]),
                status=StageStatus(row["stage_status"]),
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                model=model_from_row(row),
            )
            for row in rows
        ]
