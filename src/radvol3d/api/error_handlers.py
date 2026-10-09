"""Traduce los errores a codigos HTTP, en un solo lugar (research.md R8).

Esta es la unica parte del sistema que conoce HTTP y el dominio a la vez. Gracias
a eso, ninguna capa inferior necesita importar fastapi.

Tres reglas, todas para que ningun dato del paciente salga del servidor (FR-029):

- Cada error del dominio responde {"detail": <su mensaje>}. Los mensajes del dominio
  ya se escriben sin datos personales.
- La validacion de la peticion (422) responde loc, msg y type de cada campo, sin el
  campo input con que FastAPI devuelve el valor recibido: con un DNI mal escrito, ese
  valor seria un dato del paciente.
- Un error inesperado responde 500 con un mensaje generico y solo deja en el registro
  su tipo. Se atrapa en un middleware, y no con un manejador de Exception, porque
  Starlette vuelve a lanzar la excepcion despues de ese manejador y el servidor
  registraria la traza completa, con el texto del error.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radvol3d.domain.exceptions import (
    DatabaseUnavailableError,
    DuplicateStudyError,
    InvalidLesionError,
    InvalidPatientDataError,
    InvalidProjectionError,
    InvalidStudyIdError,
    InvalidStudyStateError,
    ModelNotAvailableError,
    PatientCodeExhaustedError,
    PersistenceError,
    StageFailedError,
    StorageError,
    StorageObjectNotFoundError,
    StudyInProgressError,
    StudyNotFoundError,
    UnknownOrganError,
)

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Error interno del servidor."

STATUS_BY_ERROR: dict[type[Exception], int] = {
    StudyNotFoundError: 404,
    StorageObjectNotFoundError: 404,
    InvalidStudyIdError: 400,
    InvalidProjectionError: 422,
    InvalidPatientDataError: 422,
    UnknownOrganError: 422,
    DuplicateStudyError: 409,
    StudyInProgressError: 409,
    InvalidStudyStateError: 409,
    ModelNotAvailableError: 503,
    DatabaseUnavailableError: 503,
    StorageError: 500,
    StageFailedError: 500,
    PersistenceError: 500,
    InvalidLesionError: 500,
    PatientCodeExhaustedError: 500,
}


class InternalErrorMiddleware:
    """Convierte un error inesperado en un 500 generico y no lo vuelve a lanzar."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, tracking_send)
        except Exception as error:  # noqa: BLE001 - es la ultima defensa
            logger.error(
                "Error inesperado en %s %s (%s)",
                scope.get("method", ""),
                scope.get("path", ""),
                type(error).__name__,
            )
            if not response_started:
                response = JSONResponse(
                    status_code=500, content={"detail": INTERNAL_ERROR_MESSAGE}
                )
                await response(scope, receive, send)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 con loc, msg y type de cada campo; sin input ni ctx."""
    detail = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def register_error_handlers(app: FastAPI) -> None:
    """Registra un manejador por cada error del dominio, el de validacion y el de 500."""

    for error_type, status_code in STATUS_BY_ERROR.items():

        async def handler(
            request: Request,
            exc: Exception,
            code: int = status_code,
        ) -> JSONResponse:
            # El mensaje al usuario va en espanol; el nombre del error, en ingles.
            return JSONResponse(status_code=code, content={"detail": str(exc)})

        app.add_exception_handler(error_type, handler)

    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(InternalErrorMiddleware)
