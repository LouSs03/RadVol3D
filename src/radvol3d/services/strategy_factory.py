"""Factory Method: un solo lugar sabe que estrategia corresponde a cada organo.

Sin esto, la decision se repartiria en if dispersos por la tuberia, el servicio y
la generacion de mallas, y cada organo nuevo obligaria a tocar los tres.

La fabrica recibe constructores sin argumentos, no estrategias ya hechas. Los llama
una sola vez, en preload(), que corre al arrancar: asi cada modelo se carga una vez
y todos los estudios comparten la misma instancia (research.md R12). Las pruebas la
arman con constructores que devuelven los dobles.

Si un constructor falla (falta PyTorch, faltan los pesos, el archivo esta corrupto),
preload() no lanza: el modelo queda no disponible y la aplicacion arranca igual
(FR-019). Pedirlo despues lanza ModelNotAvailableError.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy

logger = logging.getLogger(__name__)

# Nombre de cada organo en los mensajes al usuario.
_ORGAN_LABELS: dict[OrganName, str] = {
    OrganName.LUNG: "pulmón",
    OrganName.LIVER: "hígado",
}


@dataclass(frozen=True)
class StrategySet:
    """Las tres estrategias con que se procesa un estudio."""

    reconstruction: ReconstructionStrategy
    segmentation: SegmentationStrategy
    meshing: MeshingStrategy


class StrategyFactory:
    """Construye cada estrategia una vez y entrega las que corresponden a cada organo."""

    def __init__(
        self,
        reconstruction_builders: Mapping[str, Callable[[], ReconstructionStrategy]],
        segmentation_builders: Mapping[OrganName, Callable[[], SegmentationStrategy]],
        meshing_builder: Callable[[], MeshingStrategy],
        reconstruction_key: str,
    ) -> None:
        self._reconstruction_builders = dict(reconstruction_builders)
        self._segmentation_builders = {
            OrganName(organ): builder for organ, builder in segmentation_builders.items()
        }
        self._meshing_builder = meshing_builder
        self._reconstruction_key = reconstruction_key
        self._reconstruction: dict[str, ReconstructionStrategy] = {}
        self._segmentation: dict[OrganName, SegmentationStrategy] = {}
        self._meshing: MeshingStrategy | None = None

    def preload(self) -> None:
        """Construye cada estrategia registrada, una sola vez. Nunca lanza."""
        for key, builder in self._reconstruction_builders.items():
            self._reconstruction[key] = self._build(f"reconstruction:{key}", builder)
        for organ, builder in self._segmentation_builders.items():
            self._segmentation[organ] = self._build(f"segmentation:{organ.value}", builder)
        self._meshing = self._build("meshing", self._meshing_builder)

    def strategies_for(self, organ: OrganName | str) -> StrategySet:
        """Devuelve las estrategias ya construidas para el organo pedido."""
        organ_name = OrganName(organ)
        if organ_name not in self._segmentation_builders:
            raise ModelNotAvailableError(
                f"No hay modelo de segmentación de {_ORGAN_LABELS[organ_name]} todavía."
            )
        if self._reconstruction_key not in self._reconstruction_builders:
            raise ModelNotAvailableError(
                f"No hay estrategia de reconstrucción '{self._reconstruction_key}'."
            )
        reconstruction = self._loaded(
            f"reconstruction:{self._reconstruction_key}",
            self._reconstruction.get(self._reconstruction_key),
        )
        segmentation = self._loaded(
            f"segmentation:{organ_name.value}", self._segmentation.get(organ_name)
        )
        meshing = self._loaded("meshing", self._meshing)
        return StrategySet(reconstruction, segmentation, meshing)

    def availability(self) -> dict[str, bool]:
        """Que estrategias quedaron cargadas, para informarlo al arrancar."""
        status = {
            f"reconstruction:{key}": self._reconstruction.get(key) is not None
            for key in self._reconstruction_builders
        }
        status.update(
            {
                f"segmentation:{organ.value}": self._segmentation.get(organ) is not None
                for organ in self._segmentation_builders
            }
        )
        status["meshing"] = self._meshing is not None
        return status

    def model_strategies(self) -> list[ReconstructionStrategy | SegmentationStrategy]:
        """Las estrategias cargadas que tienen un modelo para registrar en la tabla model.

        Las mallas no cuentan: la etapa 4 no tiene modelo.
        """
        loaded = [*self._reconstruction.values(), *self._segmentation.values()]
        return [strategy for strategy in loaded if strategy is not None]

    @staticmethod
    def _build(label: str, builder: Callable[[], object]) -> object | None:
        """Llama al constructor. Si falla, registra solo el tipo del error y devuelve None.

        El texto del error no se registra: puede traer rutas firmadas del bucket.
        """
        try:
            return builder()
        except Exception as error:  # noqa: BLE001 - ningun modelo detiene el arranque
            logger.warning(
                "El modelo %s no esta disponible (%s)", label, type(error).__name__
            )
            return None

    @staticmethod
    def _loaded(label: str, strategy: object | None) -> object:
        if strategy is None:
            raise ModelNotAvailableError(
                f"El modelo {label} no está disponible en este servidor."
            )
        return strategy
