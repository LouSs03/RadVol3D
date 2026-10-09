"""Forma de la respuesta del endpoint de estado."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Estado del servicio y parametros con los que trabaja."""

    status: str = Field(description="ok si el servicio responde")
    version: str = Field(description="Version del paquete")
    grid_size: int = Field(description="Lado de la rejilla del volumen, en voxeles")
    mm_per_voxel: float = Field(description="Tamano del voxel en milimetros")
    projection_angles: list[int] = Field(description="Angulos de las proyecciones")
