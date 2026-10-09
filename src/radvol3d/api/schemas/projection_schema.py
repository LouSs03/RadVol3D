"""Forma de la respuesta de la subida de proyecciones.

La entrada son cuatro campos de archivo (angle_000 a angle_135) de un formulario
multipart: no tiene esquema de Pydantic (research.md R7).
"""

from pydantic import BaseModel, Field


class ProjectionsUploaded(BaseModel):
    """Las cuatro proyecciones quedaron guardadas."""

    study_code: str = Field(description="Codigo del estudio")
    angles: list[int] = Field(description="Angulos recibidos, en grados")
