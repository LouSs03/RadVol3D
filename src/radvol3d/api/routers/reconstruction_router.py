"""Subida de proyecciones y reconstruccion del volumen."""

from fastapi import APIRouter, Depends

from radvol3d.api.dependencies import get_processing_pipeline
from radvol3d.api.schemas.reconstruction_schema import ReconstructionResponse
from radvol3d.services.processing_pipeline import ProcessingPipeline

router = APIRouter(prefix="/studies", tags=["reconstruccion"])


@router.post(
    "/{study_code}/reconstruct",
    response_model=ReconstructionResponse,
    summary="Reconstruir el volumen desde cuatro proyecciones",
)
def reconstruct_study(
    study_code: str,
    pipeline: ProcessingPipeline = Depends(get_processing_pipeline),
) -> ReconstructionResponse:
    """La capa 1 pide el resultado; no sabe como se calcula."""
    raise NotImplementedError("TODO")
