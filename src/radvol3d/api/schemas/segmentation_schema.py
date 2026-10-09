"""Forma de la respuesta de la segmentacion.

Las claves de LesionResponse coinciden con las columnas de la tabla lesion, para
que el resultado viaje sin traducirse entre capas.
"""

from pydantic import BaseModel, Field


class LesionResponse(BaseModel):
    """Una region con lesion detectada."""

    location: str = Field(description="Posicion geometrica dentro del volumen")
    volume_mm3: float = Field(description="Volumen de la lesion en milimetros cubicos")
    confidence: float = Field(ge=0.0, le=1.0, description="Confianza media de la region")
    max_diameter_mm: float | None = Field(default=None, description="Diametro maximo")


class SegmentationResponse(BaseModel):
    """Resultado completo de la segmentacion de un estudio."""

    study_code: str = Field(description="Identificador del estudio")
    has_lesion: bool = Field(description="Si se detecto alguna lesion")
    global_confidence: float = Field(ge=0.0, le=1.0, description="Confianza global")
    lesions: list[LesionResponse] = Field(default_factory=list)
