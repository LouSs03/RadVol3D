"""Factory Method: un solo lugar sabe que estrategia corresponde a cada organo.

Sin esto, la decision se repartiria en if dispersos por la tuberia, el servicio y
la generacion de mallas, y cada organo nuevo obligaria a tocar los tres.

Las mallas tienen un constructor comun y, opcionalmente, uno por organo
(organ_meshing_builders): el pulmon necesita su propia region del organo
(services/meshing/lung_air_region.py). Un organo sin constructor propio usa el comun.

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
from radvol3d.services.reconstruction.radiograph_reconstruction_strategy import (
    RadiographReconstructionStrategy,
)
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


@dataclass(frozen=True)
class RadiographStrategySet:
    """Las tres estrategias con que se procesa un estudio de una radiografia."""

    reconstruction: RadiographReconstructionStrategy
    segmentation: SegmentationStrategy
    meshing: MeshingStrategy


RADIOGRAPH_UNAVAILABLE = "El modo de una radiografía no está disponible en este momento."


class StrategyFactory:
    """Construye cada estrategia una vez y entrega las que corresponden a cada organo."""

    def __init__(
        self,
        reconstruction_builders: Mapping[str, Callable[[], ReconstructionStrategy]],
        segmentation_builders: Mapping[OrganName, Callable[[], SegmentationStrategy]],
        meshing_builder: Callable[[], MeshingStrategy],
        reconstruction_key: str,
        organ_meshing_builders: Mapping[OrganName, Callable[[], MeshingStrategy]] | None = None,
        radiograph_reconstruction_builder: Callable[[], RadiographReconstructionStrategy]
        | None = None,
        radiograph_segmentation_builders: Mapping[OrganName, Callable[[], SegmentationStrategy]]
        | None = None,
    ) -> None:
        self._reconstruction_builders = dict(reconstruction_builders)
        self._segmentation_builders = {
            OrganName(organ): builder for organ, builder in segmentation_builders.items()
        }
        self._meshing_builder = meshing_builder
        self._organ_meshing_builders = {
            OrganName(organ): builder for organ, builder in (organ_meshing_builders or {}).items()
        }
        self._reconstruction_key = reconstruction_key
        self._radiograph_reconstruction_builder = radiograph_reconstruction_builder
        self._radiograph_segmentation_builders = {
            OrganName(organ): builder
            for organ, builder in (radiograph_segmentation_builders or {}).items()
        }
        self._radiograph_reconstruction: RadiographReconstructionStrategy | None = None
        self._radiograph_segmentation: dict[OrganName, SegmentationStrategy] = {}
        self._reconstruction: dict[str, ReconstructionStrategy] = {}
        self._segmentation: dict[OrganName, SegmentationStrategy] = {}
        self._meshing: MeshingStrategy | None = None
        self._organ_meshing: dict[OrganName, MeshingStrategy] = {}

    def preload(self) -> None:
        """Construye cada estrategia registrada, una sola vez. Nunca lanza."""
        for key, builder in self._reconstruction_builders.items():
            self._reconstruction[key] = self._build(f"reconstruction:{key}", builder)
        for organ, builder in self._segmentation_builders.items():
            self._segmentation[organ] = self._build(f"segmentation:{organ.value}", builder)
        self._meshing = self._build("meshing", self._meshing_builder)
        for organ, builder in self._organ_meshing_builders.items():
            self._organ_meshing[organ] = self._build(f"meshing:{organ.value}", builder)
        if self._radiograph_reconstruction_builder is not None:
            self._radiograph_reconstruction = self._build(
                "radiograph:reconstruction", self._radiograph_reconstruction_builder
            )
        for organ, builder in self._radiograph_segmentation_builders.items():
            self._radiograph_segmentation[organ] = self._build(
                f"radiograph:segmentation:{organ.value}", builder
            )

    def strategies_for(
        self, organ: OrganName | str, reconstruction_key: str | None = None
    ) -> StrategySet:
        """Choose a loaded reconstruction for this study without changing the default."""
        organ_name = OrganName(organ)
        key = self._reconstruction_key if reconstruction_key is None else reconstruction_key
        if organ_name not in self._segmentation_builders:
            raise ModelNotAvailableError(
                f"No hay modelo de segmentación de {_ORGAN_LABELS[organ_name]} todavía."
            )
        if key not in self._reconstruction_builders:
            raise ModelNotAvailableError(
                f"No hay estrategia de reconstrucción '{key}'."
            )
        if key == "en1_luna16" and organ_name is not OrganName.LUNG:
            raise ModelNotAvailableError("La reconstrucción LUNA16 solo admite pulmón.")
        reconstruction = self._loaded(
            f"reconstruction:{key}",
            self._reconstruction.get(key),
        )
        segmentation = self._loaded(
            f"segmentation:{organ_name.value}", self._segmentation.get(organ_name)
        )
        return StrategySet(reconstruction, segmentation, self.meshing_for(organ_name))

    def radiograph_strategies_for(self, organ: OrganName | str) -> RadiographStrategySet:
        """Las estrategias del modo de una radiografia para el organo pedido.

        Lanza ModelNotAvailableError si el modo no esta configurado (falta AXON_URL o
        AXON_API_KEY) o si no hay segmentacion registrada para ese organo. No comprueba
        que el servicio externo responda: eso lo hace StudyService antes de reclamar.
        """
        organ_name = OrganName(organ)
        if self._radiograph_reconstruction is None:
            raise ModelNotAvailableError(RADIOGRAPH_UNAVAILABLE)
        segmentation = self._radiograph_segmentation.get(organ_name)
        if segmentation is None:
            raise ModelNotAvailableError(
                f"El modo de una radiografía no admite {_ORGAN_LABELS[organ_name]}."
            )
        return RadiographStrategySet(
            self._radiograph_reconstruction, segmentation, self.meshing_for(organ_name)
        )

    def radiograph_mode_configured(self) -> bool:
        """Si el modo de una radiografia quedo armado al arrancar (no si responde)."""
        return self._radiograph_reconstruction is not None

    def meshing_for(self, organ: OrganName | str) -> MeshingStrategy:
        """La estrategia de mallas del organo: la propia si la tiene, si no la comun.

        No necesita los modelos de reconstruccion ni de segmentacion: la regeneracion de
        mallas la usa sin cargar torch.
        """
        organ_name = OrganName(organ)
        if organ_name in self._organ_meshing_builders:
            return self._loaded(f"meshing:{organ_name.value}", self._organ_meshing.get(organ_name))
        return self._loaded("meshing", self._meshing)

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
        if self._radiograph_reconstruction_builder is not None:
            status["radiograph:reconstruction"] = self._radiograph_reconstruction is not None
        status["meshing"] = self._meshing is not None
        status.update(
            {
                f"meshing:{organ.value}": self._organ_meshing.get(organ) is not None
                for organ in self._organ_meshing_builders
            }
        )
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
