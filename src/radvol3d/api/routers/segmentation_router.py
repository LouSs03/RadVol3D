"""Segmentacion del tumor y entrega de la malla al visor."""

from typing import Annotated

from fastapi import APIRouter, Depends

from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.segmentation_schema import SegmentationResponse
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["segmentacion"])


@router.get(
    "/{study_code}/segmentation",
    response_model=SegmentationResponse,
    summary="Resultado de la segmentacion",
)
def read_segmentation(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> SegmentationResponse:
    """Devuelve las lesiones detectadas con su confianza."""
    raise NotImplementedError("TODO")
