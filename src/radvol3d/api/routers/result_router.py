"""Resultado de un estudio y descarga de sus archivos (research.md R6).

Las descargas pasan por el propio servicio: el navegador nunca recibe la direccion
del bucket ni una credencial, y ninguna direccion vence mientras el visor carga.
Todas estas rutas exigen el estudio en completed (si no, 409 con el estado).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from radvol3d.api.content_types import GLB_CONTENT_TYPE, NPY_CONTENT_TYPE
from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.error_schema import ErrorResponse
from radvol3d.api.schemas.result_schema import LesionResponse, ResultResponse
from radvol3d.domain.enums import ResultFile
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["resultados"])

ERRORS = {
    400: {"model": ErrorResponse, "description": "Codigo de estudio invalido"},
    404: {"model": ErrorResponse, "description": "El estudio o el archivo no existen"},
    409: {"model": ErrorResponse, "description": "El estudio todavia no termino"},
}


def result_url(study_code: str, file_name: str) -> str:
    """Ruta del servicio para descargar un archivo del resultado."""
    return f"/studies/{study_code}/result/{file_name}"


@router.get(
    "/{study_code}/result",
    response_model=ResultResponse,
    summary="Resultado de un estudio",
    responses=ERRORS,
)
def read_result(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> ResultResponse:
    """Direcciones de las mallas y del volumen, y la lista de lesiones."""
    result = service.get_completed_result(study_code)
    return ResultResponse(
        study_code=study_code,
        organ_mesh_url=result_url(study_code, "organ.glb"),
        tumor_mesh_url=result_url(study_code, "tumor.glb"),
        volume_url=result_url(study_code, "volume.npy"),
        lesions=[
            LesionResponse(
                lesion_number=number,
                organ=lesion.organ,
                location=lesion.location,
                volume_mm3=lesion.volume_mm3,
                max_diameter_mm=lesion.max_diameter_mm,
                confidence=lesion.confidence,
                mesh_url=result_url(study_code, f"lesions/{number}.glb"),
            )
            for number, lesion in enumerate(result.lesions, 1)
        ],
    )


@router.get(
    "/{study_code}/result/organ.glb",
    response_class=Response,
    summary="Malla del organo",
    responses=ERRORS,
)
def read_organ_mesh(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    return Response(
        service.read_result_file(study_code, ResultFile.ORGAN_MESH),
        media_type=GLB_CONTENT_TYPE,
    )


@router.get(
    "/{study_code}/result/tumor.glb",
    response_class=Response,
    summary="Malla del tumor, con todas las lesiones juntas",
    responses=ERRORS,
)
def read_tumor_mesh(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    return Response(
        service.read_result_file(study_code, ResultFile.TUMOR_MESH),
        media_type=GLB_CONTENT_TYPE,
    )


@router.get(
    "/{study_code}/result/volume.npy",
    response_class=Response,
    summary="Volumen reconstruido",
    responses=ERRORS,
)
def read_volume(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    return Response(
        service.read_result_file(study_code, ResultFile.VOLUME),
        media_type=NPY_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{study_code}_volume.npy"'},
    )


@router.get(
    "/{study_code}/result/lesions/{lesion_number}.glb",
    response_class=Response,
    summary="Malla de una lesion",
    responses=ERRORS,
)
def read_lesion_mesh(
    study_code: str,
    lesion_number: Annotated[int, Path(ge=1, description="Posicion en la lista, desde 1")],
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    return Response(
        service.read_lesion_mesh(study_code, lesion_number),
        media_type=GLB_CONTENT_TYPE,
    )
