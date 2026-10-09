"""Errores propios del dominio.

Cada capa lanza estos y la capa 1 los traduce a codigos HTTP en un solo lugar
(api/error_handlers.py). Asi ninguna capa inferior necesita saber que existe HTTP.
"""


class RadVol3DError(Exception):
    """Raiz de todos los errores del sistema."""


class StudyNotFoundError(RadVol3DError):
    """El estudio pedido no existe."""


class InvalidStudyIdError(RadVol3DError):
    """El identificador no cumple el formato permitido."""


class InvalidProjectionError(RadVol3DError):
    """Las proyecciones recibidas no cumplen el contrato de entrada."""


class StorageError(RadVol3DError):
    """Fallo al leer o escribir en el almacenamiento de objetos."""


class DatabaseUnavailableError(RadVol3DError):
    """No se pudo conectar con la base de datos."""


class ModelNotAvailableError(RadVol3DError):
    """El modelo pedido no esta cargado o sus pesos no se encuentran."""
