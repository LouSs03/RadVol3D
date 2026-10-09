"""Segmentacion del tumor y entrega de la malla al visor."""

from fastapi import APIRouter, Depends

from radvol3d.api.dependencies import get_processing_pipeline
from radvol3d.api.schemas.segmentation_schema import SegmentationResponse
from radvol3d.services.processing_pipeline import ProcessingPipeline

router = APIRouter(prefix="/studies", tags=["segmentacion"])


@router.get(
    "/{study_code}/segmentation",
    response_model=SegmentationResponse,
    summary="Resultado de la segmentacion",
)
def read_segmentation(
    study_code: str,
    pipeline: ProcessingPipeline = Depends(get_processing_pipeline),
) -> SegmentationResponse:
    """Devuelve las lesiones detectadas con su confianza."""
    raise NotImplementedError("TODO")
