"""Forma de las peticiones y respuestas del historial (funcionalidad 005).

Es la unica respuesta de la API que lleva un dato personal: national_id, el DNI del
paciente (research.md R8 de 005, excepcion acotada a FR-029 de 004). Nombre y apellido
no tienen campo, asi que no pueden salir por error.

El DNI del filtro llega en el cuerpo de StudySearchRequest y nunca en la URL: el
registro de acceso de uvicorn guarda la ruta con su query string (research.md R1).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radvol3d.domain.entities import StudyHistoryPage
from radvol3d.domain.enums import OrganName, StudyStatus

HISTORY_DEFAULT_LIMIT = 50
HISTORY_MAX_LIMIT = 100


class StudyHistoryItem(BaseModel):
    """Un estudio del historial."""

    study_code: str = Field(description="Codigo del estudio")
    organ: OrganName = Field(description="Organo estudiado")
    status: StudyStatus = Field(description="Estado actual del procesamiento")
    created_at: datetime | None = Field(default=None, description="Fecha de creacion")
    lesion_count: int | None = Field(
        default=None, description="Numero de lesiones; solo en un estudio completed"
    )
    total_lesion_volume_mm3: float | None = Field(
        default=None,
        description="Suma del volumen de las lesiones en mm3; solo en un estudio completed",
    )
    national_id: str | None = Field(default=None, description="DNI del paciente, si lo tiene")


class StudyHistoryResponse(BaseModel):
    """Una pagina del historial, del mas reciente al mas antiguo."""

    items: list[StudyHistoryItem] = Field(description="Estudios de esta pagina")
    offset: int = Field(description="Posicion del primer estudio de la pagina")
    limit: int = Field(description="Tamano maximo de la pagina")
    has_more: bool = Field(description="Si hay mas estudios despues de esta pagina")


class StudySearchRequest(BaseModel):
    """Busqueda de los estudios de un paciente por su DNI.

    hide_input_in_errors quita el valor recibido del texto de ValidationError, para
    que un DNI mal escrito no llegue a un registro ni a una traza.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    national_id: str = Field(pattern=r"^[0-9]{8}$", description="DNI de ocho digitos")
    offset: int = Field(default=0, ge=0, description="Posicion del primer estudio")
    limit: int = Field(
        default=HISTORY_DEFAULT_LIMIT,
        ge=1,
        le=HISTORY_MAX_LIMIT,
        description="Tamano maximo de la pagina",
    )

    @field_validator("national_id", mode="before")
    @classmethod
    def strip_spaces(cls, value: object) -> object:
        """Quita los espacios de los extremos antes de validar el formato."""
        return value.strip() if isinstance(value, str) else value


def history_response(page: StudyHistoryPage) -> StudyHistoryResponse:
    """Pasa una pagina del dominio a la respuesta de la API."""
    return StudyHistoryResponse(
        items=[
            StudyHistoryItem(
                study_code=entry.study_code,
                organ=entry.organ,
                status=entry.status,
                created_at=entry.created_at,
                lesion_count=entry.lesion_count,
                total_lesion_volume_mm3=entry.total_lesion_volume_mm3,
                national_id=entry.national_id,
            )
            for entry in page.entries
        ],
        offset=page.offset,
        limit=page.limit,
        has_more=page.has_more,
    )
