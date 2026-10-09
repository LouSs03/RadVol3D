"""Subida de las cuatro proyecciones de un estudio (research.md R7).

Llegan en un formulario multipart con un campo de archivo por angulo: angle_000,
angle_045, angle_090 y angle_135. El angulo sale del nombre del campo, nunca del
nombre del archivo. Cada archivo se lee hasta un byte mas que el limite: si lo pasa,
se rechaza con 413 sin leer el resto.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from radvol3d import config
from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.error_schema import ErrorResponse
from radvol3d.api.schemas.projection_schema import ProjectionsUploaded
from radvol3d.services.pipeline.projection_loader import ProjectionFile
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["proyecciones"])

ERRORS = {
    404: {"model": ErrorResponse, "description": "El estudio no existe"},
    409: {"model": ErrorResponse, "description": "El estudio ya tiene sus proyecciones"},
    413: {"model": ErrorResponse, "description": "Un archivo supera el tamano maximo"},
    422: {"model": ErrorResponse, "description": "Una proyeccion no es valida"},
}


def _limit_text() -> str:
    """El limite en MiB, como lo lee una persona."""
    mebibytes = config.MAX_PROJECTION_BYTES / (1024 * 1024)
    return f"{mebibytes:g} MiB"


async def read_limited(upload: UploadFile, angle: int) -> bytes:
    """Lee el archivo hasta el limite. Si lo supera, lanza 413 sin leer el resto."""
    content = await upload.read(config.MAX_PROJECTION_BYTES + 1)
    if len(content) > config.MAX_PROJECTION_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"La proyeccion de {angle} grados supera el tamano maximo "
                f"de {_limit_text()} por archivo."
            ),
        )
    return content


@router.post(
    "/{study_code}/projections",
    response_model=ProjectionsUploaded,
    status_code=status.HTTP_201_CREATED,
    summary="Subir las cuatro proyecciones",
    responses=ERRORS,
)
async def upload_projections(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
    angle_000: Annotated[UploadFile, File(description="Proyeccion a 0 grados (.npy)")],
    angle_045: Annotated[UploadFile, File(description="Proyeccion a 45 grados (.npy)")],
    angle_090: Annotated[UploadFile, File(description="Proyeccion a 90 grados (.npy)")],
    angle_135: Annotated[UploadFile, File(description="Proyeccion a 135 grados (.npy)")],
) -> ProjectionsUploaded:
    """Guarda las cuatro proyecciones. Si una es invalida, no guarda ninguna."""
    uploads = {0: angle_000, 45: angle_045, 90: angle_090, 135: angle_135}
    files = [
        ProjectionFile(angle, await read_limited(upload, angle), upload.filename)
        for angle, upload in uploads.items()
    ]
    # El servicio valida y guarda; es sincrono, asi que corre fuera del bucle de eventos.
    await run_in_threadpool(service.add_projections, study_code, files)
    return ProjectionsUploaded(study_code=study_code, angles=list(uploads))

