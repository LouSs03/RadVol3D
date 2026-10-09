"""Estado del servicio. Es el endpoint que confirma que todo arranco bien."""

from fastapi import APIRouter

from radvol3d import __version__, config
from radvol3d.api.schemas.health_schema import HealthResponse

router = APIRouter(tags=["estado"])


@router.get("/health", response_model=HealthResponse, summary="Estado del servicio")
def read_health() -> HealthResponse:
    """Devuelve la version y los parametros con los que trabaja el sistema."""
    return HealthResponse(
        status="ok",
        version=__version__,
        grid_size=config.GRID_SIZE,
        mm_per_voxel=config.MM_PER_VOXEL,
        projection_angles=list(config.PROJECTION_ANGLES),
    )
