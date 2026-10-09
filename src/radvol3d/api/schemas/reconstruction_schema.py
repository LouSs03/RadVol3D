"""Forma de la respuesta de la reconstruccion."""

from pydantic import BaseModel, Field


class ReconstructionResponse(BaseModel):
    """Resultado de reconstruir un volumen."""

    study_code: str = Field(description="Identificador del estudio")
    grid_size: int = Field(description="Lado del volumen reconstruido")
    elapsed_sec: float = Field(description="Tiempo de reconstruccion en segundos")
    model_name: str = Field(description="Modelo usado")
    model_version: str = Field(description="Version del modelo usado")
