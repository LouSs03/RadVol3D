"""Punto de entrada. Arma la aplicacion y monta los routers de la capa 1."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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

WEB_DIRECTORY = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre los recursos caros al arrancar y los cierra al terminar.

    Los modelos y la conexion a la base de datos se preparan una sola vez.
    Cargar un modelo en cada peticion dejaria el servicio inutilizable.
    """
    # TODO: cargar modelos y abrir el grupo de conexiones
    yield
    # TODO: cerrar el grupo de conexiones


def create_app() -> FastAPI:
    """Construye la aplicacion. Separarlo de la instancia permite probarla."""
    app = FastAPI(
        title="RadVol3D",
        description=(
            "Reconstruccion tridimensional de organos a partir de cuatro "
            "proyecciones radiograficas, con deteccion automatica de tumores."
        ),
        version=__version__,
        lifespan=lifespan,
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
