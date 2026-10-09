"""Punto de entrada. Arma la aplicacion y monta los routers de la capa 1.

main.py no es una capa: es el unico lugar que une la presentacion con los servicios
ya armados. Por eso puede llamar a service_container, que a su vez usa la
persistencia, sin que api/ la importe nunca.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from radvol3d import __version__
from radvol3d.api.error_handlers import register_error_handlers
from radvol3d.api.routers import (
    health_router,
    reconstruction_router,
    segmentation_router,
    study_router,
)
from radvol3d.persistence.settings import get_model_settings, get_settings
from radvol3d.services.service_container import build_service_container

WEB_DIRECTORY = Path(__file__).parent / "web"

logger = logging.getLogger(__name__)


def build_default_container() -> Any:
    """Arma los servicios reales con la configuracion de .env."""
    return build_service_container(get_settings(), get_model_settings())


def make_lifespan(container_builder: Callable[[], Any]) -> Callable[..., Any]:
    """Devuelve el lifespan que arma los servicios con el constructor recibido."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Abre los recursos caros al arrancar y los cierra al terminar.

        La base y los modelos se preparan una sola vez. Cargar un modelo en cada
        peticion dejaria el servicio inutilizable.
        """
        container = container_builder()
        app.state.services = container
        logger.info("Modelos disponibles: %s", container.model_status())
        try:
            yield
        finally:
            container.close()

    return lifespan


def create_app(container_builder: Callable[[], Any] | None = None) -> FastAPI:
    """Construye la aplicacion. Separarlo de la instancia permite probarla.

    container_builder arma los servicios al arrancar; las pruebas pasan uno falso
    que no abre la base. Nada se construye hasta que la aplicacion arranca.
    """
    app = FastAPI(
        title="RadVol3D",
        description=(
            "Reconstruccion tridimensional de organos a partir de cuatro "
            "proyecciones radiograficas, con deteccion automatica de tumores."
        ),
        version=__version__,
        lifespan=make_lifespan(container_builder or build_default_container),
    )

    register_error_handlers(app)

    app.include_router(health_router.router)
    app.include_router(study_router.router)
    app.include_router(reconstruction_router.router)
    app.include_router(segmentation_router.router)

    if WEB_DIRECTORY.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIRECTORY, html=True), name="web")

    return app


app = create_app()
