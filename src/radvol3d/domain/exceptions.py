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


class ConfigurationError(RadVol3DError):
    """Falta una variable de configuracion o esta vacia."""


class DuplicateStudyError(RadVol3DError):
    """Ya existe un estudio con ese codigo."""


class InvalidPatientDataError(RadVol3DError):
    """Los datos del paciente no cumplen el formato permitido."""


class PatientCodeExhaustedError(RadVol3DError):
    """Ya no quedan codigos de paciente disponibles en el formato permitido."""


class UnknownOrganError(RadVol3DError):
    """El organo pedido esta fuera del alcance del sistema."""


class InvalidLesionError(RadVol3DError):
    """Una lesion o una region del resumen no cumple las reglas de los datos."""


class PersistenceError(RadVol3DError):
    """La base de datos rechazo la operacion por una regla de integridad."""


class StorageObjectNotFoundError(StorageError):
    """El archivo pedido no existe en el almacenamiento de objetos."""
