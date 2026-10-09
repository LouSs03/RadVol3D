"""Forma de las peticiones y respuestas de estudios (data-model.md §5).

Los datos personales del paciente solo entran (PatientInput). Ninguna respuesta tiene
campos para ellos, asi que no pueden salir por error: a lo sumo sale el codigo de
paciente.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from radvol3d.domain.enums import OrganName, StageStatus, StudyStatus

# El mismo formato que valida la persistencia (storage_layout.STUDY_CODE_PATTERN).
STUDY_CODE_REGEX = r"^[A-Za-z0-9_-]{1,64}$"

StageName = Literal["preprocessing", "reconstruction", "segmentation", "meshing"]


class PatientInput(BaseModel):
    """Datos personales opcionales del paciente. La persistencia los vuelve a validar."""

    first_name: str | None = Field(default=None, max_length=80, description="Nombre")
    last_name: str | None = Field(default=None, max_length=80, description="Apellido")
    national_id: str | None = Field(
        default=None, pattern=r"^[0-9]{8}$", description="DNI de ocho digitos"
    )


class StudyCreate(BaseModel):
    """Peticion para crear un estudio."""

    study_code: str = Field(
        pattern=STUDY_CODE_REGEX,
        description="Codigo del estudio: letras, digitos, guion y guion bajo (hasta 64)",
    )
    organ: OrganName = Field(description="Organo estudiado")
    patient: PatientInput | None = Field(default=None, description="Datos del paciente")


class StudyResponse(BaseModel):
    """Un estudio, sin datos personales del paciente."""

    study_code: str = Field(description="Codigo del estudio")
    organ: OrganName = Field(description="Organo estudiado")
    status: StudyStatus = Field(description="Estado del procesamiento")
    created_at: datetime | None = Field(default=None, description="Fecha de creacion")
    patient_code: str | None = Field(default=None, description="Codigo del paciente")


class StageStatusResponse(BaseModel):
    """Estado de una de las cuatro etapas."""

    stage_number: int = Field(ge=1, le=4, description="Numero de la etapa")
    stage_name: StageName = Field(description="Nombre de la etapa")
    status: StageStatus = Field(description="Estado de la etapa")
    started_at: datetime | None = Field(default=None, description="Inicio")
    finished_at: datetime | None = Field(default=None, description="Fin")


class StudyStatusResponse(StudyResponse):
    """Estado del estudio y de sus cuatro etapas, en orden."""

    total_time_sec: float | None = Field(default=None, description="Tiempo total")
    stages: list[StageStatusResponse] = Field(description="Las cuatro etapas")


class ProcessingAccepted(BaseModel):
    """El procesamiento empezo en segundo plano."""

    study_code: str = Field(description="Codigo del estudio")
    status: StudyStatus = Field(description="processing")
    status_url: str = Field(description="Donde consultar el avance")
