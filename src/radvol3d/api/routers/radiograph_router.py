"""Modo de una radiografia: subir el DICOM y saber si el modo esta disponible.

El navegador nunca habla con el servicio externo: todo pasa por este backend, asi la
clave no sale del servidor (regla de oro de la guia del modo de una radiografia).

El DICOM llega en un formulario multipart con un solo campo, file. Se lee hasta un
byte mas que el limite: si lo pasa, se rechaza con 413 sin leer el resto.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from radvol3d import config
from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.error_schema import ErrorResponse
from radvol3d.api.schemas.radiograph_result_schema import RadiographResultResponse
from radvol3d.api.schemas.study_schema import RadiographModeStatus, RadiographUploaded
from radvol3d.domain.exceptions import RadiographTooLargeError
from radvol3d.services.pipeline.radiograph_check import limit_text
from radvol3d.services.study_service import StudyService

router = APIRouter(tags=["radiografia"])

ERRORS = {
    404: {"model": ErrorResponse, "description": "El estudio no existe"},
    409: {"model": ErrorResponse, "description": "El estudio no admite una radiografia ahora"},
    413: {"model": ErrorResponse, "description": "El archivo supera el tamano maximo"},
    422: {"model": ErrorResponse, "description": "El archivo no es un DICOM valido"},
}

UNAVAILABLE_TEXT = "El modo de una radiografía no está disponible en este momento."


async def read_radiograph(upload: UploadFile) -> bytes:
    """Lee el archivo hasta el limite. Si lo supera, lanza 413 sin leer el resto."""
    content = await upload.read(config.MAX_RADIOGRAPH_BYTES + 1)
    if len(content) > config.MAX_RADIOGRAPH_BYTES:
        raise RadiographTooLargeError(f"La radiografía supera el tamaño máximo de {limit_text()}.")
    return content


@router.post(
    "/studies/{study_code}/radiograph",
    response_model=RadiographUploaded,
    status_code=status.HTTP_201_CREATED,
    summary="Subir la radiografia (DICOM) de un estudio de una radiografia",
    responses=ERRORS,
)
async def upload_radiograph(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
    file: Annotated[UploadFile, File(description="Radiografia de torax frontal (DICOM)")],
) -> RadiographUploaded:
    """Valida el DICOM (tamano y marca DICM) y lo guarda. Si no es valido, no guarda nada."""
    content = await read_radiograph(file)
    # El servicio valida y sube al bucket; es sincrono, asi que corre fuera del bucle.
    await run_in_threadpool(service.add_radiograph, study_code, content, file.filename)
    return RadiographUploaded(study_code=study_code, size_bytes=len(content))


RESULT_ERRORS = {
    404: {"model": ErrorResponse, "description": "El estudio no existe"},
    409: {"model": ErrorResponse, "description": "No termino o no es de una radiografia"},
}

# Archivos de X2CT-GAN que se pueden descargar, con su tipo.
OUTPUT_MEDIA_TYPES = {
    "volumen.nii.gz": "application/gzip",
    "entrada_modelo_128.png": "image/png",
    "metadatos.json": "application/json",
}
OutputFile = Literal["volumen.nii.gz", "entrada_modelo_128.png", "metadatos.json"]


def output_url(study_code: str, file_name: str) -> str:
    """Ruta de descarga de un archivo de X2CT-GAN."""
    return f"/studies/{study_code}/radiograph-result/{file_name}"


@router.get(
    "/studies/{study_code}/radiograph-result",
    response_model=RadiographResultResponse,
    summary="Resultado de un estudio de una radiografia (visor de ese modo)",
    responses=RESULT_ERRORS,
)
def read_radiograph_result(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> RadiographResultResponse:
    """Voxel con que se muestra el volumen, avisos y direcciones de sus archivos."""
    view = service.radiograph_view(study_code)
    has_files = view.get("has_reconstruction_files", True)
    input_size = view.get("input_size_px")
    return RadiographResultResponse(
        study_code=study_code,
        model_name=view.get("model_name"),
        voxel_mm=[float(value) for value in view["voxel_mm"]],
        relative_measurements=bool(view.get("relative_measurements", False)),
        warnings=[str(text) for text in view.get("warnings", [])],
        input_size_px=[int(value) for value in input_size] if input_size else None,
        timings_s={str(k): float(v) for k, v in (view.get("timings_s") or {}).items()},
        volume_url=f"/studies/{study_code}/result/volume.npy",
        surface_url=f"/studies/{study_code}/result/organ.glb",
        input_image_url=output_url(study_code, "entrada_modelo_128.png") if has_files else None,
        metadata_url=output_url(study_code, "metadatos.json") if has_files else None,
        nifti_url=output_url(study_code, "volumen.nii.gz") if has_files else None,
    )


@router.get(
    "/studies/{study_code}/radiograph-result/{file_name}",
    response_class=Response,
    summary="Archivo de X2CT-GAN: volumen en HU, placa del modelo o metadatos",
    responses=RESULT_ERRORS,
)
def read_radiograph_output(
    study_code: str,
    file_name: OutputFile,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    content = service.read_radiograph_output(study_code, file_name)
    headers = {}
    if file_name != "entrada_modelo_128.png":
        headers["Content-Disposition"] = f'attachment; filename="{study_code}_{file_name}"'
    return Response(content, media_type=OUTPUT_MEDIA_TYPES[file_name], headers=headers)


@router.get(
    "/radiograph-mode",
    response_model=RadiographModeStatus,
    summary="Saber si el modo de una radiografia esta disponible",
)
def radiograph_mode(
    service: Annotated[StudyService, Depends(get_study_service)],
) -> RadiographModeStatus:
    """Consulta /health del servicio externo con un tiempo de espera corto (5 s).

    Es una funcion sincrona a proposito: FastAPI la corre en su grupo de hilos, asi la
    espera no bloquea las demas peticiones.
    """
    available = service.radiograph_mode_available()
    return RadiographModeStatus(
        available=available,
        message=None if available else UNAVAILABLE_TEXT,
        max_bytes=config.MAX_RADIOGRAPH_BYTES,
    )
