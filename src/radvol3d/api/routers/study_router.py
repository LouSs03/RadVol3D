"""Crear, consultar y borrar estudios."""

from fastapi import APIRouter, Depends

from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.study_schema import StudyResponse
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["estudios"])


@router.get("/{study_code}", response_model=StudyResponse, summary="Consultar un estudio")
def read_study(
    study_code: str,
    service: StudyService = Depends(get_study_service),
) -> StudyResponse:
    """Devuelve el estado y los resultados de un estudio."""
    raise NotImplementedError("TODO")
