"""Doble del ServiceContainer para las pruebas de la aplicacion.

Con el, create_app arranca sin abrir la base ni bajar pesos: el lifespan guarda el
doble en app.state.services como guardaria el contenedor real.
"""

from unittest.mock import create_autospec

from radvol3d.services.study_service import StudyService


class FakeServiceContainer:
    """Tiene la forma de ServiceContainer y anota si se cerro."""

    def __init__(self) -> None:
        self.study_service = create_autospec(StudyService, instance=True)
        self.closed = 0

    def model_status(self) -> dict[str, bool]:
        return {"reconstruction:en1": False, "segmentation:lung": False, "meshing": False}

    def close(self) -> None:
        self.closed += 1
