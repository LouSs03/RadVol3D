"""Historial de estudios (funcionalidad 005, contracts/http_api_history.md).

El historial sale de la base y no del navegador, asi que es el mismo en cualquier
equipo. GET /studies lista todos los estudios; su URL nunca lleva un DNI, porque el
registro de acceso de uvicorn guarda la ruta con su query string (research.md R1). Para
filtrar por DNI esta POST /studies/search, con el DNI en el cuerpo.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.error_schema import ErrorResponse
from radvol3d.api.schemas.history_schema import (
    HISTORY_DEFAULT_LIMIT,
    HISTORY_MAX_LIMIT,
    StudyHistoryResponse,
    StudySearchRequest,
    history_response,
)
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["historial"])

ERRORS = {
    503: {"model": ErrorResponse, "description": "La base de datos no esta disponible"},
}


@router.get(
    "",
    response_model=StudyHistoryResponse,
    summary="Listar el historial de estudios",
    responses=ERRORS,
)
def list_history(
    service: Annotated[StudyService, Depends(get_study_service)],
    offset: Annotated[int, Query(ge=0, description="Posicion del primer estudio")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=HISTORY_MAX_LIMIT, description="Tamano maximo de la pagina")
    ] = HISTORY_DEFAULT_LIMIT,
) -> StudyHistoryResponse:
    """Todos los estudios, del mas reciente al mas antiguo, por paginas.

    El numero de lesiones y el volumen total solo vienen en un estudio completed.
    """
    return history_response(service.list_history(limit=limit, offset=offset, national_id=None))


@router.post(
    "/search",
    response_model=StudyHistoryResponse,
    summary="Buscar los estudios de un paciente por su DNI",
    responses=ERRORS,
)
def search_history(
    request: StudySearchRequest,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> StudyHistoryResponse:
    """Los estudios del paciente con ese DNI, del mas reciente al mas antiguo.

    El DNI llega en el cuerpo y no en la URL: el cuerpo no queda en el registro de acceso
    ni en el historial del navegador (research.md R1). Un DNI sin estudios devuelve una
    pagina vacia, no un error. Esta ruta no registra nada propio.
    """
    return history_response(
        service.list_history(
            limit=request.limit, offset=request.offset, national_id=request.national_id
        )
    )
