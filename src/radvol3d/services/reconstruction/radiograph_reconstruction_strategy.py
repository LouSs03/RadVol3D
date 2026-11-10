"""Interfaz del patron Strategy para reconstruir desde UNA radiografia real.

Es distinta de ReconstructionStrategy porque la entrada es distinta: un DICOM tal como
sale del equipo, no cuatro proyecciones sinteticas en el convenio de TA-2. La salida si
es la misma: (128, 128, 128) float32 en [0, 1] con la ventana config.HU_WINDOW y los
ejes del sistema (R, A, S). Asi la segmentacion, las mallas y el visor no cambian.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from radvol3d.domain.enums import RemoteJobState

# Avisa en que paso va el trabajo ("en cola", "reconstruyendo"). Solo para la interfaz.
StateReporter = Callable[[RemoteJobState], None]


class RadiographReconstructionStrategy(ABC):
    """Reconstruye un volumen 3D a partir de una radiografia de torax frontal (DICOM)."""

    @abstractmethod
    def reconstruct(self, radiograph: bytes, report: StateReporter | None = None) -> Any:
        """Recibe los bytes del DICOM y devuelve (128, 128, 128) float32 en [0, 1]."""

    @abstractmethod
    def is_available(self) -> bool:
        """True si la estrategia puede atender un trabajo ahora. Debe responder rapido."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nombre con el que se registra en la tabla model."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Version del modelo."""
