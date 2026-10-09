"""Subida de proyecciones y reconstruccion del volumen."""

from typing import Annotated

from fastapi import APIRouter, Depends

from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.reconstruction_schema import ReconstructionResponse
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["reconstruccion"])


@router.post(
    "/{study_code}/reconstruct",
    response_model=ReconstructionResponse,
    summary="Reconstruir el volumen desde cuatro proyecciones",
)
def reconstruct_study(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> ReconstructionResponse:
    """La capa 1 pide el resultado; no sabe como se calcula."""
    raise NotImplementedError("TODO")
