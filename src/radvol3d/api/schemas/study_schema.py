"""Forma de las peticiones y respuestas de estudios."""

from pydantic import BaseModel, Field

from radvol3d.domain.enums import OrganName, StudyStatus


class StudyResponse(BaseModel):
    """Estado de un estudio."""

    study_code: str = Field(description="Identificador del estudio")
    organ: OrganName = Field(description="Organo estudiado")
    status: StudyStatus = Field(description="Estado del procesamiento")
    total_time_sec: float | None = Field(default=None, description="Tiempo total")
