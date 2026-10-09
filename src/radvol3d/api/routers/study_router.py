"""Crear un estudio, consultar su estado y mandarlo a procesar (contracts/http_api.md).

La tuberia no corre dentro de la peticion: process reclama el estudio y deja
run_processing como tarea en segundo plano, que Starlette ejecuta en su grupo de
hilos despues de responder (research.md R4). Asi la respuesta llega enseguida y las
consultas de estado siguen respondiendo mientras el estudio se procesa.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from radvol3d.api.dependencies import get_study_service
from radvol3d.api.schemas.error_schema import ErrorResponse
from radvol3d.api.schemas.study_schema import (
    ProcessingAccepted,
    StageStatusResponse,
    StudyCreate,
    StudyResponse,
    StudyStatusResponse,
)
from radvol3d.domain.entities import PatientDetails, Study
from radvol3d.domain.enums import StudyStatus
from radvol3d.services.study_service import StudyService

router = APIRouter(prefix="/studies", tags=["estudios"])

ERRORS = {
    400: {"model": ErrorResponse, "description": "Codigo de estudio invalido"},
    404: {"model": ErrorResponse, "description": "El estudio no existe"},
    409: {"model": ErrorResponse, "description": "El estado del estudio no lo permite"},
    503: {"model": ErrorResponse, "description": "No hay modelo para el organo"},
}


def status_url(study_code: str) -> str:
    """Ruta donde se consulta el avance del estudio."""
    return f"/studies/{study_code}/status"


def run_in_background(service: StudyService, study_code: str) -> None:
    """La tarea en segundo plano. Es una funcion sincrona comun a proposito: Starlette
    la ejecuta en su grupo de hilos, fuera del bucle de eventos. run_processing nunca
    lanza, asi que un fallo no llega aqui: queda en el estado del estudio.
    """
    service.run_processing(study_code)


def study_response(study: Study) -> StudyResponse:
    """El estudio sin datos personales: del paciente solo sale su codigo."""
    return StudyResponse(
        study_code=study.study_code,
        organ=study.organ,
        status=study.status,
        created_at=study.created_at,
        patient_code=study.patient.patient_code if study.patient else None,
    )


def status_response(study: Study) -> StudyStatusResponse:
    """El estudio con sus cuatro etapas en orden."""
    stages = sorted(study.stages, key=lambda stage: stage.stage_number.value)
    return StudyStatusResponse(
        **study_response(study).model_dump(),
        total_time_sec=study.total_time_sec,
        stages=[
            StageStatusResponse(
                stage_number=stage.stage_number.value,
                stage_name=stage.stage_number.name.lower(),
                status=stage.status,
                started_at=stage.started_at,
                finished_at=stage.finished_at,
            )
            for stage in stages
        ],
    )


@router.post(
    "",
    response_model=StudyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un estudio",
    responses=ERRORS,
)
def create_study(
    request: StudyCreate,
    response: Response,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> StudyResponse:
    """Crea el estudio en pending, todavia sin proyecciones."""
    patient = (
        PatientDetails(
            first_name=request.patient.first_name,
            last_name=request.patient.last_name,
            national_id=request.patient.national_id,
        )
        if request.patient is not None
        else None
    )
    study = service.create_study(request.study_code, request.organ, patient)
    response.headers["Location"] = status_url(study.study_code)
    return study_response(study)


@router.get(
    "/{study_code}/status",
    response_model=StudyStatusResponse,
    summary="Consultar el estado de un estudio",
    responses=ERRORS,
)
def read_status(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> StudyStatusResponse:
    """Devuelve el estado del estudio y el de cada una de sus cuatro etapas."""
    return status_response(service.get_study(study_code))


@router.delete(
    "/{study_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Borrar un estudio",
    responses=ERRORS,
)
def delete_study(
    study_code: str,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> Response:
    """Borra el estudio con sus filas y todos sus archivos. El paciente se conserva."""
    service.delete_study(study_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{study_code}/process",
    response_model=ProcessingAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Procesar un estudio en segundo plano",
    responses=ERRORS,
)
def process_study(
    study_code: str,
    background_tasks: BackgroundTasks,
    service: Annotated[StudyService, Depends(get_study_service)],
) -> ProcessingAccepted:
    """Reclama el estudio y lanza la tuberia sin esperarla.

    Un fallo de la tuberia no cambia esta respuesta: se ve despues en el estado.
    """
    service.start_processing(study_code)
    background_tasks.add_task(run_in_background, service, study_code)
    return ProcessingAccepted(
        study_code=study_code,
        status=StudyStatus.PROCESSING,
        status_url=status_url(study_code),
    )
