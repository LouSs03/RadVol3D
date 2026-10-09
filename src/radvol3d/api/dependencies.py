"""Inyeccion de dependencias.

Es la pieza que sostiene el limite entre capas. El endpoint no construye el
servicio de la capa 2: lo recibe con Depends(). Asi no tiene forma de saltarse
la capa, y en las pruebas se sustituye con app.dependency_overrides.
"""

from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.study_service import StudyService


def get_processing_pipeline() -> ProcessingPipeline:
    """Arma la tuberia con sus estrategias. La capa 1 solo la consume."""
    raise NotImplementedError("TODO: construir la tuberia con sus estrategias")


def get_study_service() -> StudyService:
    """Devuelve el servicio de estudios."""
    raise NotImplementedError("TODO: construir el servicio de estudios")
