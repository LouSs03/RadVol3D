"""Pagina del visor 3D de un estudio (research.md R13).

La pagina es estatica: lee el codigo del estudio de su propia URL y pide el estado y
el resultado a la API. Aqui solo se comprueba que el estudio exista, para responder
404 (con la misma pagina, que muestra "no existe") cuando no existe.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from radvol3d.api.dependencies import get_study_service
from radvol3d.domain.exceptions import StudyNotFoundError
from radvol3d.services.study_service import StudyService

VIEWER_PAGE = Path(__file__).resolve().parents[2] / "web" / "viewer.html"

router = APIRouter(tags=["visor"])


@router.get(
    "/viewer/{study_code}",
    response_class=FileResponse,
    summary="Visor 3D de un estudio",
)
def read_viewer(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> FileResponse:
    """Devuelve la pagina del visor; 404 con la misma pagina si el estudio no existe."""
    try:
        service.get_study(study_code)
    except StudyNotFoundError:
        return FileResponse(VIEWER_PAGE, status_code=404, media_type="text/html")
    return FileResponse(VIEWER_PAGE, media_type="text/html")
