"""Arma los servicios una sola vez, al arrancar la aplicacion (research.md R11).

La presentacion no puede importar la persistencia, asi que alguien tiene que armar
StudyService por ella: es este modulo, y lo llama el lifespan de main.py. Abre la
base, crea los almacenes, baja los pesos, construye cada estrategia una vez y
registra cada modelo cargado en la tabla model.

Un modelo que no carga (falta PyTorch, faltan sus variables o sus pesos) no detiene
el arranque: queda no disponible y los estudios que lo necesiten fallan con
ModelNotAvailableError (FR-019). La base, en cambio, es obligatoria.

El modo de una radiografia sigue la misma regla: sin AXON_URL o AXON_API_KEY queda no
disponible y el modo de cuatro proyecciones funciona igual. Armar su estrategia no toca
la red: si el servicio externo esta apagado se sabe al usarlo, no al arrancar.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.model_weights_store import ModelWeightsStore
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.reconstruction_service_client import ReconstructionServiceClient
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.settings import (
    ModelSettings,
    ReconstructionServiceSettings,
    Settings,
)
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.lung_air_region import LungAirRegion
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard
from radvol3d.services.reconstruction.luna16_strategy import Luna16Strategy
from radvol3d.services.reconstruction.neural_en1_strategy import NeuralEn1Strategy
from radvol3d.services.reconstruction.radiograph_reconstruction_strategy import (
    RadiographReconstructionStrategy,
)
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.reconstruction.remote_axon_strategy import RemoteAxonStrategy
from radvol3d.services.segmentation.lung_unet_strategy import LungUnetStrategy
from radvol3d.services.segmentation.pending_segmentation_strategy import (
    PendingSegmentationStrategy,
)
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyService

logger = logging.getLogger(__name__)

# Descripcion con que se registra cada modelo en la tabla model (data-model.md §5).
MODEL_DESCRIPTIONS: dict[str, str] = {
    "reconstruction_en1": "Retroproyector de TA-2, filtro rampa y U-Net 3D residual EN-1",
    "reconstruction_en1_luna16": "Experimental LUNA16 reconstruction, training run v3",
    "segmentation_lung": "U-Net 3D residual con supervision profunda EN-2",
    "reconstruction_axon_coarsediff": (
        "AXON CoarseDiff: volumen desde una radiografia real, servicio externo con GPU"
    ),
}


@dataclass(frozen=True)
class StrategyBuilders:
    """Los constructores de estrategias que recibe la fabrica."""

    reconstruction: Mapping[str, Callable[[], ReconstructionStrategy]]
    segmentation: Mapping[OrganName, Callable[[], SegmentationStrategy]]
    meshing: Callable[[], MeshingStrategy]
    # Mallas propias de un organo; el resto usa meshing.
    organ_meshing: Mapping[OrganName, Callable[[], MeshingStrategy]] = field(
        default_factory=dict
    )
    # Modo de una radiografia. None: el modo no esta configurado.
    radiograph_reconstruction: Callable[[], RadiographReconstructionStrategy] | None = None
    # Segmentacion de los volumenes de una radiografia, por organo (requisito 8 de la
    # guia: hoy el gancho PendingSegmentationStrategy).
    radiograph_segmentation: Mapping[OrganName, Callable[[], SegmentationStrategy]] = field(
        default_factory=dict
    )


class ServiceContainer:
    """Lo que el lifespan guarda en app.state.services."""

    def __init__(
        self, study_service: StudyService, factory: StrategyFactory, database: Database
    ) -> None:
        self.study_service = study_service
        self.factory = factory
        self._database = database
        self._closed = False

    def model_status(self) -> dict[str, bool]:
        """Que estrategias quedaron disponibles, por ejemplo {"segmentation:lung": True}."""
        return self.factory.availability()

    def close(self) -> None:
        """Cierra la base. Llamarlo dos veces no hace nada la segunda."""
        if not self._closed:
            self._closed = True
            self._database.close()


def radiograph_reconstruction_builder(
    service_settings: ReconstructionServiceSettings | None,
) -> Callable[[], RadiographReconstructionStrategy] | None:
    """El constructor de la estrategia remota, o None si falta AXON_URL o AXON_API_KEY."""
    if service_settings is None or not service_settings.configured:
        return None

    def build() -> RadiographReconstructionStrategy:
        client = ReconstructionServiceClient.from_settings(service_settings)
        if client is None:
            raise ModelNotAvailableError("Falta configurar AXON_URL o AXON_API_KEY.")
        return RemoteAxonStrategy(
            client,
            poll_seconds=service_settings.axon_poll_seconds,
            max_wait_seconds=service_settings.axon_max_wait_seconds,
        )

    return build


def default_strategy_builders(
    weights_store: ModelWeightsStore | None,
    model_settings: ModelSettings,
    service_settings: ReconstructionServiceSettings | None = None,
) -> StrategyBuilders:
    """Las estrategias reales. Cada una baja sus pesos solo cuando se construye."""

    def weights(object_path: str | None, variable: str) -> Path:
        if weights_store is None or not object_path:
            raise ModelNotAvailableError(f"Falta configurar MODEL_BUCKET o {variable}.")
        return weights_store.fetch(object_path)

    reconstruction: dict[str, Callable[[], ReconstructionStrategy]] = {
        "en1": lambda: NeuralEn1Strategy.from_weights(
            weights(model_settings.en1_weights_object, "EN1_WEIGHTS_OBJECT")
        ),
    }
    if model_settings.en1_v2_weights_object:
        reconstruction["en1_luna16"] = lambda: Luna16Strategy.from_weights(
            weights(model_settings.en1_v2_weights_object, "EN1_V2_WEIGHTS_OBJECT")
        )
    return StrategyBuilders(
        reconstruction=reconstruction,
        segmentation={
            OrganName.LUNG: lambda: LungUnetStrategy.from_weights(
                weights(model_settings.en2_weights_object, "EN2_WEIGHTS_OBJECT")
            ),
        },
        meshing=MarchingCubesStrategy,
        organ_meshing={
            # El pulmon es aire: su malla sale del aire que encierra el cuerpo.
            OrganName.LUNG: lambda: MarchingCubesStrategy(organ_region=LungAirRegion()),
        },
        radiograph_reconstruction=radiograph_reconstruction_builder(service_settings),
        radiograph_segmentation={
            # Gancho: aqui se registra el segmentador que entrene Lourdes.
            OrganName.LUNG: PendingSegmentationStrategy,
        },
    )


def build_service_container(
    settings: Settings,
    model_settings: ModelSettings,
    *,
    database_factory: Callable[[Settings], Database] = Database.from_settings,
    storage_factory: Callable[..., ObjectStorage] = ObjectStorage.from_settings,
    strategy_builders: StrategyBuilders | None = None,
    service_settings: ReconstructionServiceSettings | None = None,
) -> ServiceContainer:
    """Arma todos los servicios. Lanza solo si la base no se puede abrir."""
    database = database_factory(settings)
    database.open()

    storage = storage_factory(settings)
    weights_store = None
    if model_settings.model_bucket:
        model_storage = storage_factory(settings, bucket=model_settings.model_bucket)
        weights_store = ModelWeightsStore(model_storage, model_settings.model_cache_dir)

    builders = strategy_builders or default_strategy_builders(
        weights_store, model_settings, service_settings
    )
    factory = StrategyFactory(
        reconstruction_builders=builders.reconstruction,
        segmentation_builders=builders.segmentation,
        meshing_builder=builders.meshing,
        reconstruction_key=model_settings.reconstruction_strategy,
        organ_meshing_builders=builders.organ_meshing,
        radiograph_reconstruction_builder=builders.radiograph_reconstruction,
        radiograph_segmentation_builders=builders.radiograph_segmentation,
    )
    factory.preload()

    progress_store = ProcessingProgressStore(database)
    for strategy in factory.model_strategies():
        # trained_on queda vacio: la fecha real de entrenamiento no esta en los pesos
        # ni en el repositorio, y no se estima (Principio V).
        # TODO(TRAINING_DATE_EN1): registrar la fecha real de entrenamiento de EN-1.
        # TODO(TRAINING_DATE_EN2): registrar la fecha real de entrenamiento de EN-2.
        progress_store.register_model(
            strategy.model_name,
            strategy.model_version,
            trained_on=None,
            description=MODEL_DESCRIPTIONS.get(strategy.model_name),
        )

    loader = ProjectionLoader()
    board = RemoteJobBoard()
    study_service = StudyService(
        metadata_store=StudyMetadataStore(database, storage),
        result_store=ResultStore(database, storage),
        progress_store=progress_store,
        factory=factory,
        pipeline=ProcessingPipeline(loader, board),
        loader=loader,
        board=board,
    )
    # La tarea que procesaba un estudio en processing murio con el proceso anterior:
    # sin esto quedaria colgado y no se podria borrar (research.md R5 de 004).
    recovered = study_service.recover_interrupted_studies()
    logger.info("Estudios interrumpidos marcados como failed al arrancar: %d", len(recovered))
    return ServiceContainer(study_service, factory, database)
