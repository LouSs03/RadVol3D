"""Inyeccion de dependencias.

Es la pieza que sostiene el limite entre capas. El endpoint no construye el
servicio de la capa 2: lo recibe con Depends(). Asi no tiene forma de saltarse
la capa, y en las pruebas se sustituye con app.dependency_overrides.

El servicio lo arma service_container una sola vez, en el lifespan de main.py, y
queda en app.state.services. Aqui solo se lee: api/ nunca ve la persistencia.
"""

from fastapi import Request

from radvol3d.services.study_service import StudyService


def get_study_service(request: Request) -> StudyService:
    """Devuelve el servicio de estudios armado al arrancar."""
    return request.app.state.services.study_service
