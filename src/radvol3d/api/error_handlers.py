"""Traduce los errores del dominio a codigos HTTP.

Esta es la unica parte del sistema que conoce HTTP y el dominio a la vez. Gracias
a eso, ninguna capa inferior necesita importar fastapi.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from radvol3d.domain.exceptions import (
    DatabaseUnavailableError,
    InvalidProjectionError,
    InvalidStudyIdError,
    ModelNotAvailableError,
    StorageError,
    StudyNotFoundError,
)

STATUS_BY_ERROR: dict[type[Exception], int] = {
    StudyNotFoundError: 404,
    InvalidStudyIdError: 400,
    InvalidProjectionError: 422,
    ModelNotAvailableError: 503,
    DatabaseUnavailableError: 503,
    StorageError: 500,
}


def register_error_handlers(app: FastAPI) -> None:
    """Registra un manejador por cada error del dominio."""

    for error_type, status_code in STATUS_BY_ERROR.items():

        async def handler(
            request: Request,
            exc: Exception,
            code: int = status_code,
        ) -> JSONResponse:
            # El mensaje al usuario va en espanol; el nombre del error, en ingles.
            return JSONResponse(status_code=code, content={"detalle": str(exc)})

        app.add_exception_handler(error_type, handler)
