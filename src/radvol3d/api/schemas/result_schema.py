"""Forma de la respuesta del resultado de un estudio (data-model.md §5).

Las direcciones son rutas del propio servicio, nunca del bucket. Cada lesion se
identifica por su posicion en la lista (lesion_number, desde 1): ni region_id ni el
id interno de la base salen por la API.
"""

from pydantic import BaseModel, Field

from radvol3d.domain.enums import OrganName


class LesionResponse(BaseModel):
    """Una lesion detectada, con la direccion de su malla."""

    lesion_number: int = Field(ge=1, description="Posicion en la lista, desde 1")
    organ: OrganName | None = Field(
        description="Organo de la lesion (columna lesion.organ; nunca vacio tras la migracion 002)"
    )
    location: str = Field(description="Posicion geometrica dentro del volumen")
    volume_mm3: float = Field(description="Volumen en milimetros cubicos")
    max_diameter_mm: float | None = Field(default=None, description="Diametro maximo en mm")
    confidence: float = Field(ge=0, le=1, description="Confianza media de la region")
    mesh_url: str = Field(description="Donde descargar la malla .glb de la lesion")


class ResultResponse(BaseModel):
    """El resultado de un estudio completed."""

    study_code: str = Field(description="Codigo del estudio")
    organ_mesh_url: str = Field(description="Malla .glb del organo")
    tumor_mesh_url: str = Field(description="Malla .glb con todas las lesiones juntas")
    volume_url: str = Field(description="Volumen reconstruido (.npy)")
    lesions: list[LesionResponse] = Field(description="Lesiones detectadas")
