"""Forma de los cuerpos de error de la API.

Sirven para documentar las respuestas en /docs. El cuerpo de validacion no tiene el
campo input a proposito: FastAPI lo usa para devolver el valor recibido, y con un DNI
mal escrito ese valor seria un dato del paciente (research.md R8).
"""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Error del dominio o del servidor."""

    detail: str = Field(description="Mensaje en espanol, sin datos del paciente")


class ValidationErrorItem(BaseModel):
    """Un campo de la peticion que no paso la validacion."""

    loc: list[str | int] = Field(description="Donde esta el campo invalido")
    msg: str = Field(description="Que regla no cumple")
    type: str = Field(description="Codigo del tipo de error")


class ValidationErrorResponse(BaseModel):
    """La peticion no cumple su esquema."""

    detail: list[ValidationErrorItem]
